# `scripts/` — build and session helpers

- `build-frontend.sh` / `build-frontend.ps1` (+ the `.cmd` shim) configure and build `frontend_v2`;
  usage is in the root `CLAUDE.md` §3.2 and §8. `new-session.ps1` / `finish-session.ps1` are the
  Windows-only worktree helpers (the `parallel-worktree` skill) — there is no Linux port.
- It globs **both** `~/Qt/*/gcc_64` and `~/Qt/*/gcc_arm64` (the Raspberry Pi's kit name) and uses
  Ninja only when installed, because the Pi's setup does not install it.
- **A kit counts only if it is at least the Qt that `frontend_v2/CMakeLists.txt` requires** (its
  `qt_standard_project_setup(REQUIRES x.y)`, read each run, so a Qt bump needs no script change; the
  version from the kit's `qmake6 -query QT_VERSION`). A `QTDIR` left at an older or removed kit — any
  shell opened before a Qt upgrade — is reported and skipped for the newest kit that qualifies; an
  explicit `--qt-prefix` that does not qualify stops the build with the reason.
- **`--qml-preview` (`-QmlPreview`) is passed to CMake on every configure, ON or OFF**, never left to
  the cache: it builds in the QML debug service for the live preview (`frontend_v2/CLAUDE.md`,
  *QML live preview*), which must not survive into a later plain build — least of all on the Pi.
- **It wipes the build directory when the generator or the Qt kit changed** since the last
  configure (`CMAKE_GENERATOR`, `Qt6_DIR` in the cache): CMake refuses a new generator outright, and
  a new kit would otherwise go on building against the cached old one. A box that installs a newer
  Qt — picked by the glob — rebuilds from scratch once.
- `gen-map-coverage.py` writes `frontend_v2/items/tesla/MapCoverage.js`, where MML's orthophoto has
  imagery (`frontend_v2/items/tesla/CLAUDE.md`, *The basemap*). Run once, by hand, with shapely and
  pyproj (`uv run --with`); its header has the steps.

## Releases — `release.sh`, `release/`, `install.sh` (#56)

There is no CI, by choice: `release.sh vX.Y.Z`, run by the maintainer on a development machine
(Linux or WSL2, x86_64), is the whole pipeline. It builds the commit the pushed tag names, exported
with `git archive` into the cache (`~/.cache/Tesla-Homedash/release`, or
`TESLA_HOMEDASH_RELEASE_CACHE`), and runs the helpers in `release/` from that export, never from
the working tree. `--dry-run [COMMIT]` builds without signing or uploading; to build the working
tree as it stands, give it `git commit-tree` of a scratch index (`GIT_INDEX_FILE`), which touches
no ref.

**The assets** of a release, all in `SHA256SUMS`, which `SHA256SUMS.sig` signs:
`tesla-homedash-frontend-<tag>-linux-aarch64.tar.gz` (`frontend/`: `bin/`, `lib/`, `plugins/`,
`qml/`), `tesla-homedash-backend-<tag>.tar.gz` (`backend/`: `src/`, `run.py`, `pyproject.toml`,
`uv.lock`, `.python-version`, `config_template.json`), `manifest.json` and `install.sh`. The
tarballs are owned by root with the commit's time, so a rebuild is byte-identical.

- **The Pi's frontend is cross-compiled.** `release/toolchain.sh` caches Qt's arm64 kit (aqtinstall,
  pinned) and an Ubuntu 24.04 arm64 sysroot: Qt builds its own arm64 binaries on 24.04, so linking
  against the same libraries keeps the bundle's glibc floor at Qt's. The sysroot is apt run rootless
  on a private state directory, the packages extracted with `--keep-directory-symlink` over merged-
  /usr links and every absolute symlink pointed back inside. The kit must be exactly the host kit's
  Qt version: `QT_HOST_PATH` runs the host's moc, qmlcachegen, rcc and qsb.
- `release/aarch64-linux.cmake` is the kit's `qt.toolchain.cmake`'s `QT_CHAINLOAD_TOOLCHAIN_FILE`.
  It takes the sysroot from `TESLA_HOMEDASH_SYSROOT` in the environment, because CMake re-reads a
  toolchain file for every try_compile, and points pkg-config into the sysroot.
- **Qt's own deployment refuses a cross build** ("not implemented … cross-compiled"), so
  `release/bundle.py` copies what it would: per QML import, its `qmldir` and plugin; the plugin
  types it lists; and every library those and the binary link against that the kit has. Checked
  against Qt's deploy of a native build, file for file: the same, less the eglfs and Lottie plugins
  left out on purpose. Qt's deploy takes only the xcb platform plugin, so the bundle adds wayland
  (the Pi's labwc) and offscreen.
- **A bundle runs on the dev box under qemu-user** (binfmt is registered there):
  `QEMU_LD_PREFIX=<sysroot> QT_QPA_PLATFORM=offscreen <bundle>/bin/appfrontend_v2`, with scratch
  `TESLA_HOMEDASH_SETTINGS_FILE`, `_CREDENTIALS_FILE` and `_LOG_DIR`. It loads the whole UI.
- `release/manifest.py` takes the requirements from the code where they live:
  `REQUIRED_ENV_VARS` from `start_services.py`, the Python from `backend/.python-version`, and the
  glibc floor measured with objdump over the bundle. The host commands are its own two lists, the
  second only for a device with its own panel.
- **Signing**: `ssh-keygen -Y sign` with `~/.ssh/tesla-homedash-release` (namespace
  `tesla-homedash-release`, identity `release@tesla-homedash`), checked against the release's own
  `backend/src/update_service/release_signers`. A device checks a new release against the key of
  the release it runs, so a new key ships in a release the old key signs.
- **`install.sh`'s copy in a release is stamped** with its `RELEASE` and `SIGNERS`, so it installs
  exactly that release and trusts its key; the repository's copy refuses to run. It installs only
  what `--no-display` leaves, unpacks into the layout `update_service` keeps, and writes the systemd
  units, keeping replaced ones as `.bak`. Tested in a scratch `HOME` with stand-ins for `curl`
  (serving the out directory's assets), `systemctl` and `loginctl`, and a throwaway key re-stamped
  into a copy.

## WSL2 GPU environment under `--run`

WSL2 exposes the GPU as `/dev/dxg` with **no `/dev/dri`**, so Mesa cannot probe a driver and lands
on llvmpipe. Under `--run` on that host shape the script exports `GALLIUM_DRIVER=d3d12`, which
reaches the real adapter: the Qt Quick scene graph moves off llvmpipe, so the maps and graphs get
faster. The Pi has `/dev/dri` and gets nothing.

**Reading the log:** two lines persist in the healthy state and are not failure signals — the
`libEGL warning: failed to get driver name` block and exactly ONE `EGL:
EGL_EXT_image_dma_buf_import extension is not supported` (Qt's `EGLHelper` always probes for it).
