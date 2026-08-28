#!/usr/bin/env python
'''
PostToolUse hook: validate an edited file before the agent moves on.

Claude Code passes the tool invocation as JSON on stdin. This reads the edited
file path and dispatches to the cheapest check that can catch a build-breaking
mistake without a full build:

    backend/src/**.py -> python -m compileall backend/src   (CLAUDE.md 3.3)
    **.qml            -> qmllint, gated to syntax errors only

The qmllint gate matters: across the 53 files in frontend_v2 the linter reports
~750 style diagnostics (unqualified access, missing-property) but zero [syntax]
warnings and zero errors. Blocking on the style backlog would fire on untouched
code, so only [syntax] and Error: lines fail the hook -- the same contract as
compileall, which catches syntax and leaves style alone.

Missing tooling is never fatal: a machine without a Qt kit (the Raspberry Pi
deployment, a fresh clone) skips the QML check instead of blocking every edit.

Exit codes:
    0 -- nothing to check, tooling absent, or the check passed
    2 -- the file is broken; stderr is fed back to the agent to fix
'''
import json
import os
import re
import subprocess
import sys
from pathlib import Path

QMLLINT_ENV = "TESLA_HOMEDASH_QMLLINT"
# (root, glob) pairs, searched on every platform. Windows kits keep qmllint.exe
# under an MSVC kit directory; Linux kits (aqtinstall or the online installer)
# keep it under gcc_64. A root that does not exist yields nothing, so listing
# both costs nothing and keeps one hook working on Windows and WSL alike.
QT_SEARCH = (
    ("D:/Qt", "*/msvc2022_64/bin/qmllint.exe"),
    ("C:/Qt", "*/msvc2022_64/bin/qmllint.exe"),
    (str(Path.home() / "Qt"), "*/gcc_64/bin/qmllint"),
)
FATAL = re.compile(r"\[syntax\]|^Error:", re.MULTILINE)


def version_key(path: Path) -> tuple:
    '''
    Builds a sort key from a Qt kit directory name so 6.11.1 beats 6.8.0.
    Arguments:
        path (Path): Path to a qmllint executable inside a Qt kit
    '''
    for part in path.parts:
        if re.fullmatch(r"\d+(\.\d+)*", part):
            return tuple(int(n) for n in part.split("."))
    return (0,)


def find_qmllint() -> str | None:
    '''
    Locates the newest installed qmllint, or None when no Qt kit is present.
    An explicit TESLA_HOMEDASH_QMLLINT path always wins.
    '''
    override = os.environ.get(QMLLINT_ENV)
    if override and Path(override).exists():
        return override
    found = []
    for root, glob in QT_SEARCH:
        found.extend(Path(root).glob(glob))
    if not found:
        return None
    return str(max(found, key=version_key))


def qml_import_root(qml_file: Path) -> Path | None:
    '''
    Walks up from a QML file to the module root, so generated modules resolve.
    Without this the linter cannot import frontend_v2 and one unresolved import
    cascades into hundreds of spurious unqualified-access warnings.
    Arguments:
        qml_file (Path): Absolute path to the edited .qml file
    '''
    for parent in qml_file.parents:
        if (parent / "build").is_dir():
            return parent / "build"
    return None


def check_backend(project_dir: str) -> tuple[int, str]:
    '''
    Byte-compiles the backend package to catch Python syntax errors.
    Arguments:
        project_dir (str): Repository root to run the compile from
    '''
    result = subprocess.run(
        [sys.executable, "-m", "compileall", "-q", "backend/src"],
        cwd=project_dir, capture_output=True, text=True,
    )
    return result.returncode, result.stdout + result.stderr


def check_qml(qml_file: Path) -> tuple[int, str]:
    '''
    Lints one QML file, failing only on syntax errors.
    Arguments:
        qml_file (Path): Absolute path to the edited .qml file
    '''
    qmllint = find_qmllint()
    if not qmllint:
        return 0, ""
    args = [qmllint]
    import_root = qml_import_root(qml_file)
    if import_root:
        args += ["-I", str(import_root)]
    args.append(str(qml_file))
    result = subprocess.run(args, capture_output=True, text=True)
    output = result.stdout + result.stderr
    fatal = [line for line in output.splitlines() if FATAL.search(line)]
    if fatal:
        return 2, "\n".join(fatal)
    return 0, ""


def main() -> int:
    '''
    Reads the hook payload from stdin and runs the check matching the file type.
    '''
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    raw_path = (payload.get("tool_input") or {}).get("file_path") or ""
    if not raw_path:
        return 0
    file_path = Path(raw_path)
    posix = file_path.as_posix()
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or "."

    if posix.endswith(".py") and "backend/src" in posix:
        code, output = check_backend(project_dir)
    elif posix.endswith(".qml"):
        code, output = check_qml(file_path)
    else:
        return 0

    if code != 0:
        sys.stderr.write(output)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
