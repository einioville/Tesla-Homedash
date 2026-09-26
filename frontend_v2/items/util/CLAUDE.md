# `items/util/` — shared components

The dock's layering rules (it floats over every view; y 684–780 on the target) are in
`frontend_v2/CLAUDE.md`.

## `ScreenSaver.qml` and its photo folder

The photos come from one **fixed folder**, `~/.config/Tesla-Homedash/screensaver` (the `Photos`
singleton, `../../core/CLAUDE.md`). It is filled over scp or by the Options view's USB import
(`../settings/CLAUDE.md`). `FolderListModel.folder` binds to `Photos.url`, and the model watches the
folder, so photos copied in appear without a restart. With no photos the screensaver does not start
by day (`hasPhotos`); night mode's screensaver runs anyway, on a black screen.

Two measured facts about `FolderListModel` still shape it. **An empty `folder` at component
completion does NOT leave the model empty** — it falls back to *the application's working
directory* and lists whatever images sit there — which is why the folder must never be bound to an
empty value. And **`nameFilters` match case-sensitively by default**, so a lowercase-only list
silently skips every `DSC_0042.JPG` a camera writes (measured: 2 of 5 files matched, 4 with
`caseSensitive: false`). The extension list lives once, on `Photos`, because the Options view counts
images with it and a second copy would vouch for photos the screensaver never shows.

`ScreenSaver.inhibited` is held while `Updater.busy`, so the photos never fade in over a live
update (`../../core/CLAUDE.md`, under `Updater`).

## `NightSchedule.qml` — night mode (Yleinen > Yötila)

A decider with no machinery of its own. Inside the `nightStartMin`–`nightEndMin` window (local
time; a window crossing midnight is the normal case, and start == end means none) it raises
`screensaverActive` or `screenOffActive`, and `Main.qml` routes them into what already exists:
- **`screensaver`** shortens `Idle.timeoutMs` to `nightWakeMin` and sets `ScreenSaver.nightMode`,
  which lets the screensaver run **without the daytime toggle or a photo folder** — no folder means a
  plain black overlay, a dark panel for a host where the backlight cannot be cut. `pushNext()`
  therefore gates on `hasPhotos` rather than `folderModel.count`: with no folder the model lists
  the working directory (above), and the night screensaver would show whatever images sit there.
- **`screenOff`** arms `Display` with the short timeout even when the daytime power-off is off, so
  it inherits wake-on-touch, the update inhibit and the `OUTPUT_LOST` handling (#43).

`IdleWatcher` and `ScreenPower` both restart their countdown on a timeout change, so the panel goes
dark `nightWakeMin` after the window opens rather than at once. **The window closing counts as a
touch** (`Idle.poke()`): that lifts a night screensaver and, through `Display`'s activity hook, wakes
a dark panel whatever the daytime settings would leave it in. `nowMin` is seeded at construction —
a placeholder 0 would put the window in effect for one tick and poke the panel awake on the way out.

**Home return** (`homeReturnEnabled` / `homeReturnMin`, Yleinen > Navigointi) is a `Timer` in
`Main.qml` that runs only while a view other than the dashboard is current and restarts on every
`Idle.activity()`. It keeps counting under the screensaver, which is what makes the screensaver lift
onto the dashboard. The dock's auto-hide delay (`dockHideSec`) sits in the same card.

## `HoldRepeatArea.qml` — tap to step, hold to repeat

The press area behind every ± button (the climate card's target arrows, `SettingNumber`'s
steppers), so they all behave the same (#48). A tap steps on **release**, so a press that becomes a
drag steps nothing; a hold repeats after a 400 ms delay, and the release ending a hold adds no
extra step (a naive `onClicked` + running `Timer` stepped twice on any slightly long tap).
`canStep` false stops the repeat and swallows the tap, so a held button stops at its limit instead
of hammering it. `finished()` fires once per press however it ended, for callers that batch steps:
**`SettingNumber` must**, because a settings write rebuilds its own delegate
(`../settings/CLAUDE.md`), whereas the climate arrows can send every step — `Vehicle.plus_temp` only
moves the local setpoint and nothing reaches the car until climate is next toggled.
