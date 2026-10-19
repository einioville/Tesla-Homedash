#!/usr/bin/env bash
#
# Configure + build (and optionally run) frontend_v2. Linux counterpart of
# scripts/build-frontend.ps1 — there is no MSVC environment to import, so this is
# mostly Qt kit detection plus the same Ninja configure + build of the
# appfrontend_v2 target into <repo>/frontend_v2/build. Object files are reused via
# ccache (or sccache) automatically when installed — see the compiler-cache block
# in frontend_v2/CMakeLists.txt.
#
# Options:
#   -c, --config <cfg>      CMake build type: Debug (default), Release, RelWithDebInfo
#   -q, --qt-prefix <path>  Qt kit path. Default: $QTDIR, else the newest
#                           ~/Qt/*/gcc_64 or ~/Qt/*/gcc_arm64; either only when
#                           it is at least the Qt that frontend_v2/CMakeLists.txt
#                           requires
#   -r, --run               Launch appfrontend_v2 after a successful build
#   -f, --fullscreen        With --run, start fullscreen (TESLA_HOMEDASH_FULLSCREEN=1)
#       --clean             Delete the build directory first (full reconfigure)
#       --qml-preview       Build for QML live preview (QT_QML_DEBUG; development
#                           only, never for the Pi). Off unless given, every time.
#   -h, --help              Show this help
#
# Examples:
#   ./scripts/build-frontend.sh --run
#   ./scripts/build-frontend.sh --config Release --clean
set -euo pipefail

CONFIG=Debug
RUN=0
FULLSCREEN=0
CLEAN=0
QML_PREVIEW=OFF
QT_PREFIX=""

# The comment block at the top, from its third line to the first line of code.
usage() { sed -n '3,/^[^#]/{/^#/p}' "$0" | sed 's/^# \{0,1\}//'; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        -c|--config)     CONFIG="${2:?--config needs a value}"; shift 2 ;;
        -q|--qt-prefix)  QT_PREFIX="${2:?--qt-prefix needs a value}"; shift 2 ;;
        -r|--run)        RUN=1; shift ;;
        -f|--fullscreen) FULLSCREEN=1; shift ;;
        --clean)         CLEAN=1; shift ;;
        --qml-preview)   QML_PREVIEW=ON; shift ;;
        -h|--help)       usage; exit 0 ;;
        *) echo "unknown option: $1" >&2; usage >&2; exit 1 ;;
    esac
done

case "$CONFIG" in
    Debug|Release|RelWithDebInfo) ;;
    *) echo "--config must be Debug, Release or RelWithDebInfo (got '$CONFIG')" >&2; exit 1 ;;
esac

REPO_ROOT="$(git rev-parse --show-toplevel)"
SRC="$REPO_ROOT/frontend_v2"
BUILD="$SRC/build"
[[ -f "$SRC/CMakeLists.txt" ]] || { echo "No frontend_v2/CMakeLists.txt under $REPO_ROOT" >&2; exit 1; }

# The oldest Qt the project builds with, from qt_standard_project_setup(REQUIRES x.y),
# so that a QTDIR left at an older or removed kit (a shell opened before a Qt upgrade)
# falls through to one that works instead of failing.
MIN_QT="$(sed -n 's/^qt_standard_project_setup(REQUIRES \([0-9.]*\)).*/\1/p' "$SRC/CMakeLists.txt")"
[[ -n "$MIN_QT" ]] || { echo "No qt_standard_project_setup(REQUIRES ...) in $SRC/CMakeLists.txt" >&2; exit 1; }

# A kit's Qt version; empty when the path holds no Qt kit.
kit_version() { [[ -x "$1/bin/qmake6" ]] && "$1/bin/qmake6" -query QT_VERSION 2>/dev/null || true; }

# Whether $1 is a Qt kit at least MIN_QT. sort -V puts 6.12.0 above 6.8.0, which a
# plain lexical sort would not.
kit_ok() {
    local version
    version="$(kit_version "$1")"
    [[ -n "$version" && "$(printf '%s\n' "$MIN_QT" "$version" | sort -V | head -1)" == "$MIN_QT" ]]
}

if [[ -n "$QT_PREFIX" ]]; then
    if ! kit_ok "$QT_PREFIX"; then
        found="$(kit_version "$QT_PREFIX")"
        echo "Not a Qt $MIN_QT+ kit: $QT_PREFIX (${found:+Qt }${found:-no bin/qmake6})" >&2
        exit 1
    fi
elif [[ -n "${QTDIR:-}" ]] && kit_ok "$QTDIR"; then
    QT_PREFIX="$QTDIR"
