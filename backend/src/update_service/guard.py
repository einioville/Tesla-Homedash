#!/usr/bin/env python3
'''
The health gate's guard (#56). install.sh and every healthy switch copy it out of the release
into the directory holding the release folders, so a release that breaks cannot break its own
way back:

  guard.py            the backend unit's ExecStartPre, before every start
  guard.py --expire   the timer a switch arms, run when the switch's deadline passes

A switch to another release leaves switch.json beside this file:
{"from", "to", "deadline" (epoch s), "starts", "restoredSnapshot"}. The backend of "to" removes it
once that release is healthy (update_service). While it is there, this points `current` back at
"from" when the deadline passes or when the backend has been started more than MAX_STARTS times
(a crash loop), and leaves rollback.json saying so for the restored release to show. A power cut
mid-switch is the same case: the marker is still there at the next boot.

It never fails the unit: whatever goes wrong here, the backend still starts. Standard library
only, run by the system's python3 rather than a release's venv.
'''

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MARKER = ROOT / "switch.json"
RECORD = ROOT / "rollback.json"
CURRENT = ROOT / "current"
RELEASES = ROOT / "releases"
SNAPSHOTS = ROOT / "snapshots"
TIMER = "tesla-homedash-guard"
UNITS = ("tesla-homedash-backend.service", "tesla-homedash-frontend.service")
# Starts before a crash-looping release is given up on: RestartSec=5 makes this about 25 s.
MAX_STARTS = 5


def write_json(path: Path, data: dict) -> None:
    '''
    Replaces a JSON file atomically.
    Arguments:
        path (Path): The file.
        data (dict): Its new content.
    '''
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(data, handle)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def point_current(tag: str) -> None:
    '''
    Points `current` at a release with one rename, so it is never missing.
    Arguments:
        tag (str): The release folder's name.
    '''
    link = ROOT / "current.new"
    if link.is_symlink() or link.exists():
        link.unlink()
    os.symlink(Path("releases") / tag, link)
    os.replace(link, CURRENT)


def restore_snapshot(tag: str) -> None:
    '''
    Puts back the state files saved when a release was left (snapshot.json maps each saved name
    to where it came from).
    Arguments:
        tag (str): The release whose snapshot to restore.
    '''
    folder = SNAPSHOTS / tag
    index = json.loads((folder / "snapshot.json").read_text(encoding="utf-8"))
    for name, destination in index.get("files", {}).items():
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        if (folder / name).is_dir():
            shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(folder / name, target)
        else:
            shutil.copy2(folder / name, target)


def systemctl(*args: str) -> None:
    '''
    Runs one systemctl --user command, ignoring its outcome.
    Arguments:
        *args (str): The command after "systemctl --user".
    '''
    subprocess.run(("systemctl", "--user", *args), stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)


def roll_back(marker: dict, reason: str) -> None:
    '''
    Points `current` back at the release the switch came from.
    Arguments:
        marker (dict): The switch marker.
        reason (str): "crashloop" or "timeout", for rollback.json.
    '''
    previous, failed = marker.get("from", ""), marker.get("to", "")
    MARKER.unlink(missing_ok=True)
    if not previous or not (RELEASES / previous / ".complete").exists():
        print(f"guard: {failed} failed ({reason}) and there is no release to go back to")
        return
    if marker.get("restoredSnapshot") and (SNAPSHOTS / previous / "snapshot.json").exists():
        restore_snapshot(previous)
    point_current(previous)
    write_json(RECORD, {"failed": failed, "restored": previous, "reason": reason,
                        "at": int(time.time())})
    print(f"guard: rolled back {failed} -> {previous} ({reason})")


def arm_timer(seconds: float) -> None:
    '''
    Arms the transient timer that runs this script with --expire.
    Arguments:
        seconds (float): Seconds until it fires.
    '''
    systemctl("stop", f"{TIMER}.timer")
    systemctl("reset-failed", f"{TIMER}.service")
    subprocess.run(("systemd-run", "--user", "--quiet", "--collect", f"--unit={TIMER}",
                    f"--on-active={max(1, int(seconds))}s", sys.executable, "-I",
                    str(Path(__file__).resolve()), "--expire"),
                   stdin=subprocess.DEVNULL, timeout=30, check=False)


def on_start() -> None:
    '''ExecStartPre: count the start, roll back a crash loop or an expired switch.'''
    marker = json.loads(MARKER.read_text(encoding="utf-8"))
    marker["starts"] = int(marker.get("starts", 0)) + 1
    if marker["starts"] > MAX_STARTS:
        roll_back(marker, "crashloop")
        # The frontend still runs the failed release's binary. --no-block: its unit is ordered
        # after this one, which is still starting.
        systemctl("--no-block", "restart", UNITS[1])
        return
    remaining = float(marker.get("deadline", 0)) - time.time()
    if remaining <= 0:
        roll_back(marker, "timeout")
        systemctl("--no-block", "restart", UNITS[1])
        return
    write_json(MARKER, marker)
    # Gone after a reboot: the marker outlived a power cut, the timer did not.
    probe = subprocess.run(("systemctl", "--user", "is-active", "--quiet", f"{TIMER}.timer"),
                           stdin=subprocess.DEVNULL, timeout=30, check=False)
    if probe.returncode != 0:
        arm_timer(remaining)


def on_expire() -> None:
    '''The deadline passed with the marker still there: roll back and restart both halves.'''
    roll_back(json.loads(MARKER.read_text(encoding="utf-8")), "timeout")
    systemctl("--no-block", "restart", *UNITS)


def main() -> int:
    '''Runs one mode; always returns 0.'''
    try:
        if MARKER.exists():
            on_expire() if "--expire" in sys.argv[1:] else on_start()
    except Exception as e:  # noqa: BLE001 - the backend must start whatever happens here
        print(f"guard: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
