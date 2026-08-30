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
#   -q, --qt-prefix <path>  Qt kit path. Default: $QTDIR, else newest ~/Qt/*/gcc_64
#   -r, --run               Launch appfrontend_v2 after a successful build
#   -f, --fullscreen        With --run, start fullscreen (TESLA_HOMEDASH_FULLSCREEN=1)
#       --clean             Delete the build directory first (full reconfigure)
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
QT_PREFIX="${QTDIR:-}"

usage() { sed -n '3,20p' "$0" | sed 's/^# \{0,1\}//'; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        -c|--config)     CONFIG="${2:?--config needs a value}"; shift 2 ;;
        -q|--qt-prefix)  QT_PREFIX="${2:?--qt-prefix needs a value}"; shift 2 ;;
        -r|--run)        RUN=1; shift ;;
        -f|--fullscreen) FULLSCREEN=1; shift ;;
        --clean)         CLEAN=1; shift ;;
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

# Newest ~/Qt/6.*/gcc_64 unless QTDIR or --qt-prefix says otherwise. sort -V puts
# 6.11.1 above 6.8.0, which a plain lexical sort would not.
if [[ -z "$QT_PREFIX" ]]; then
    QT_PREFIX="$(find "$HOME/Qt" -maxdepth 2 -type d -name gcc_64 2>/dev/null | sort -V | tail -1)"
fi
[[ -n "$QT_PREFIX" ]] || { echo "No Qt kit found; pass --qt-prefix or export QTDIR." >&2; exit 1; }
[[ -x "$QT_PREFIX/bin/qmake6" ]] || { echo "Not a Qt kit: $QT_PREFIX (no bin/qmake6)" >&2; exit 1; }
echo "Qt kit:  $QT_PREFIX"
echo "Config:  $CONFIG"

# Plain `if` rather than `(( CLEAN )) && rm -rf ...` — same behaviour under
# `set -e` (the left operand of an && list is exempt from errexit), just easier to
# read and safe to move around; a bare `(( 0 ))` as a standalone statement would
# abort the script.
if (( CLEAN )); then
    echo "Cleaning: $BUILD"
    rm -rf "$BUILD"
fi

cmake -S "$SRC" -B "$BUILD" -G Ninja \
      -DCMAKE_PREFIX_PATH="$QT_PREFIX" \
      -DCMAKE_BUILD_TYPE="$CONFIG"
cmake --build "$BUILD" --target appfrontend_v2

EXE="$BUILD/appfrontend_v2"
echo "Build OK -> $EXE"
if command -v ccache >/dev/null; then ccache --show-stats | head -5 || true; fi

if (( RUN )); then
    if (( FULLSCREEN )); then
        export TESLA_HOMEDASH_FULLSCREEN=1
    fi
    # WSL2 exposes the GPU as /dev/dxg, not a DRM render node, so Mesa cannot probe
    # a driver and silently lands on llvmpipe. Chromium >= 120 then refuses to
    # create a WebGL context on software GL ("WebGL1 blocklisted"), and Spotify's
    # login page runs reCAPTCHA Enterprise, which scores WebGL while building its
    # challenge — so the Options view's consent page loads but the challenge never
    # solves and the re-authorization dead-ends. The d3d12 gallium driver reaches
    # the real adapter.
    #
    # The second half is not optional. Once Chromium HAS a GPU, QtWebEngine tries
    # to import its frames as dma_buf native pixmaps, and Mesa's d3d12 EGL driver
    # does not expose EGL_EXT_image_dma_buf_import — so the GPU fix on its own
    # turns "renders, no WebGL" into "WebGL, renders nothing", a black panel with
    # "Failed to get native pixmap due to dma_buf acquisition failure" on repeat.
    # --disable-gpu-compositing keeps the GPU process (and WebGL with it) while
    # delivering frames through shared memory instead. Measured, 600x400 grab of a
    # solid-colour page: plain d3d12 = 0 % of the expected colour; with this flag
    # = 100 %, WebGL still reporting the real D3D12 adapter. It reaches only
    # QtWebEngine's Chromium, never Qt Quick, so the dashboard's own maps and
    # graphs keep the hardware path GALLIUM_DRIVER just gave them.
    #
    # Both are guarded on the WSL2 shape, so they are inert on the Pi, which has
    # /dev/dri and needs neither.
    if [[ -e /dev/dxg && ! -d /dev/dri ]]; then
        export GALLIUM_DRIVER="${GALLIUM_DRIVER:-d3d12}"
        export QTWEBENGINE_CHROMIUM_FLAGS="${QTWEBENGINE_CHROMIUM_FLAGS:-} --disable-gpu-compositing"
    fi
    exec "$EXE"
fi
