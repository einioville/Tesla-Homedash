'''
Which version of the app this backend is. An installed release (#56) runs from
<root>/releases/<tag>/backend and carries the release's manifest.json beside its backend; a
development machine runs from a git checkout, and its version is the commit.
'''

import json
import subprocess
from functools import cache
from pathlib import Path

# <tag>/backend/src/utils/version.py
_RELEASE_CANDIDATE = Path(__file__).resolve().parents[3]


def release_dir() -> Path | None:
    '''The release folder this backend runs from, or None for a development checkout.'''
    if (_RELEASE_CANDIDATE.parent.name == "releases"
            and (_RELEASE_CANDIDATE / "manifest.json").is_file()):
        return _RELEASE_CANDIDATE
    return None


def install_root() -> Path | None:
    '''The directory holding releases/, `current` and the guard; None for a checkout.'''
    release = release_dir()
    return release.parent.parent if release is not None else None


@cache
def manifest() -> dict:
    '''The running release's manifest.json; empty for a development checkout.'''
    release = release_dir()
    if release is None:
        return {}
    try:
        return json.loads((release / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _git(*args: str) -> str:
    '''
    One read-only git query in the checkout this file is in; empty when git cannot answer.
    Arguments:
        *args (str): Arguments after "git".
    '''
    try:
        done = subprocess.run(("git", *args), cwd=Path(__file__).resolve().parent,
                              capture_output=True, text=True, timeout=10,
                              stdin=subprocess.DEVNULL, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


@cache
def app_version() -> str:
    '''
    The release's tag (v2.0.0), or for a checkout git's description of HEAD (the release tag on
    it, else the nearest one, commits since and the short commit, with -dirty for local changes);
    empty when neither can be read.
    '''
    if release_dir() is not None:
        return str(manifest().get("version", ""))
    return _git("describe", "--tags", "--match", "v[0-9]*", "--always", "--dirty")


@cache
def commit() -> str:
    '''The full commit this backend was built from; empty when unknown.'''
    if release_dir() is not None:
        return str(manifest().get("commit", ""))
    return _git("rev-parse", "HEAD")
