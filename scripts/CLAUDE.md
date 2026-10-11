# `scripts/` — build and session helpers

- `build-frontend.sh` / `build-frontend.ps1` (+ the `.cmd` shim) configure and build `frontend_v2`;
  usage is in the root `CLAUDE.md` §3.2 and §8. `new-session.ps1` / `finish-session.ps1` are the
  Windows-only worktree helpers — there is no Linux port.
- **`build-frontend.sh` is also run by the in-app updater** (`backend/src/update_service/`), which
  passes the Qt kit as `--qt-prefix`. Treat its command line as an interface and read that service's
  `CLAUDE.md` before changing it.
- It globs **both** `~/Qt/*/gcc_64` and `~/Qt/*/gcc_arm64` (the Raspberry Pi's kit name) and uses
  Ninja only when installed, because the Pi's setup does not install it.

## WSL2 GPU environment under `--run`

WSL2 exposes the GPU as `/dev/dxg` with **no `/dev/dri`**, so Mesa cannot probe a driver and lands
on llvmpipe. Under `--run` on that host shape the script exports `GALLIUM_DRIVER=d3d12`, which
reaches the real adapter: the Qt Quick scene graph moves off llvmpipe, so the maps and graphs get
faster. The Pi has `/dev/dri` and gets nothing.

**Reading the log:** two lines persist in the healthy state and are not failure signals — the
`libEGL warning: failed to get driver name` block and exactly ONE `EGL:
EGL_EXT_image_dma_buf_import extension is not supported` (Qt's `EGLHelper` always probes for it).
