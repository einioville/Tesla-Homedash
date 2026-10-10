# `scripts/` — build and session helpers

- `build-frontend.sh` / `build-frontend.ps1` (+ the `.cmd` shim) configure and build `frontend_v2`;
  usage is in the root `CLAUDE.md` §3.2 and §8. `new-session.ps1` / `finish-session.ps1` are the
  Windows-only worktree helpers — there is no Linux port.
- **`build-frontend.sh` is also run by the in-app updater** (`backend/src/update_service/`), which
  passes the Qt kit as `--qt-prefix`. Treat its command line as an interface and read that service's
  `CLAUDE.md` before changing it.
- It globs **both** `~/Qt/*/gcc_64` and `~/Qt/*/gcc_arm64` (the Raspberry Pi's kit name) and uses
  Ninja only when installed, because the Pi's setup does not install it. Both were once hard-coded,
  which meant the script could never have worked on the deployment target.

## WSL2 GPU environment under `--run`

**Qt WebEngine has since left the build** (`frontend_v2/core/CLAUDE.md`, under `SpotifyAuth`), so
`QTWEBENGINE_CHROMIUM_FLAGS` currently has nothing to act on, while `GALLIUM_DRIVER=d3d12` still
moves the Qt Quick scene graph off llvmpipe onto the real adapter. The notes below record why the
script exports both, in case an embedded Chromium ever returns.

A GPU under WSL2 has **two halves that must land together**. WSL2 exposes the GPU as
`/dev/dxg` with **no `/dev/dri`**, so Mesa lands on llvmpipe and Chromium refuses every WebGL
context — which breaks the Spotify consent page specifically. `GALLIUM_DRIVER=d3d12` reaches the
real adapter. But once Chromium HAS a GPU it hands frames to Qt as **dma_buf native pixmaps**, and
Mesa's d3d12 EGL driver does not expose `EGL_EXT_image_dma_buf_import` — so that fix alone trades
"renders, no WebGL" for "WebGL, renders nothing": a black panel spamming *"Failed to get native
pixmap due to dma_buf acquisition failure"*. `QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu-compositing`
keeps the GPU process (and WebGL) while delivering frames through shared memory.
`scripts/build-frontend.sh` exports **both** under `--run` when it sees that host shape. Measured
on a 600×400 grab of a solid-colour page: plain d3d12 = 0 % of the expected colour, with the flag
= 100 %, WebGL still on the real D3D12 adapter. The flag reaches only QtWebEngine's Chromium, not
Qt Quick, so the dashboard keeps the hardware path — the scene graph moves off llvmpipe onto the
real adapter, so the maps and graphs get *faster*, not slower.

**Reading the log:** two lines persist in the healthy state and are not failure signals — the
`libEGL warning: failed to get driver name` block (the Qt Quick window, not Chromium) and exactly
ONE `EGL: EGL_EXT_image_dma_buf_import extension is not supported` (Qt's `EGLHelper` always probes
for it). The discriminators are the **repeated** `Failed to get native pixmap due to dma_buf
acquisition failure` lines and `WebGL1 blocklisted`; both must be absent. Measured: broken config
= 1 EGL probe line + 3 native-pixmap failures; fixed = 1 EGL probe line + 0.

Three switches that look plausible here are **no-ops**, so don't reach for them: `--in-process-gpu`
is already set unconditionally by QtWebEngine, `--disable-gpu-memory-buffer-compositor-resources`
is already false on Linux, and **SwiftShader is compiled out of the Qt binary build**
(`enable_swiftshader=false` in `qtwebengine/src/core/CMakeLists.txt`, no `libvk_swiftshader*`
shipped), so `--use-angle=swiftshader` silently falls through to ANGLE-on-llvmpipe.
