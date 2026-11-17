#!/usr/bin/env bash
# Prepares what scripts/release.sh cross-compiles the frontend with, in a cache outside the
# repository: Qt's arm64 desktop kit and an Ubuntu 24.04 arm64 sysroot.
#
# Ubuntu 24.04 because Qt's own arm64 binaries are built on it (glibc 2.39, Qt's supported
# platforms page): linking against the same libraries keeps the bundle's floor at Qt's, so a
# device that runs Qt's kit runs the bundle. The sysroot is extracted from ports.ubuntu.com's
# packages with a private apt state, so nothing here needs root.
#
# Idempotent: a step whose result is already in the cache is skipped. --refresh rebuilds the
# sysroot (new security updates); delete the cache to start over.
set -euo pipefail

# The arm64 kit must be the same Qt version as the host kit whose moc, qmlcachegen and rcc the
# cross build runs (QT_HOST_PATH).
QT_VERSION="6.12.0"
# qttasktree only quiets find_package(Qt6Qml), whose QmlAssetDownloader plugin asks for it.
QT_MODULES=(qt5compat qtgraphs qtquick3d qtquicktimeline qtlocation qtpositioning qtmultimedia
            qtshadertools qtvirtualkeyboard qttasktree)
AQT="aqtinstall==3.3.0"
SUITE="noble"
MIRROR="http://ports.ubuntu.com/ubuntu-ports"
KEYRING="/usr/share/keyrings/ubuntu-archive-keyring.gpg"

# What the Qt libraries and plugins the bundle carries link against, plus the headers
# find_package(Qt6) looks for. Their dependencies come along.
SYSROOT_PACKAGES=(
    libc6-dev libstdc++-13-dev
    libgl-dev libegl-dev libgles-dev libopengl-dev libglx-dev libvulkan-dev libdrm-dev libgbm-dev
    libxkbcommon-dev libxkbcommon-x11-dev libwayland-dev libdecor-0-dev
    libx11-dev libx11-xcb-dev libxext-dev libxrender-dev libxi-dev libsm-dev libice-dev
    libxcb1-dev libxcb-cursor-dev libxcb-glx0-dev libxcb-icccm4-dev libxcb-image0-dev
    libxcb-keysyms1-dev libxcb-randr0-dev libxcb-render-util0-dev libxcb-shape0-dev
    libxcb-shm0-dev libxcb-sync-dev libxcb-util-dev libxcb-xfixes0-dev libxcb-xinerama0-dev
    libxcb-xinput-dev libxcb-xkb-dev
    libfontconfig-dev libfreetype-dev libglib2.0-dev libdbus-1-dev zlib1g-dev libzstd-dev
    libkrb5-dev libssl-dev libudev-dev libmtdev-dev libinput-dev
    libpulse-dev libasound2-dev libpipewire-0.3-dev libva-dev
)

CACHE="${TESLA_HOMEDASH_RELEASE_CACHE:-${XDG_CACHE_HOME:-$HOME/.cache}/Tesla-Homedash/release}"
QT_ROOT="$CACHE/qt"
QT_ARM64="$QT_ROOT/$QT_VERSION/gcc_arm64"
SYSROOT="$CACHE/sysroot-$SUITE-arm64"
APT_DIR="$CACHE/apt-$SUITE-arm64"

refresh=0
for arg in "$@"; do
    case "$arg" in
        --refresh) refresh=1 ;;
        --print-env)
            printf 'QT_VERSION=%q\nQT_ARM64=%q\nSYSROOT=%q\n' "$QT_VERSION" "$QT_ARM64" "$SYSROOT"
            exit 0 ;;
        -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
        *) echo "Unknown option: $arg" >&2; exit 2 ;;
    esac
done

die() { echo "toolchain.sh: $*" >&2; exit 1; }

for tool in aarch64-linux-gnu-g++ aarch64-linux-gnu-objdump apt-get dpkg-deb; do
    command -v "$tool" >/dev/null || die "$tool is missing (sudo apt install g++-aarch64-linux-gnu)"
done
[[ -r "$KEYRING" ]] || die "$KEYRING is missing (sudo apt install ubuntu-keyring)"
uv="$(command -v uv || echo "$HOME/.local/bin/uv")"
[[ -x "$uv" ]] || die "uv is missing (https://docs.astral.sh/uv/)"

mkdir -p "$CACHE"

if [[ ! -f "$QT_ARM64/lib/libQt6Core.so.6" ]]; then
    echo "== Qt $QT_VERSION arm64 kit -> $QT_ROOT"
    "$uv" tool run --from "$AQT" aqt install-qt linux_arm64 desktop "$QT_VERSION" linux_gcc_arm64 \
        --outputdir "$QT_ROOT" --modules "${QT_MODULES[@]}"
else
    echo "== Qt $QT_VERSION arm64 kit already in $QT_ARM64"
fi

if [[ "$refresh" == 1 || ! -f "$SYSROOT/.complete" ]]; then
    echo "== Ubuntu $SUITE arm64 sysroot -> $SYSROOT"
    rm -rf "$SYSROOT" "$APT_DIR"
    mkdir -p "$APT_DIR"/etc/apt/{apt.conf.d,preferences.d,sources.list.d} \
             "$APT_DIR"/var/lib/apt/lists/partial "$APT_DIR"/var/cache/apt/archives/partial
    : > "$APT_DIR/status"
    {
        echo "deb [arch=arm64 signed-by=$KEYRING] $MIRROR $SUITE main universe"
        echo "deb [arch=arm64 signed-by=$KEYRING] $MIRROR $SUITE-updates main universe"
        echo "deb [arch=arm64 signed-by=$KEYRING] $MIRROR $SUITE-security main universe"
    } > "$APT_DIR/etc/apt/sources.list"
    apt=(apt-get -q -o Dir="$APT_DIR" -o Dir::State::status="$APT_DIR/status"
         -o APT::Architecture=arm64 -o APT::Architectures::=arm64 -o Debug::NoLocking=true
         -o Acquire::Languages=none -o APT::Install-Recommends=false)
    "${apt[@]}" update
    "${apt[@]}" install -y --download-only "${SYSROOT_PACKAGES[@]}"

    # Merged /usr, as on the device: a package's /lib/... lands in usr/lib, and the
    # --keep-directory-symlink keeps tar from replacing these links with directories.
    mkdir -p "$SYSROOT/usr/lib" "$SYSROOT/usr/bin" "$SYSROOT/usr/sbin"
    ln -s usr/lib "$SYSROOT/lib"
    ln -s usr/bin "$SYSROOT/bin"
    ln -s usr/sbin "$SYSROOT/sbin"
    for deb in "$APT_DIR"/var/cache/apt/archives/*.deb; do
        dpkg-deb --fsys-tarfile "$deb" | tar -x --keep-directory-symlink -C "$SYSROOT"
    done
    # An absolute link (libGL.so -> /usr/lib/aarch64-linux-gnu/libGL.so.1) would resolve into
    # the build host's own /usr; point every one back inside the sysroot.
    while IFS= read -r -d '' link; do
        target="$(readlink "$link")"
        ln -sfn "$(realpath -m --relative-to="$(dirname "$link")" "$SYSROOT$target")" "$link"
    done < <(find "$SYSROOT" -type l -lname '/*' -print0)
    touch "$SYSROOT/.complete"
else
    echo "== sysroot already in $SYSROOT"
fi

echo "== toolchain ready"
