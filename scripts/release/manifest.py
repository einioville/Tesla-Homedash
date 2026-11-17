#!/usr/bin/env python3
'''
Writes a release's manifest.json: which release it is, which assets hold it, and what a device
must provide to run it. The device's updater reads it before it downloads the bundles and shows a
release whose requirements are not met as not installable, naming what is missing
(backend/src/update_service/CLAUDE.md). Run with python3 -I by scripts/release.sh.
'''

import argparse
import ast
import json
import re
import subprocess
import sys
import time
from pathlib import Path

# Host commands the release needs that a fresh Raspberry Pi OS does not ship with: the updater's
# own (uv builds the backend's venv, ssh-keygen checks a release's signature, systemctl switches
# the units) and the spectrum's (pw-record); and, only on a device with its own panel, the
# screen-off's (wlopm, wlr-randr).
REQUIRED_COMMANDS = ("uv", "ssh-keygen", "systemctl", "pw-record")
DISPLAY_COMMANDS = ("wlopm", "wlr-randr")

_GLIBC = re.compile(r"GLIBC_(\d+)\.(\d+)")


def required_env(source: Path) -> list[str]:
    '''
    The .env variables the backend refuses to start without: start_services.REQUIRED_ENV_VARS.
    Arguments:
        source (Path): The exported source tree of the release.
    '''
    tree = ast.parse((source / "backend" / "src" / "start_services.py").read_text("utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "REQUIRED_ENV_VARS" for t in node.targets):
            return [str(v) for v in ast.literal_eval(node.value)]
    raise SystemExit("manifest.py: REQUIRED_ENV_VARS not found in start_services.py")


def glibc_floor(frontend: Path, objdump: str) -> str:
    '''
    The newest glibc symbol version any ELF file in the frontend bundle needs.
    Arguments:
        frontend (Path): The staged frontend bundle.
        objdump (str): objdump for the target architecture.
    '''
    newest = (0, 0)
    for path in frontend.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        with path.open("rb") as handle:
            if handle.read(4) != b"\x7fELF":
                continue
        out = subprocess.run([objdump, "-T", str(path)], capture_output=True, text=True).stdout
        for major, minor in _GLIBC.findall(out):
            newest = max(newest, (int(major), int(minor)))
    return f"{newest[0]}.{newest[1]}"


def main() -> int:
    '''Writes the manifest; returns the exit code.'''
    parser = argparse.ArgumentParser(description="Writes a release's manifest.json.")
    parser.add_argument("--version", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--source", required=True, type=Path, help="the exported source tree")
    parser.add_argument("--frontend", required=True, type=Path, help="the staged frontend bundle")
    parser.add_argument("--objdump", default="objdump")
    parser.add_argument("--frontend-asset", required=True)
    parser.add_argument("--backend-asset", required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    manifest = {
        "version": args.version,
        "commit": args.commit,
        "built": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "requires": {
            "arch": "aarch64",
            "glibc": glibc_floor(args.frontend, args.objdump),
            "python": (args.source / "backend" / ".python-version").read_text("utf-8").strip(),
            "commands": list(REQUIRED_COMMANDS),
            "displayCommands": list(DISPLAY_COMMANDS),
            "env": required_env(args.source),
        },
        "assets": {"frontend": args.frontend_asset, "backend": args.backend_asset},
    }
    args.out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
