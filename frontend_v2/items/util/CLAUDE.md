# `items/util/` — shared components

The dock's layering rules (it floats over every view; y 684–780 on the target) are in
`frontend_v2/CLAUDE.md`. The folder picker that sets `screensaverDir` is in `../settings/CLAUDE.md`.

## `ScreenSaver.qml` and the `screensaverDir` setting

The **`screensaverDir`** setting (issue #33) is the pattern for a path: `string` + `nullable`,
defaulting from `TESLA_HOMEDASH_SCREENSAVER_DIR` through the schema's `env` key. `AppConfig` does
not read that variable at all — two readers would be two sources of truth, and the setting is
live. `ScreenSaver.qml` binds `FolderListModel.folder` to `Settings.toFileUrl(Theme.screensaverDir)`
(`QUrl::fromLocalFile`, empty in → empty out). `coerceLocal` has the matching rule: an empty
string is rejected unless the setting is `nullable`.

It is **picked, not typed** (`editor: "folder"` → `SettingFolder` → `FolderPickerPopup`). Two
measured facts about `FolderListModel` shape `ScreenSaver.qml`. **An empty `folder` at component
completion does NOT leave the model empty** — it falls back to its documented default, *the
application's working directory*, and lists whatever images sit there — so "no folder, no
screensaver" has to be delivered explicitly, by the `Theme.screensaverDir.length > 0` term in
`ScreenSaver.active`. And **`nameFilters` match case-sensitively by default**, so a lowercase-only
list silently skips every `DSC_0042.JPG` a camera writes (measured: 2 of 5 files matched, 4 with
`caseSensitive: false`). The extension list lives once on the `Folders` singleton, because the
picker counts images with it to say "42 kuvaa" and a second copy would vouch for folders the
screensaver plays as empty.

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
