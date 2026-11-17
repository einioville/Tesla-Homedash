#!/usr/bin/env bash
# Builds a Tesla-Homedash release on this machine and publishes it on GitHub's Releases page
# (#56). There is no CI: this script is the whole pipeline, run by the maintainer on a
# development machine (Linux or WSL2, x86_64), and the Pi's frontend is cross-compiled for arm64.
#
#   scripts/release.sh vX.Y.Z [--notes FILE]   build the pushed tag, sign it, publish it
#   scripts/release.sh --dry-run [COMMIT]      build COMMIT (default HEAD) into the cache only
#
# A release is built from its commit exported with git archive, never from the working tree, so
# what ships is exactly what the tag names. The notes are FILE, else the tag's annotation; a tag
# ending -rcN is published as a pre-release. Everything is uploaded to a draft first, and the
# draft is published only once every asset is up, so a device never lists half a release.
# A dry run neither signs nor uploads.
set -euo pipefail

SIGN_NAMESPACE="tesla-homedash-release"
SIGN_IDENTITY="release@tesla-homedash"
KEY="${TESLA_HOMEDASH_RELEASE_KEY:-$HOME/.ssh/tesla-homedash-release}"
CACHE="${TESLA_HOMEDASH_RELEASE_CACHE:-${XDG_CACHE_HOME:-$HOME/.cache}/Tesla-Homedash/release}"
# Fixed paths, so one release's build directory and compiler cache serve the next.
SRC="$CACHE/src"
BUILD="$CACHE/build-aarch64"
OUT="$CACHE/out"

die() { echo "release.sh: $*" >&2; exit 1; }
step() { printf '\n== %s\n' "$*"; }

repo="$(git rev-parse --show-toplevel 2>/dev/null)" || die "run this inside the repository"
cd "$repo"

mode=publish tag="" ref="" notes=""
while (($#)); do
    case "$1" in
        --dry-run)
            mode=dry; shift
            if (($#)) && [[ "$1" != -* ]]; then ref="$1"; shift; fi ;;
        --notes) notes="${2:?--notes needs a file}"; shift 2 ;;
        -h|--help) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        -*) die "unknown option $1" ;;
        *) [[ -z "$tag" ]] || die "one tag at a time"; tag="$1"; shift ;;
    esac
done

