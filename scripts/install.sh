#!/usr/bin/env bash
# Installs a Tesla-Homedash release on this device (#56): a new device, or one that runs from a
# git checkout and moves onto releases. Every release carries this script as an asset, stamped
# with the release and the key that signs it:
#
#   curl -fsSL https://github.com/einioville/Tesla-Homedash/releases/latest/download/install.sh | bash
#
# Options (piped: bash -s -- OPTIONS):
#   --no-display    a backend-only host: no frontend bundle and no dashboard unit
#   --checkout DIR  the git checkout whose .env moves out (default ~/Tesla-Homedash)
#
# It checks the signature over SHA256SUMS against the key it carries and every asset against
# SHA256SUMS before unpacking anything, unpacks into ~/.local/share/Tesla-Homedash/releases/<tag>,
# builds the backend's venv there, moves .env to ~/.config/Tesla-Homedash/.env, points the
# "current" link at the release and writes the systemd user units, which start whatever "current"
# points at. Unit files it replaces are kept as .bak. Running it again is harmless.
set -euo pipefail

# Stamped by scripts/release.sh into the copy a release carries.
RELEASE=""
SIGNERS=""

REPO="einioville/Tesla-Homedash"
ROOT="$HOME/.local/share/Tesla-Homedash"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/Tesla-Homedash"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
SIGN_NAMESPACE="tesla-homedash-release"
SIGN_IDENTITY="release@tesla-homedash"
BACKEND_UNIT="tesla-homedash-backend.service"
FRONTEND_UNIT="tesla-homedash-frontend.service"

die() { echo "install.sh: $*" >&2; exit 1; }
step() { printf '\n== %s\n' "$*"; }

display=1
checkout="$HOME/Tesla-Homedash"
while (($#)); do
    case "$1" in
        --no-display) display=0; shift ;;
        --checkout) checkout="${2:?--checkout needs a directory}"; shift 2 ;;
        -h|--help) sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) die "unknown option $1" ;;
    esac
done

[[ -n "$RELEASE" && -n "$SIGNERS" ]] \
    || die "this is the repository's copy; run the one a release carries (see the header)"
for tool in curl tar sha256sum ssh-keygen systemctl python3; do
    command -v "$tool" >/dev/null || die "$tool is missing"
done
uv="$(command -v uv || echo "$HOME/.local/bin/uv")"
[[ -x "$uv" ]] || die "uv is missing: curl -LsSf https://astral.sh/uv/install.sh | sh"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
base="https://github.com/$REPO/releases/download/$RELEASE"
fetch() { curl -fsSL --retry 3 -o "$work/$1" "$base/$1" || die "could not download $1"; }
verify() {
    (cd "$work" && grep -E "^[0-9a-f]{64}  $1\$" SHA256SUMS | sha256sum -c --quiet --strict -) \
        || die "$1 does not match SHA256SUMS"
}

step "Checking $RELEASE"
fetch SHA256SUMS
fetch SHA256SUMS.sig
printf '%s\n' "$SIGNERS" > "$work/signers"
ssh-keygen -Y verify -f "$work/signers" -I "$SIGN_IDENTITY" -n "$SIGN_NAMESPACE" \
    -s "$work/SHA256SUMS.sig" < "$work/SHA256SUMS" >/dev/null \
    || die "the signature over SHA256SUMS does not verify: not a genuine release"
fetch manifest.json
verify manifest.json

# The manifest's asset names and requirements, as shell assignments.
eval "$(python3 -I - "$work/manifest.json" "$display" <<'EOF'
import json, os, platform, shlex, shutil, sys
manifest = json.load(open(sys.argv[1], encoding="utf-8"))
display = sys.argv[2] == "1"
requires = manifest.get("requires", {})
missing = []
if display:
    if platform.machine() != requires.get("arch", platform.machine()):
        missing.append(requires["arch"] + "-suoritin")
    have = tuple(int(p) for p in platform.libc_ver()[1].split(".") if p.isdigit())
    need = tuple(int(p) for p in str(requires.get("glibc", "0")).split("."))
    if have < need:
        missing.append("glibc " + str(requires["glibc"]))
path = os.environ.get("PATH", "") + os.pathsep + os.path.expanduser("~/.local/bin")
commands = requires.get("commands", []) + (requires.get("displayCommands", []) if display else [])
missing += [c for c in commands if shutil.which(c, path=path) is None]
assets = manifest.get("assets", {})
print("frontend_asset=" + shlex.quote(assets.get("frontend", "")))
print("backend_asset=" + shlex.quote(assets.get("backend", "")))
print("required_env=" + shlex.quote(" ".join(requires.get("env", []))))
print("missing=" + shlex.quote(", ".join(missing)))
EOF
)"
[[ -z "$missing" ]] || die "$RELEASE needs what this device lacks: $missing"