else
    if [[ -n "${QTDIR:-}" ]]; then
        echo "QTDIR=$QTDIR is not a Qt $MIN_QT+ kit; looking under ~/Qt"
    fi
    # BOTH kit names, not just gcc_64: the Qt installer calls the ARM64 kit
    # `gcc_arm64`, which is what the Raspberry Pi has (see README), and the Options
    # view's update card runs this script from a `systemd --user` unit where QTDIR is
    # not set either.
    while IFS= read -r kit; do
        if kit_ok "$kit"; then
            QT_PREFIX="$kit"
            break
        fi
    done < <(find "$HOME/Qt" -maxdepth 2 -type d \( -name gcc_64 -o -name gcc_arm64 \) \
                  2>/dev/null | sort -V -r)
    [[ -n "$QT_PREFIX" ]] || { echo "No Qt $MIN_QT+ kit under ~/Qt; install one, or pass --qt-prefix." >&2; exit 1; }
fi
echo "Qt kit:  $QT_PREFIX (Qt $(kit_version "$QT_PREFIX"))"
echo "Config:  $CONFIG"

# Plain `if` rather than `(( CLEAN )) && rm -rf ...` — same behaviour under
# `set -e` (the left operand of an && list is exempt from errexit), just easier to
# read and safe to move around; a bare `(( 0 ))` as a standalone statement would
# abort the script.
if (( CLEAN )); then
    echo "Cleaning: $BUILD"
    rm -rf "$BUILD"
fi

# Ninja when it is installed, otherwise whatever CMake defaults to. The Pi's
# setup instructions install cmake but not ninja, and a hard -G Ninja there fails
# at configure time complaining about CMAKE_MAKE_PROGRAM — an unhelpful error for
# a missing package, and a hard stop for the in-app updater.
GENERATOR=()
GENERATOR_NAME="Unix Makefiles"
if command -v ninja >/dev/null; then
    GENERATOR=(-G Ninja)
    GENERATOR_NAME="Ninja"
else
    echo "ninja not found; using CMake's default generator"
fi

# CMake REFUSES to reconfigure a build tree with a different generator, so a box
# that built once without ninja and then installed it would fail here forever
# with an opaque error — and for the in-app updater that means every update fails
# at the build step until someone SSHes in to delete the directory. Wipe instead.
if [[ -f "$BUILD/CMakeCache.txt" ]]; then
    PREVIOUS="$(sed -n 's/^CMAKE_GENERATOR:INTERNAL=//p' "$BUILD/CMakeCache.txt")"
    if [[ -n "$PREVIOUS" && "$PREVIOUS" != "$GENERATOR_NAME" ]]; then
        echo "Generator changed ($PREVIOUS -> $GENERATOR_NAME); reconfiguring from scratch"
        rm -rf "$BUILD"
    fi
fi
# The same for a new Qt kit: the cache keeps the old kit's Qt6_DIR, so a box that
# installs a newer Qt (picked by the glob above) would go on building against the
# old one, or against a mix of the two.
if [[ -f "$BUILD/CMakeCache.txt" ]]; then
    PREVIOUS="$(sed -n 's/^Qt6_DIR:[A-Z]*=//p' "$BUILD/CMakeCache.txt")"
    if [[ -n "$PREVIOUS" && "$PREVIOUS" != "$QT_PREFIX"/* ]]; then
        echo "Qt kit changed (${PREVIOUS%/lib/cmake/Qt6} -> $QT_PREFIX); reconfiguring from scratch"
        rm -rf "$BUILD"
    fi
fi

cmake -S "$SRC" -B "$BUILD" "${GENERATOR[@]}" \
      -DCMAKE_PREFIX_PATH="$QT_PREFIX" \
      -DCMAKE_BUILD_TYPE="$CONFIG" \
      -DFRONTEND_V2_QML_PREVIEW="$QML_PREVIEW"
# A job count, not a bare --parallel. Ninja ignores the flag (it picks its own
# default), but on the Makefiles path CMake turns it into `make -j` with NO
# limit — one compiler per ready target at once. A Qt Quick translation unit
# peaks in the hundreds of megabytes, so on a 4-core Pi that means swap thrash or
# the OOM killer, and the largest resident process there is the backend running
# the update: it can kill its own orchestrator, and with it the rollback.
cmake --build "$BUILD" --target appfrontend_v2 --parallel "$(nproc 2>/dev/null || echo 2)"

EXE="$BUILD/appfrontend_v2"
echo "Build OK -> $EXE"
if command -v ccache >/dev/null; then ccache --show-stats | head -5 || true; fi

if (( RUN )); then
    if (( FULLSCREEN )); then
        export TESLA_HOMEDASH_FULLSCREEN=1
    fi
    # WSL2 exposes the GPU as /dev/dxg, not a DRM render node, so Mesa cannot probe
    # a driver and silently lands on llvmpipe; the d3d12 gallium driver reaches the
    # real adapter, which the maps and graphs need. Guarded on the WSL2 shape, so it
    # is inert on the Pi, which has /dev/dri (scripts/CLAUDE.md).
    if [[ -e /dev/dxg && ! -d /dev/dri ]]; then
        export GALLIUM_DRIVER="${GALLIUM_DRIVER:-d3d12}"
    fi
    exec "$EXE"
fi
