# `items/util/` — shared components

The dock's layering rules (it floats over every view; y 684–780 on the target) are in
`frontend_v2/CLAUDE.md`.

## `ScreenSaver.qml` and its photo folder

The photos come from one **fixed folder**, `~/.config/Tesla-Homedash/screensaver` (the `Photos`
singleton, `../../core/CLAUDE.md`). It is filled over scp or by the Options view's USB import
(`../settings/CLAUDE.md`). `FolderListModel.folder` binds to `Photos.url`, and the model watches the
folder, so photos copied in appear without a restart. With no photos the screensaver does not start
(`hasPhotos`).

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

A decider with no machinery of its own. With `nightModeEnabled` on and inside the
`nightStartMin`–`nightEndMin` window (local time; a window crossing midnight is the normal case, and
start == end means none) it raises `active`, and `Main.qml` routes it into what already exists: it
**replaces the screensaver settings** — `ScreenSaver.inhibited` holds the screensaver back — and
arms `Display` with `nightWakeMin` as the timeout even when the daytime power-off is off, so the
panel goes straight to off and inherits wake-on-touch, the update inhibit and the `OUTPUT_LOST`
handling (#43). **The screensaver is only held back where `Display.available`**: on a host without
wlopm the panel cannot be powered off, and the screensaver is all there is.

`ScreenPower` restarts its countdown on a timeout change, so the panel goes dark `nightWakeMin`
after the window opens rather than at once. **The window closing counts as a touch**
(`Idle.poke()`): through `Display`'s activity hook that wakes a dark panel whatever the daytime
settings would leave it in. `nowMin` is seeded at construction —
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