dest="$ROOT/releases/$RELEASE"
if [[ -f "$dest/.complete" ]]; then
    step "$RELEASE is already unpacked in $dest"
else
    step "Downloading $RELEASE"
    fetch "$backend_asset"
    verify "$backend_asset"
    if ((display)); then
        fetch "$frontend_asset"
        verify "$frontend_asset"
    fi
    step "Unpacking into $dest"
    rm -rf "$dest"
    mkdir -p "$dest"
    tar -xzf "$work/$backend_asset" -C "$dest"
    if ((display)); then tar -xzf "$work/$frontend_asset" -C "$dest"; fi
    cp "$work/manifest.json" "$dest/manifest.json"
    (cd "$dest/backend" && "$uv" sync --locked --no-install-project --no-progress)
    touch "$dest/.complete"
fi

step "Settings in $CONFIG_DIR"
mkdir -p "$CONFIG_DIR"
if [[ ! -f "$CONFIG_DIR/.env" ]]; then
    if [[ -f "$checkout/.env" ]]; then
        mv "$checkout/.env" "$CONFIG_DIR/.env"
        echo "Moved $checkout/.env to $CONFIG_DIR/.env"
    else
        { echo "# Tesla-Homedash secrets (README, Backend). Fill these in:"
          for name in $required_env; do echo "$name="; done
          echo "TESLA_HOMEDASH_PASSWORD="; } > "$CONFIG_DIR/.env"
        echo "Wrote $CONFIG_DIR/.env with empty values: fill it in before the backend can start"
    fi
fi
chmod 600 "$CONFIG_DIR/.env"
if ! grep -q '^CONFIG_PATH=.' "$CONFIG_DIR/.env" && [[ ! -f "$CONFIG_DIR/backend_config.json" ]]; then
    cp "$dest/backend/config_template.json" "$CONFIG_DIR/backend_config.json"
    echo "Wrote $CONFIG_DIR/backend_config.json from the template"
fi

step "Switching to $RELEASE"
install -m 755 "$dest/backend/src/update_service/guard.py" "$ROOT/guard.py"
ln -sfn "releases/$RELEASE" "$ROOT/current.new"
mv -Tf "$ROOT/current.new" "$ROOT/current"

mkdir -p "$UNIT_DIR"
write_unit() {
    local unit="$UNIT_DIR/$1"
    if [[ -f "$unit" ]] && ! grep -q "$ROOT/current" "$unit"; then
        cp "$unit" "$unit.bak"
        echo "Kept the old $1 as $1.bak"
    fi
    cat > "$unit"
}
wayland=""
if ((display)); then wayland="Environment=WAYLAND_DISPLAY=wayland-1"; fi
write_unit "$BACKEND_UNIT" <<EOF
[Unit]
Description=Tesla-Homedash backend

[Service]
WorkingDirectory=-$ROOT/current/backend
# Before every start: rolls a switch that never got healthy back to the release before it.
ExecStartPre=/usr/bin/python3 -I $ROOT/guard.py
# Waits (up to 60 s) for the system-level InfluxDB, so the day's and month's baselines read right.
ExecStartPre=/bin/sh -c 'for i in \$(seq 1 60); do curl -sf http://localhost:8086/health >/dev/null && exit 0; sleep 1; done; exit 1'
ExecStart=$ROOT/current/backend/.venv/bin/python run.py
# A --user unit's PATH has no ~/.local/bin, where uv is.
Environment=PATH=$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin
$wayland
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF
if ((display)); then
    write_unit "$FRONTEND_UNIT" <<EOF
[Unit]
Description=Tesla-Homedash dashboard (Qt frontend)
After=graphical-session.target $BACKEND_UNIT
PartOf=graphical-session.target

[Service]
Environment=TESLA_HOMEDASH_FULLSCREEN=1
ExecStart=$ROOT/current/frontend/bin/appfrontend_v2
Restart=on-failure
RestartSec=5

[Install]
WantedBy=graphical-session.target
EOF
fi

systemctl --user daemon-reload
units=("$BACKEND_UNIT")
if ((display)); then units+=("$FRONTEND_UNIT"); fi
systemctl --user enable "${units[@]}" >/dev/null
systemctl --user restart "${units[@]}"

if [[ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" != yes ]]; then
    echo "The backend starts only once you log in; to start it at boot: loginctl enable-linger $USER"
fi
step "Tesla-Homedash $RELEASE is installed"
echo "Follow it with: journalctl --user -u $BACKEND_UNIT -f"
