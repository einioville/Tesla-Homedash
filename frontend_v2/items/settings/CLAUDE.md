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
| `UsbImportPopup.qml` | `UsbImport` |
| `ScreensaverPhotosDetails.qml` | `Photos` |
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
**`relevantWhen`** (`{key, equals|notEquals}` or `{condition}`, or a list of such rules that must
ALL hold — `SettingRow`
fades a row whose controlling setting makes it meaningless **and sets `enabled: false` on it**,
since a control that changes a value with no effect is worse than one that visibly cannot be used;
`enabled` propagates down the item tree, so no editor needs to know about relevance. A `key` rule
resolves through `Settings.valueOf()`, which reaches **both** halves, with
`Settings.valuesRevision` read purely to make the binding live. A `condition` rule names a runtime
fact no setting holds, resolved in `SettingRow.conditionHolds()` — `screensaverPhotos` is
`Photos.count > 0`. The screensaver card is the consumer of both: the switch is unavailable until
the photo folder holds photos, and its three tuning rows need the switch on *and* the photos. The
row that FIXES a condition — *Kuvakansio*'s import button — must not carry the rule, or it becomes
unusable exactly when it is needed),
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
`SettingAction`.

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
general per-type control HINT, not a numeric one — `slider` and `time` are its consumers today.
**`editor: "time"`** keeps `SettingNumber` but reads the int as minutes since midnight (`HH:MM`), makes the ± buttons **wrap** past midnight (min 0, max 1440 − step) and the field
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
(`spotifyAuth` → `SpotifyAuthDetails`, `spotifyDevice` → `SpotifyDeviceDetails`,
`screensaverPhotos` → `ScreensaverPhotosDetails`). It is for facts
that belong to one row without being its value — these actions carry no `help`, and their
details are the whole explanation. *Kuvakansio*'s is a single live line styled as the `help` it
stands in for ("N kuvaa löydetty", from `Photos.count`). The two Spotify ones render through
**`SettingDetails.qml`**: a status line led
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
  An empty screensaver folder is deliberately *not* an issue: the switch is unavailable without
  photos, so a user who wants no screensaver could never clear it. Add a check by pushing one more
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

## USB photo import — `UsbImportPopup.qml`

The *Kuvakansio* row's *Tuo USB:ltä* opens it through `Settings.invokeAction` → `actionRequested` →
`UsbImport.begin()`, the same route the Spotify dialogs take. There are three steps: the drive list,
what the chosen drive's `tesla_homedash_screensaver` folder holds, then the copy. The backend does
all of them (`core/CLAUDE.md`, under `UsbImport`). Load-bearing:
- **Top-anchored and short.** A popup inside a view cannot cover the dock (y 684–780 on the target),
  so the drive list scrolls past four entries rather than growing the card into that band.
- **Buttons pinned to the card's edges.** The import button appears when the scan answers, which is
  asynchronous, and a button joining a centred row would slide the others under a finger already
  reaching for them.
- **Leaving the view closes the dialog, which unmounts the stick — except mid-copy.** The home
  return fires after minutes without a touch, which a long copy easily outlasts; the dialog is
  simply still there on the way back.
