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
