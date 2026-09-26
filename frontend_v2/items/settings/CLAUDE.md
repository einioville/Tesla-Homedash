# `items/settings/` — the Options view (Asetukset)

The QML for `views/SettingsView.qml`: `SettingsSidebar` + `SettingsPane`, the `Setting*` row
delegates, the status widgets and the popups. What they render is `frontend_v2/config/settings.json`
merged with the backend's `CONFIG_SCHEMA` (`backend/src/config_service/CLAUDE.md`). The singletons
behind several of these files are documented in `../../core/CLAUDE.md`:

| QML | Singleton (notes in `core/CLAUDE.md`) |
|---|---|
| `BackendProbeStatus.qml` | `Probe` |
| `SystemStatusPanel.qml` | `System` |
| `SpotifyAuthDetails.qml`, `SpotifyAuthPopup.qml`, `SpotifyAuthAlert.qml`, `DialogButton.qml` | `SpotifyAuth` |
| `SpotifyDeviceDetails.qml`, `SpotifyDevicePopup.qml` | `SpotifyDevice` |
| `UpdatePanel.qml`, `UpdateBanner.qml` | `Updater` |
| `ScreenPowerStatus.qml` | `Display` |
| `TeslaFieldTable.qml` | `TeslaFields` |
| `SettingsIssues.qml` | reads `Server`, `SpotifyAuth`, `SpotifyDevice`, `Settings` |
| everything else | `Settings` |

## Layout

