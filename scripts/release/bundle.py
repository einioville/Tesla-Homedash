#!/usr/bin/env python3
'''
Completes the frontend's release bundle: copies into it the Qt libraries, plugins and QML modules
the app uses, from the Qt kit it was built against.

Qt's own deployment (qt_generate_deploy_qml_app_script) does this for a native build but refuses a
cross-compiled one, and the release is cross-compiled for the Pi (scripts/release.sh). This copies
what Qt's deploy copies for the same app and kit: for every QML import the build's import scanner
found, the module's qmldir and plugin (the module's QML is compiled into the plugin); the plugins
in PLUGIN_TYPES and PLATFORMS; and every library those and the executable link against that the
kit provides. Libraries from the system's own directories stay out: the device provides them.

The layout is the kit's own (lib/, plugins/, qml/), so the RUNPATHs Qt gives its libraries and
plugins ($ORIGIN/../lib and the like) find each other inside the bundle unchanged.

Run with python3 -I; standard library only.
'''

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

# Qt's deploy picks plugin types by the modules the app links; these are the types it picked for
# this app (Qt 6.12), less vectorimageformats and egldeviceintegrations, which nothing here uses.
PLUGIN_TYPES = (
    "generic", "geoservices", "iconengines", "imageformats", "multimedia", "networkinformation",
    "platforminputcontexts", "platformthemes", "position", "tls",
    "wayland-decoration-client", "wayland-graphics-integration-client",
    "wayland-shell-integration", "xcbglintegrations",
)
# Of the platform plugins: Wayland for the Pi's desktop (labwc), xcb as Qt's default, offscreen
# for checking a bundle with no display.
PLATFORMS = ("libqwayland.so", "libqxcb.so", "libqoffscreen.so")

_IMPORT_LINE = re.compile(r'^set\(qml_import_scanner_import_\d+ "(.*)"\)$')
_NEEDED = re.compile(r"\(NEEDED\)\s+Shared library: \[(.+)\]")


def qml_imports(build_dir: Path) -> list[dict]:
    '''
    Reads the imports the build's qmlimportscanner found.
    Arguments:
        build_dir (Path): The CMake build directory of appfrontend_v2.
    '''
    scan = build_dir / ".qt" / "qml_imports" / "appfrontend_v2_build.cmake"
    entries = []
    for line in scan.read_text(encoding="utf-8").splitlines():
        match = _IMPORT_LINE.match(line)
        if not match:
            continue
        # A CMake list of KEY;VALUE pairs; a key's value may itself be a list (COMPONENTS), but
        # the keys read here (PATH, PLUGIN, RELATIVEPATH) are single values.
        fields = match.group(1).split(";")
        entry, key = {}, None
        for field in fields:
            if field.isupper() and field.replace("_", "").isalpha():
                key = field
                entry.setdefault(key, "")
            elif key is not None and not entry[key]:
                entry[key] = field
        entries.append(entry)
    return entries


def needed(readelf: str, path: Path) -> list[str]:
    '''
    The sonames one ELF file links against.
    Arguments:
        readelf (str): The readelf for the target architecture.
        path (Path): A shared library or executable.
    '''
    out = subprocess.run([readelf, "-d", str(path)], check=True, capture_output=True,
                         text=True).stdout
    return _NEEDED.findall(out)


def copy(src: Path, dest: Path) -> None:
    '''
    Copies one file, symlinks resolved, keeping its mode.
    Arguments:
        src (Path): The file in the kit.
        dest (Path): Where it goes in the bundle.
    '''
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src.resolve(), dest)


def main() -> int:
    '''Builds the bundle; returns the exit code.'''
    parser = argparse.ArgumentParser(
        description="Copies the Qt libraries, plugins and QML modules the app uses into its bundle.")
    parser.add_argument("--kit", required=True, type=Path, help="the Qt kit built against")
    parser.add_argument("--build", required=True, type=Path, help="appfrontend_v2's build dir")
    parser.add_argument("--bundle", required=True, type=Path,
                        help="the install prefix holding bin/appfrontend_v2")
    parser.add_argument("--readelf", default="readelf", help="readelf for the target")
    args = parser.parse_args()

    kit, bundle = args.kit.resolve(), args.bundle.resolve()
    exe = bundle / "bin" / "appfrontend_v2"
    if not exe.is_file():
        print(f"bundle.py: {exe} is missing (cmake --install first)", file=sys.stderr)
        return 1

    roots = [exe]
    kit_qml = kit / "qml"
    for entry in qml_imports(args.build):
        path, plugin, relative = (entry.get("PATH", ""), entry.get("PLUGIN", ""),
                                  entry.get("RELATIVEPATH", ""))
        if not (path and plugin and relative) or not Path(path).is_relative_to(kit_qml):
            continue
        dest = bundle / "qml" / relative
        copy(Path(path) / "qmldir", dest / "qmldir")
        library = Path(path) / f"lib{plugin}.so"
        copy(library, dest / library.name)
        roots.append(dest / library.name)

    for plugin_type in PLUGIN_TYPES:
        for library in sorted((kit / "plugins" / plugin_type).glob("*.so")):
            dest = bundle / "plugins" / plugin_type / library.name
            copy(library, dest)
            roots.append(dest)
    for name in PLATFORMS:
        dest = bundle / "plugins" / "platforms" / name
        copy(kit / "plugins" / "platforms" / name, dest)
        roots.append(dest)

    seen: set[str] = set()
    pending = list(roots)
    while pending:
        for soname in needed(args.readelf, pending.pop()):
            source = kit / "lib" / soname
            if soname in seen or not source.exists():
                continue
            seen.add(soname)
            copy(source, bundle / "lib" / soname)
            pending.append(bundle / "lib" / soname)

    (bundle / "bin" / "qt.conf").write_text("[Paths]\nPrefix = ..\n", encoding="utf-8")
    print(f"bundle.py: {len(roots) - 1} plugins and QML modules, {len(seen)} libraries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
