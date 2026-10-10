'''
Pins how the backend's run-a-command helpers behave: what they return for a
clean exit, a failing exit, a command that cannot start and one that hangs past
its timeout. Every command here is a harmless stand-in (sh, sleep, a fake
wlopm); nothing touches audio, mounts, git remotes or the display.

Runs under pytest, or standalone: `uv run python tests/test_process.py`.
'''
import asyncio
import os
import stat
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.audio_service.audio_backend import run_command  # noqa: E402
from src.display_service import display_service  # noqa: E402
from src.update_service.update_service import UpdateService  # noqa: E402
from src.usb_import_service import usb_import_service  # noqa: E402
from src.usb_import_service.usb_import_service import UsbImportService  # noqa: E402

ECHO_AND_FAIL = ["sh", "-c", "echo out; echo ' err ' >&2; exit 3"]
MISSING = "/nonexistent/tesla-homedash-test-binary"


def test_audio_run_command():
    assert asyncio.run(run_command(ECHO_AND_FAIL)) == (3, "out\n")
    assert asyncio.run(run_command([MISSING])) == (-1, "")
    started = time.monotonic()
    assert asyncio.run(run_command(["sleep", "5"], timeout=0.2)) == (-1, "")
    assert time.monotonic() - started < 2


def test_usb_import_run():
    run = UsbImportService._UsbImportService__run
    assert asyncio.run(run(*ECHO_AND_FAIL)) == (3, "out\n", "err")
    code, out, err = asyncio.run(run(MISSING))
    assert (code, out) == (-1, "") and "No such file" in err
    saved = usb_import_service._COMMAND_TIMEOUT_SECONDS
    usb_import_service._COMMAND_TIMEOUT_SECONDS = 0.2
    try:
        assert asyncio.run(run("sleep", "5")) == (-1, "", "sleep timed out")
    finally:
        usb_import_service._COMMAND_TIMEOUT_SECONDS = saved


class _NoVetoes:
    '''The one ConfigService call UpdateService makes at construction.'''

    def register_restart_veto(self, _name, _veto):
        '''Accepts and ignores the updater's restart veto.'''


def test_update_git():
    service = UpdateService(server=None, config_service=_NoVetoes())
    git = service._UpdateService__git
    code, out, err = asyncio.run(git("--version"))
    assert code == 0 and out.startswith("git version") and err == ""
    code, out, err = asyncio.run(git("-c", "alias.nap=!sleep 5", "nap", timeout=0.3))
    assert (code, out) == (-1, "") and err == "git -c alias.nap=!sleep 5 nap timed out"


def _fake_wlopm(directory: str, script: str) -> str:
    path = os.path.join(directory, "wlopm")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("#!/bin/sh\n" + script + "\n")
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    return path


def _display_with(script: str):
    directory = tempfile.mkdtemp()
    display_service._COMMAND = _fake_wlopm(directory, script)
    return display_service.DisplayService(server=None)


def test_display_run():
    original = display_service._COMMAND
    try:
        assert asyncio.run(_display_with("exit 0")._DisplayService__run(True)) is True
        assert asyncio.run(_display_with("echo no >&2; exit 1")._DisplayService__run(False)) is False
        display_service._RUN_TIMEOUT_SECONDS, saved = 0.2, display_service._RUN_TIMEOUT_SECONDS
        pid_file = os.path.join(tempfile.mkdtemp(), "pid")
        try:
            hung = _display_with(f"echo $$ > {pid_file}; exec sleep 5")
            assert asyncio.run(hung._DisplayService__run(True)) is False
        finally:
            display_service._RUN_TIMEOUT_SECONDS = saved
        # A wlopm that hangs is killed, not left running behind the timeout.
        with open(pid_file, encoding="utf-8") as fh:
            pid = int(fh.read())
        try:
            os.kill(pid, 0)
            assert False, f"wlopm stand-in {pid} still running after its timeout"
        except ProcessLookupError:
            pass
    finally:
        display_service._COMMAND = original


def test_display_check_lit():
    original = display_service._COMMAND
    try:
        lit = '''echo '[{"output": "HDMI-A-1", "power-mode": "on"}]' '''
        dark = '''echo '[{"output": "HDMI-A-1", "power-mode": "off"}]' '''
        cases = [
            (lit, display_service._LIT),
            (dark, display_service._DARK),
            ("echo '[]'", display_service._MISSING),
            ("echo nonsense", display_service._UNKNOWN),
            ("exit 2", display_service._UNKNOWN),
        ]
        for script, expected in cases:
            check = _display_with(script)._DisplayService__check_lit
            assert asyncio.run(check()) == expected, script
    finally:
        display_service._COMMAND = original


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS  {test.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL  {test.__name__}: {e}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(1 if failures else 0)
