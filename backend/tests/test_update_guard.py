'''
Tests for the health gate's guard (#56): guard.py run as the backend unit's ExecStartPre and as
its expiry timer, in a scratch install root holding two releases, against fake systemctl and
systemd-run commands that log their calls. A start counts itself and arms the timer; a crash
loop, a lapsed deadline and the timer each roll `current` back; a rollback puts back the
snapshot a downgrade replaced; and nothing a broken marker does can fail the unit.

Runs under pytest, or standalone: `python backend/tests/test_update_guard.py`.
'''
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

GUARD = Path(__file__).resolve().parents[1] / "src" / "update_service" / "guard.py"

# Logs its own name and arguments; `systemctl --user is-active` answers FAKE_TIMER_ACTIVE
# (3, systemd's "inactive", by default).
_FAKE = '''#!/bin/sh
echo "$(basename "$0") $*" >> "$FAKE_LOG"
case "$*" in *is-active*) exit "${FAKE_TIMER_ACTIVE:-3}" ;; esac
exit 0
'''


def make_root(tmp: Path) -> Path:
    '''
    Builds an install root: releases A and B, `current` at B, the guard beside them.
    Arguments:
        tmp (Path): A scratch directory.
    '''
    root = tmp / "root"
    for tag in ("A", "B"):
        (root / "releases" / tag).mkdir(parents=True)
        (root / "releases" / tag / ".complete").touch()
    os.symlink("releases/B", root / "current")
    (root / "guard.py").write_text(GUARD.read_text(encoding="utf-8"), encoding="utf-8")
    fakes = tmp / "bin"
    fakes.mkdir()
    for name in ("systemctl", "systemd-run"):
        (fakes / name).write_text(_FAKE, encoding="utf-8")
        (fakes / name).chmod(0o755)
    return root


def write_marker(root: Path, **fields) -> None:
    '''
    Leaves a switch marker from A to B, with any field overridden.
    Arguments:
        root (Path): The install root.
        **fields: Marker fields to override.
    '''
    marker = {"from": "A", "to": "B", "deadline": time.time() + 300, "starts": 0,
              "restoredSnapshot": False}
    marker.update(fields)
    (root / "switch.json").write_text(json.dumps(marker), encoding="utf-8")


def run_guard(root: Path, *args: str, timer_active: bool = False) -> tuple[int, list[str]]:
    '''
    Runs the guard as systemd would; returns its exit code and the fake commands' calls.
    Arguments:
        root (Path): The install root.
        *args (str): Arguments to guard.py.
        timer_active (bool): Whether the fake reports the expiry timer as running.
    '''
    log = root.parent / "calls.log"
    log.unlink(missing_ok=True)
    env = dict(os.environ, PATH=f"{root.parent / 'bin'}:{os.environ['PATH']}",
               FAKE_LOG=str(log), FAKE_TIMER_ACTIVE="0" if timer_active else "3")
    done = subprocess.run([sys.executable, "-I", str(root / "guard.py"), *args], env=env,
                          capture_output=True, text=True, timeout=60)
    calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return done.returncode, calls


def current(root: Path) -> str:
    '''The release `current` points at.'''
    return os.readlink(root / "current")


def test_no_marker_is_a_no_op():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(Path(tmp))
        code, calls = run_guard(root)
        assert code == 0 and calls == [] and current(root) == "releases/B"


def test_start_counts_and_arms_the_timer():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(Path(tmp))
        write_marker(root)
        code, calls = run_guard(root)
        assert code == 0 and current(root) == "releases/B"
        assert json.loads((root / "switch.json").read_text())["starts"] == 1
        armed = [c for c in calls if c.startswith("systemd-run")]
        assert len(armed) == 1 and "--unit=tesla-homedash-guard" in armed[0]
        assert armed[0].endswith("--expire") and "--on-active=29" in armed[0]


def test_a_running_timer_is_left_alone():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(Path(tmp))
        write_marker(root, starts=2)
        calls = run_guard(root, timer_active=True)[1]
        assert not [c for c in calls if c.startswith("systemd-run")]
        assert json.loads((root / "switch.json").read_text())["starts"] == 3


def test_a_crash_loop_rolls_back():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(Path(tmp))
        write_marker(root, starts=5)
        code, calls = run_guard(root)
        assert code == 0 and current(root) == "releases/A"
        assert not (root / "switch.json").exists()
        record = json.loads((root / "rollback.json").read_text())
        assert (record["failed"], record["restored"], record["reason"]) == ("B", "A", "crashloop")
        assert "systemctl --user --no-block restart tesla-homedash-frontend.service" in calls


def test_a_lapsed_deadline_rolls_back():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(Path(tmp))
        write_marker(root, deadline=time.time() - 1)
        run_guard(root)
        assert current(root) == "releases/A"
        assert json.loads((root / "rollback.json").read_text())["reason"] == "timeout"


def test_the_timer_rolls_back_and_restarts_both():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(Path(tmp))
        write_marker(root)
        code, calls = run_guard(root, "--expire")
        assert code == 0 and current(root) == "releases/A"
        assert ("systemctl --user --no-block restart tesla-homedash-backend.service "
                "tesla-homedash-frontend.service") in calls


def test_a_rollback_restores_the_replaced_snapshot():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(Path(tmp))
        state = Path(tmp) / "state"
        (state / "tls").mkdir(parents=True)
        (state / "config.json").write_text("restored by the downgrade")
        (state / "tls" / "cert.pem").write_text("old cert")
        snapshot = root / "snapshots" / "A"
        (snapshot / "tls").mkdir(parents=True)
        (snapshot / "config.json").write_text("A's config")
        (snapshot / "tls" / "cert.pem").write_text("A's cert")
        (snapshot / "snapshot.json").write_text(json.dumps({"files": {
            "config.json": str(state / "config.json"), "tls": str(state / "tls")}}))
        write_marker(root, starts=5, restoredSnapshot=True)
        run_guard(root)
        assert (state / "config.json").read_text() == "A's config"
        assert (state / "tls" / "cert.pem").read_text() == "A's cert"


def test_no_release_to_go_back_to():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(Path(tmp))
        (root / "releases" / "A" / ".complete").unlink()
        write_marker(root, starts=5)
        assert run_guard(root)[0] == 0 and current(root) == "releases/B"
        assert not (root / "switch.json").exists() and not (root / "rollback.json").exists()


def test_a_broken_marker_never_fails_the_unit():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(Path(tmp))
        (root / "switch.json").write_text("{not json")
        assert run_guard(root)[0] == 0 and current(root) == "releases/B"


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"ok  {test.__name__}")
    print(f"{len(tests)} passed")