Master/detail, three levels deep: `views/SettingsView.qml` is a sidebar + pane
split: `items/settings/SettingsSidebar.qml` lists the sections (one per schema group, its row
naming the subsections inside) and `SettingsPane.qml` renders the selected section as a stack
of **one card per subsection** (issue #30) — the same card the sidebar itself carries. The pane
is transparent; the cards are the containers, so nothing is nested inside a further border.
Sections are general (Yleinen, Media, Datan visualisointi, Sähkö, Tesla, Ylläpito) and the
subsections carry the detail.

Load-bearing:

- **Selection is a group ID, and it is sticky.** The section list grows from 3 entries to 8
  when the backend's schema arrives and shrinks again if the connection drops, so an index
  would silently select a different section. `currentSectionId` holds what the user *chose*
  and is never overwritten by a list change; `currentGroup` resolves it on read, falling back
  to the first section. That is what makes a backend section still be selected after a
  reconnect instead of the user being bounced to the first one.
- **Rows carry the card's only vertical padding.** A row centres its label block and its editor in
  at least 56px with at least 12px above and below; the card body adds nothing around the rows. A
  card margin on top of that made the first and last rows lopsided — more space toward the card
  edge than toward the divider. Only the intro (the card's `help` line and `status` widget), which
  has no padding of its own, is padded, and at the bottom too only when no row follows it.
- **Subsection order across the two halves is the local group's `sectionOrder`.** Local
  subsections are folded in before the backend's, so without it a backend card can never lead its
  section. `Settings` applies the list after the merge: named ids first, in that order, everything
  unnamed after them in its natural order (so a subsection added later still appears). Media uses
  it to put the backend's *Ääni* card above the local *Spotify* card and the backend's *Radio*.
- **Group `icon` is a SEMANTIC name** (`"charger"`, `"media"`, `"price"`, …), mapped to a
  resource by `SettingsSidebar.iconFor()`. The backend names icons without knowing anything
  about frontend assets; an unknown name falls back to the gear. Both schema builders copy
  *every* group-level key rather than an allow-list, so the next group field needs no code
  change (the icon was the first, and an allow-list is exactly what dropped it initially).

## Schema keys the delegates understand

Beyond the basics (`key`, `type`, `label`, `help`, `unit`, `min`/`max`/`step`, `nullable`,
`options`): **`hidden`** (kept out of the rendered rows while stored and persisted normally — for a
setting whose editor lives in the subsection's status widget; `updateChannel` is the example —
`core/CLAUDE.md`, under `Updater`. A subsection whose entries are ALL hidden and that names no
`status` is dropped, which is how the backend's `spotify` subsection — `spotifyDeviceId` /
`spotifyDeviceName`, written only by the device scan — renders nothing while staying the write
allow-list), **`details`** (a row-level live block under the label — see *Row details* below),
**`relevantWhen`** (`{key, equals|notEquals|notEmpty}`, or a list of
such rules that must ALL hold — `SettingRow`
fades a row whose controlling setting makes it meaningless **and sets `enabled: false` on it**,
since a control that changes a value with no effect is worse than one that visibly cannot be used;
`enabled` propagates down the item tree, so no editor needs to know about relevance. `notEmpty`
treats `""` and null alike, since a cleared nullable string can arrive as either. The screensaver
card is the list form's consumer: the switch is unavailable until a photo folder is set, and its
three tuning rows need the switch on *and* the folder. A setting that is a *precondition* for its
controller — that photo folder — must NOT carry a rule, or it becomes unsettable exactly when it
needs setting. Resolved through `Settings.valueOf()`, which reaches **both** halves, with
`Settings.valuesRevision` read purely to make the binding live), **`editor: "folder"`** (opt-in on a
`string` setting: the row becomes a tappable path that opens the folder browser instead of a text
field, and honoured only for `origin === "local"` — the browser walks the FRONTEND's filesystem, so
a backend key falls back to `SettingText` rather than silently browsing the wrong machine),
**`maxLabel`** (`SettingSlider` shows this text instead of the number at the slider's top stop — the
graph point cap uses it for *rajoittamaton*, which really does disable decimation), **`secret`** (a
`string` shown masked by `SettingText` except while it is being edited, and logged as `<hidden>` by
`Settings::setValue` — the MML map key; the saved file still holds it in clear, like `.env`) and **`warnBelow`
/ `warnAbove` + `warnMessage`** (issue
#34: `SettingRow` shows an inline caution while the value crosses the threshold; advisory only,
`min`/`max` remain the hard bounds — the myenergi idle poll interval is the first consumer).

## Delegates

`SettingRow` dispatches on `setting.type` to
`SettingSwitch` / `SettingNumber` / `SettingSlider` / `SettingText` / `SettingSelect` (the
last subclasses `TripComboBox`, inheriting the dark styling and the #9/#19 dropdown fixes) /
`SettingFolder`.

**Numeric settings default to `SettingNumber` — a `[−] [typed value] [+]` stepper — and sliders are
OPT-IN** via the schema's `editor: "slider"`. A slider only works when the exact number does not
matter; most settings here are the opposite. Dispatching on `type` alone gave `backendPort`
(1–65535) a slider whose 320px track is ~205 ports per pixel, and 13 of the 18 numeric settings were
similarly undraggable. Only genuine coarse dials carry the hint — `screensaverStackCount`,
`graphMaxPoints`, `graphSensitivity`, `graphRenderMarginFrac` and the map's `mapDefaultZoom`,
`mapSensitivity`, `mapWarpDeadzonePct`, `mapWarpLeadPct` (check `config/settings.json` for the
current set). **Rule of thumb: if the user knows the number they want, it is not a slider.** The slider is **one
line** — track, then the readout at its right, sized by `TextMetrics` for the widest text it can
show so the track keeps its length mid-drag — because an editor must centre on the label like the
others: a readout stacked above the track pushed the track ~8px below the label's centre line.
`SettingNumber`'s ± buttons hold-to-repeat (`../util/HoldRepeatArea.qml`), and it accepts typing
for big jumps. **A hold steps a pending value that only the field shows and commits it once, on
release** — every `Settings.setValue()` rebuilds `Settings.groups` (at once for a local key, on the
schema broadcast for a backend one), which destroys the delegate and the press with it, so writing
per step stopped every hold after one step and wrote `config.json` on each. `editor` is the
general per-type control HINT, not a numeric one — `slider`, `folder` and `time` are its consumers
today. **`editor: "time"`** keeps `SettingNumber` but reads the int as minutes since midnight
(`HH:MM`), makes the ± buttons **wrap** past midnight (min 0, max 1440 − step) and the field
read-only: the number pad has no colon, and with wrapping, eight 15-minute steps back from 00:00
reach 22:00. The night-mode window (`nightStartMin` / `nightEndMin`) is its consumer.

**`type: "action"` is a button, not a value.** `SettingAction.qml` renders it and calls
`Settings::invokeAction(key)`; nothing is stored, persisted or sent as `CONFIG_SET`. Keeping
actions in the schema is what lets the *Ylläpito* section — **restart the dashboard**,
**restart the backend**, **reboot the host** (`HOST_REBOOT`, #40) — be ordinary sidebar rows
instead of a widget bolted onto the view.
Entries carry `actionLabel` and optionally `requiresConnection` (which greys the backend
restart while disconnected). Both need a **second tap to confirm** (armed for 4 s, then it
lapses) — a modal would need a Cancel button and a way to dismiss it, which a fullscreen
keyboard-less panel does not have.

Three write-rate / semantics rules matter:
- the **slider commits on release**, not per frame (otherwise a drag rewrites the settings
  file — or fires a `CONFIG_SET` the backend persists — dozens of times a second);
- **text and number fields commit on `editingFinished`**, not per keystroke (otherwise every
  prefix of a typed value gets sent and rejected);
- a **nullable setting that is null renders as "—" / an empty field, not as its minimum**, and
  can be cleared back to null. `electricityPriceEurPerKwh` null means "no flat tariff, show —"
  in the Charging view, which is not the same as pricing energy at 0.000 €/kWh.

**Typing on the device** goes through the app's own on-screen keyboard (`frontend_v2/CLAUDE.md`).
The field delegates only steer it: `SettingText` turns off auto-capitalisation and prediction (its
values are hosts, URLs and serials, and prediction holds text in pre-edit, off `text`), and
`SettingNumber` asks for the number pad — the digits-only one unless the setting can go negative,
since that pad has no minus key. Both close the keyboard on Enter without dropping focus.
`SettingsPane` handles the other half: the keyboard covers the bottom half of the screen, so while
it is up the Flickable gets that much `bottomMargin` (otherwise the last rows could never scroll
above it) and `revealFocused()` scrolls the focused field into the strip that stays visible. It
runs on both a focus change and the inset change, because the inset only settles after the panel's
slide-in, well after focus moved.

## Row details

The row-level sibling of the subsection `status` hook below: **`details: "<id>"`** makes
`SettingRow` load a component under the label, resolved against its own small table
(`spotifyAuth` → `SpotifyAuthDetails`, `spotifyDevice` → `SpotifyDeviceDetails`). It is for facts
that belong to one row without being its value — the two Spotify actions carry no `help`, and their
details are the whole explanation. Both render through **`SettingDetails.qml`**: a status line led
by a green / amber / red / grey dot, then label–value pairs. Grey means *could not be established*,
which is kept apart from red on purpose.

- **`SpotifyAuthDetails`** — account (e-mail, else display name), *Tunnistettu*, *Voimassa asti*.
  Red only when the backend says the grant does not work; amber within 30 days of `validUntil`, past
  it while Spotify still accepts the grant (the 180-day estimate is deliberately early), and when
  the dates are unknown — a grant issued before the backend's grant record existed. Re-evaluates
  hourly, so amber arrives on a panel left on this view.
- **`SpotifyDeviceDetails`** — name (type) and id of the configured device. Amber when Spotify does
  not list it: Spotify lists only devices that are up, so *switched off* and *wrong id* look the
  same, and the text says both. It asks for `SpotifyDevice.configuredStatus` on construction; the
  row is rebuilt on every settings write, so the request is throttled in C++ (`core/CLAUDE.md`).

## Write results

**A write's result is shown beside the title of the row that made it** — "Tallennettu" in
green for 2.5 s, a rejection in red for 6 s — not in a banner elsewhere on the screen. The state
lives in `SettingsView.rowFeedback`, passed down through `SettingsPane`, **not in the row**: every
write rebuilds `Settings.groups`, which destroys the row that made the write before its result
arrives. A result with no row to sit beside — a keyless `CONFIG_SET_RESULT` (a refused restart or
reboot), a lost connection, a hidden setting such as `updateChannel` — goes to the app's
notification pill (`Notifications.post("settings", …)`) instead. A restart-tier write gets no extra
wording: the row's badge and the restart banner already say it.

## Issues and the fix spotlight

The header shows **"Ongelmia havaittu" + *Tarkista*** only while `SettingsIssues` reports
something (red dot if any issue is an error, amber for warnings only). It replaced the old
"Yhdistetty" indicator; a lost backend is itself an issue, which is what keeps a screen showing only
the local sections from reading as a bug.

- **`SettingsIssues.qml`** is a plain binding over the singletons, so an issue appears and clears by
  itself. Each names the **setting key that fixes it**; its section is looked up in
  `Settings.groups` rather than hardcoded, and an issue whose row is not in the schema right now
  offers no *Korjaa*. **While disconnected, only the connection is reported** — every other check
  reads backend state that is stale until it returns. Today's checks: backend unreachable →
  `backendHost`; Spotify grant broken, or valid for ≤ 30 more days → `spotifyReauth`; no Spotify
  device chosen, or chosen but not listed → `spotifyIdentifyDevice` (only with a working grant).
  A missing screensaver folder is deliberately *not* an issue: the switch is unavailable without
  one, so a user who wants no screensaver could never clear it. Add a check by pushing one more
  entry.
  The view refreshes `SpotifyDevice.configuredStatus` whenever it becomes current, since the device
  checks read it.
- **`SettingsIssuesPopup.qml`** is the list, drawn like `SpotifyDevicePopup` (scrim over the blurred
  view, opaque card) but anchored under the header. A tap beside the card closes it.
- **`SettingSpotlight.qml`** is where *Korjaa* ends: the view selects the fix's section and the view
  blurs its content (the same layer the dialogs use), while this draws a **crisp copy** of the row —
  a `ShaderEffectSource` over an opaque plate recreating the card behind it, ringed in the accent —
  until the next tap. The row cannot leave the blurred layer, so a copy is the only way to show it
  sharp. **A press on the copy dismisses and is not accepted**, so it reaches the real row beneath
  (tapping the highlighted *Kirjaudu* works first time); a press anywhere else is swallowed, so a
  blind tap on the blur cannot flip a switch nobody could see. The row is found by key on every
  80 ms tick (rows name themselves `settingRow:<key>`, `SettingsPane.rowItem()`), because a write
  rebuilds every row and a status widget settling can move one; the first ticks also scroll it to
  the middle of the pane, since the section may only just have been built. The copy is not drawn
  before the first tick: a just-selected section has not been laid out yet.

## Status widgets

The hook is a **subsection-level `status` key**: a subsection may name a runtime status widget,
which `SettingsPane` renders in the card via a `Loader` above the rows, resolving the name against a
small component table (`backendProbe`, `systemStatus`, `appUpdate`, `screenPower`,
`teslaProperties`). `active:` gates construction,
which is what keeps the probe from firing for a card that did not ask
for it. A subsection carrying a `status` but **no settings** is legitimate and is exempted from the
empty-section filter: the system-status card is entirely a status widget. It exists because not
every fact about a section fits in a setting row: *is that address reachable* belongs to the host
and port **together**. The verdict follows the SAVED values (what startup will actually use),
debounced 400 ms so editing host then port probes once against the final pair. Advisory only — the
write is never blocked, since the backend legitimately may not be up yet.

## Folder browser — `SettingFolder.qml` + `FolderPickerPopup.qml`

**The folder browser** is `core/folderbrowser.{hh,cpp}`, the QML singleton **`Folders`**, with
`items/settings/SettingFolder.qml` as the row editor and `items/settings/FolderPickerPopup.qml` as
the dialog. It exists because `FolderListModel` is a fine lister and a poor navigator: it reports
what is inside a directory it has already opened, and everything a picker needs *before* that —
does this path still exist, may we read it, what is its parent, where do we open when nothing is
configured, which removable volumes are mounted right now — has no QML type in this build at all
(`Qt.labs.platform` is not linked, and `QStorageInfo` has no QML API in any build). Every method
recomputes rather than caching: a stick can be plugged in while the Options view sits open.
Load-bearing details, all measured against Qt 6.11.1:
- **Navigation state is a plain path, never a URL.** `folder`, `parentFolder` and the `fileUrl`
  role are URLs, and recovering a path from one by stripping `file://` yields the percent-encoded
  form — `/media/pi/Kesäloma 2024` comes back mangled, `Settings.toFileUrl` then double-encodes it,
  and the screensaver silently plays nothing. Rows navigate by the **`filePath`** role, which is
  already an absolute decoded path, so no URL enters the state at all. It matters twice over that
  `Settings::setValue` **rejects a QUrl outright** for a `string` setting ("odotettiin tekstiä"):
  the most natural line to write fails at runtime with a toast and no folder saved.
- **Never `parentFolder`.** It returns an EMPTY url at `/`, and feeding that back into `folder`
  leaves the model pointing nowhere *and* computing every later parent from nothing — a permanently
  blank dialog on a device with no keyboard. `Folders.parentOf()` returns `""` at the root and the
  up button is simply inert there.
- **A folder whose name contains `#`, `%` or `?` cannot be browsed or played.** `FolderListModel`
  re-parses the decoded path as a URL internally, so `Loma#2024` truncates to `Loma` — status Null,
  count 0, even from a correctly encoded URL. `Folders.isBrowsable()` mirrors that test
  (`QUrl(path).path() == path`, a pure string parse, because the browser asks it once per visible
  row) and such rows render dimmed and inert. This is also why the row needs no text field: a
  hand-typed path to such a folder would not work either.
- **The picker is instantiated permanently, not behind a `Loader`.** `~FileInfoThread` takes the
  scan thread's mutex and `wait()`s for it while the scan holds that mutex for its whole directory
  walk — so unloading mid-scan blocks the **GUI thread** until a stale mount or a spun-down disk
  answers, and "Peruuta during a slow load" is exactly when a user taps. The cost is one listing of
  the process's working directory at startup and one idle watcher.
- **The image count is gated on `status`, not on `count` alone.** `count` is 0 while the background
  walk runs, so a naive binding flashes the amber "no images here" warning on every descend,
  including into folders that turn out to be full.
- **The card reserves the DOCK's band.** A popup inside a view cannot cover the dock (the general
  rule is in `frontend_v2/CLAUDE.md`), and the dock is also briefly on screen at startup. Measured
  on the 1280×800 target: the dock occupies **y 684–780**, and a 690px card centred in the window
  puts its button row at **y 681–725** — *Peruuta* and *Valitse tämä kansio* covered, with no way to
  reach them. The card is therefore top-anchored and sized to end above that band (30px of
  clearance, which still leaves ~8 directory rows). `SpotifyDevicePopup` escapes this only by being
  content-sized and short; anything taller has to reserve the band deliberately.

**Tapping anything only changes WHERE YOU ARE; the button at the bottom writes.** Nothing is ever
"selected", so there is no tap-to-select vs. double-tap-to-open overload, and a leaf folder with no
subdirectories — `DCIM/100CANON`, the usual case — is selectable at all, which a select-the-row
design cannot manage. The confirm button's label and width are fixed for the same reason
`SpotifyDevicePopup`'s are: a label naming the current folder would resize as the user navigates
and slide *Peruuta* under a finger already reaching for it.

**There is deliberately no text field.** It would not be an escape hatch: the only folders the
browser cannot reach contain `#`, `%` or `?`, and `ScreenSaver.qml` uses the same `FolderListModel`,
so it could not play them however the path was entered. (The in-app keyboard would make one
typeable; it just has nothing to add.)
