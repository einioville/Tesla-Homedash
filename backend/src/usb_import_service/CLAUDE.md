# `usb_import_service/` — screensaver photos from a USB stick

Serves `USB_IMPORT_LIST` / `_SCAN` / `_START` / `_CLOSE` → `USB_IMPORT_STATE` (`0xE0`–`0xE4`,
`../utils/CLAUDE.md`) for the Options view's *Kuvakansio* row (*Tuo USB:ltä*). The screensaver
plays one **fixed folder**, `$XDG_CONFIG_HOME`(or `~/.config`)`/Tesla-Homedash/screensaver` —
`screensaver_dir()` here and `ScreensaverPhotos` in the frontend resolve the same path, which is why
neither side makes it configurable. Photos get there over scp or through this service. It runs
here, not in the frontend, because every step is a system call.

The flow: **list** (`lsblk -J -b`) → the user picks a volume → **scan** (mount with `udisksctl` if
nothing has, find `tesla_homedash_screensaver` in the volume's root, case-insensitively, and count
the images directly in it) → **start** (copy on a worker thread, progress ≤ 4 Hz) → unmount.

Load-bearing:

- **A device path from the client is never trusted.** `__volume()` re-lists and accepts only a path
  that `usb_volumes()` returns right now, so a request cannot name the system disk. That filter
  takes USB or hot-pluggable disks and **drops every disk with a volume mounted outside `/media/`,
  `/run/media/` or `/mnt/`**. The SD card holds `/` and `/boot/firmware`, and a USB SSD the Pi
  boots from holds `/` too, so all of their volumes are left out.
- **Unmount only what this service mounted** (`__mounted_here`). A stick the desktop automounted is
  left as it was. The state's `unmounted` flag is what lets the dialog say the stick can be pulled.
- **Nothing on the dashboard is overwritten.** `destination_name()` skips a file of the same name
  *and size* (so importing the same stick twice copies nothing), and gives a different file with a
  clashing name a ` (2)` suffix. Each copy is written as a hidden `.name.part` and renamed into
  place, so the screensaver never lists a half-written photo (hidden files are filtered on both
  sides).
- **The copy is its own task**, not the `USB_IMPORT_START` handler. The server cancels a client's
  handlers when that client disconnects, and a copy must neither die half-way with the stick
  mounted nor block a `CLOSE`, which sets a `threading.Event` checked between files.
- **One flow at a time, one client.** `LIST` takes the flow over (unless a copy is running) and
  every later request must come from that writer with that `flowId`; states go to it only.
- Free space is checked before copying, keeping 200 MB spare on a root filesystem shared with
  InfluxDB and the logs.

**Mount permission.** `udisksctl mount --no-user-interaction` goes through polkit. udisks allows it
for the active desktop session, and a process outside the session — a `systemd --user` unit can be
one — may be refused (`NotAuthorized`, reported to the dialog as missing rights). The README has the
polkit rule that grants it. A stick the desktop already mounted needs no permission at all.