if [[ "$mode" == publish ]]; then
    [[ "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-rc[0-9]+)?$ ]] \
        || die "a release tag looks like v2.0.0 or v2.1.0-rc1, not '$tag'"
    commit="$(git rev-parse --verify --quiet "refs/tags/$tag^{commit}")" || die "no tag $tag here"
    # An annotated tag lists its object, then the commit it peels to; a lightweight one only the commit.
    remote="$(git ls-remote --tags origin "refs/tags/$tag" "refs/tags/$tag^{}" | awk '{print $1}' | tail -n 1)"
    [[ "$remote" == "$commit" ]] \
        || die "origin's $tag is '${remote:-missing}', not ${commit:0:12}: git push origin $tag"
    [[ -z "$notes" || -r "$notes" ]] || die "cannot read $notes"
    [[ -r "$KEY" ]] || die "no signing key at $KEY"
    gh auth status >/dev/null 2>&1 || die "gh is not logged in (gh auth login)"
    if draft="$(gh release view "$tag" --json isDraft --jq .isDraft 2>/dev/null)"; then
        [[ "$draft" == true ]] || die "$tag is already published"
        echo "Deleting the draft an earlier run left for $tag"
        gh release delete "$tag" --yes
    fi
    label="$tag"
else
    [[ -z "$tag" && -z "$notes" ]] || die "--dry-run takes only a commit"
    commit="$(git rev-parse --verify --quiet "${ref:-HEAD}^{commit}")" || die "no commit ${ref:-HEAD}"
    label="dry-run-${commit:0:7}"
fi

step "Exporting ${commit:0:12} as $label"
rm -rf "$SRC"
mkdir -p "$SRC"
git archive --format=tar "$commit" | tar -x -C "$SRC"
signers="$SRC/backend/src/update_service/release_signers"
[[ -f "$SRC/scripts/install.sh" ]] || die "$label has no scripts/install.sh"
[[ -f "$signers" ]] || die "$label trusts no signing key ($signers)"

step "Toolchain"
"$SRC/scripts/release/toolchain.sh"
eval "$("$SRC/scripts/release/toolchain.sh" --print-env)"
qt_host="${TESLA_HOMEDASH_QT_HOST:-$HOME/Qt/$QT_VERSION/gcc_64}"
[[ -x "$qt_host/libexec/moc" ]] \
    || die "the cross build runs this machine's Qt $QT_VERSION tools; none at $qt_host (TESLA_HOMEDASH_QT_HOST)"

step "Frontend (arm64)"
export TESLA_HOMEDASH_SYSROOT="$SYSROOT"
generator=()
command -v ninja >/dev/null && generator=(-G Ninja)
# CMake refuses a build directory made with another generator.
if [[ -f "$BUILD/CMakeCache.txt" ]]; then
    cached="$(sed -n 's/^CMAKE_GENERATOR:INTERNAL=//p' "$BUILD/CMakeCache.txt")"
    [[ "$cached" == "${generator[1]:-Unix Makefiles}" ]] || rm -rf "$BUILD"
fi
cmake -S "$SRC/frontend_v2" -B "$BUILD" "${generator[@]}" \
    -DCMAKE_TOOLCHAIN_FILE="$QT_ARM64/lib/cmake/Qt6/qt.toolchain.cmake" \
    -DQT_CHAINLOAD_TOOLCHAIN_FILE="$SRC/scripts/release/aarch64-linux.cmake" \
    -DQT_HOST_PATH="$qt_host" \
    -DCMAKE_BUILD_TYPE=Release \
    -DFRONTEND_V2_QML_PREVIEW=OFF \
    -DFRONTEND_V2_VERSION="$label" \
    -DFRONTEND_V2_BUILD_COMMIT="$commit"
cmake --build "$BUILD" --target appfrontend_v2
rm -rf "$OUT"
mkdir -p "$OUT/stage" "$OUT/assets"
cmake --install "$BUILD" --prefix "$OUT/stage/frontend" --strip >/dev/null
python3 -I "$SRC/scripts/release/bundle.py" --kit "$QT_ARM64" --build "$BUILD" \
    --bundle "$OUT/stage/frontend" --readelf aarch64-linux-gnu-readelf

step "Backend"
mkdir -p "$OUT/stage/backend"
tar -C "$SRC/backend" -c --exclude=__pycache__ --exclude=CLAUDE.md \
    src run.py pyproject.toml uv.lock .python-version | tar -x -C "$OUT/stage/backend"
cp "$SRC/config_template.json" "$OUT/stage/backend/"

step "Assets"
frontend_asset="tesla-homedash-frontend-$label-linux-aarch64.tar.gz"
backend_asset="tesla-homedash-backend-$label.tar.gz"
mtime="$(git show -s --format=%ct "$commit")"
pack() {
    tar -C "$OUT/stage" --sort=name --owner=0 --group=0 --numeric-owner --mtime="@$mtime" -c "$1" \
        | gzip -n -9 > "$OUT/assets/$2"
}
pack frontend "$frontend_asset"
pack backend "$backend_asset"
python3 -I "$SRC/scripts/release/manifest.py" --version "$label" --commit "$commit" \
    --source "$SRC" --frontend "$OUT/stage/frontend" --objdump aarch64-linux-gnu-objdump \
    --frontend-asset "$frontend_asset" --backend-asset "$backend_asset" \
    --out "$OUT/assets/manifest.json"
# The release's own copy of install.sh knows which release it is and which key signs it.
python3 -I - "$SRC/scripts/install.sh" "$OUT/assets/install.sh" "$label" "$signers" <<'EOF'
import shlex, sys
source, target, release, signers = sys.argv[1:]
text = open(source, encoding="utf-8").read()
if text.count('\nRELEASE=""\n') != 1 or text.count('\nSIGNERS=""\n') != 1:
    sys.exit("release.sh: install.sh needs one RELEASE=\"\" and one SIGNERS=\"\" line to stamp")
with open(signers, encoding="utf-8") as handle:
    trusted = handle.read().strip()
stamped = text.replace('\nRELEASE=""\n', "\nRELEASE=" + shlex.quote(release) + "\n", 1)
stamped = stamped.replace('\nSIGNERS=""\n', "\nSIGNERS=" + shlex.quote(trusted) + "\n", 1)
open(target, "w", encoding="utf-8").write(stamped)
EOF
chmod 755 "$OUT/assets/install.sh"
(cd "$OUT/assets" && sha256sum -- "$frontend_asset" "$backend_asset" manifest.json install.sh > SHA256SUMS)

if [[ "$mode" == dry ]]; then
    step "Dry run done — nothing signed or uploaded"
    ls -l "$OUT/assets"
    exit 0
fi

step "Signing"
ssh-keygen -Y sign -q -f "$KEY" -n "$SIGN_NAMESPACE" "$OUT/assets/SHA256SUMS"
ssh-keygen -Y verify -f "$signers" -I "$SIGN_IDENTITY" -n "$SIGN_NAMESPACE" \
    -s "$OUT/assets/SHA256SUMS.sig" < "$OUT/assets/SHA256SUMS" >/dev/null \
    || die "the signature does not verify against $label's own release_signers: wrong key?"

step "Publishing $tag"
flags=(--draft --verify-tag --title "$tag")
[[ "$tag" == *-rc* ]] && flags+=(--prerelease)
if [[ -n "$notes" ]]; then flags+=(--notes-file "$notes"); else flags+=(--notes-from-tag); fi
gh release create "$tag" "${flags[@]}" "$OUT/assets"/*
gh release edit "$tag" --draft=false
gh release view "$tag" --json url --jq .url
