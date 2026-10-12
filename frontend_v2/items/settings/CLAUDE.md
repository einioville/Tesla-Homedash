# `items/settings/` — the Options view (Asetukset)

The QML for `views/SettingsView.qml`: `SettingsSidebar` + `SettingsPane`, the `Setting*` row
delegates, the status widgets and the popups. What they render is `frontend_v2/config/settings.json`
merged with the backend's `CONFIG_SCHEMA` (`backend/src/config_service/CLAUDE.md`). The singletons
behind several of these files are documented in `../../core/CLAUDE.md`:

| QML | Singleton (notes in `core/CLAUDE.md`) |
|---|---|
| `BackendProbeStatus.qml` | `Probe` |
| `BackendLoginPrompt.qml`, `BackendLoginDetails.qml` | `Server` (`ServerClient`'s login) |
| `PairedDisplaysPanel.qml` | `PairedDisplays` |
| `SystemStatusSection.qml`, `SystemGraphCard.qml`, `SystemOverviewCard.qml` | `SystemHistory` (graphs), `System` (service cards) |
| `SystemServiceCard.qml`, `SystemLogPopup.qml` | `System` |
| `DebugLogDetails.qml`, `DebugLogPopup.qml` | `Settings` (the backend's `logging.*`) |
| `LogClearPopup.qml` | `Logs` |
| `SpotifyAuthDetails.qml`, `SpotifyAuthPopup.qml`, `SpotifyAuthAlert.qml` | `SpotifyAuth` |
| `SpotifyDeviceDetails.qml`, `SpotifyDevicePopup.qml` | `SpotifyDevice` |
| `UpdatePanel.qml` (unused while the *Päivitys* card is out of the schema, #56), `UpdateBanner.qml` | `Updater` |
| `ScreenPowerStatus.qml` | `Display` |
| `TeslaFieldTable.qml` (unused while the backend omits its subsection) | `TeslaFields` |
| `UsbImportPopup.qml` | `UsbImport` |
| `ScreensaverPhotosDetails.qml` | `Photos` |
| `SettingsIssues.qml` | reads `Server`, `SpotifyAuth`, `SpotifyDevice`, `Settings` |
| everything else | `Settings` |

## Layout

Master/detail, three levels deep: `views/SettingsView.qml` is a sidebar + pane
split: `items/settings/SettingsSidebar.qml` lists the sections (one per schema group, its row
the icon and title only — a second line naming the subsections would be cut mid-word at the
sidebar's width, and the cards name them anyway) and `SettingsPane.qml` renders the selected section as a stack
of **one card per subsection** (issue #30) — the same card the sidebar itself carries. The pane
is transparent; the cards are the containers, so nothing is nested inside a further border.
Sections are general (Yleinen, Media, Datan visualisointi, Sähkö, Tesla, Ylläpito) and the
subsections carry the detail — except *Järjestelmän tila*, which is a status screen rather than
options and renders its own `view` (below).

Load-bearing:

- **Rows survive a write.** Every write replaces `Settings.groups` (at once for a local key, on
  the schema broadcast for a backend one), and a Repeater handed a new array recreates every
  delegate — and a recreated row cannot animate past a write: a switch would reappear already
  moved and nested rows pop in. So `SettingsPane` builds the cards from **`layout`**, replaced
  only when the section's **shape** changes (`shapeOf()`: the sections with each entry's `value`,
  the local `modified` flag and `runtime` dropped, as JSON), and each row reads its current entry
  by key from **`liveEntries`**. A value write leaves the shape alone, so the delegates stay and
  their bindings carry the value in; a section switch, a schema with other entries, a changed
  option list or apply tier rebuilds the cards. Every editor re-syncs on `onSettingChanged`, which
  is what lets a row take a new value in place. Measured offscreen: the toggled row is the same
  object afterwards.
- **Selection is a group ID, and it is sticky.** The section list grows from 5 entries to 7
  when the backend's schema arrives and shrinks again if the connection drops, so an index
  would silently select a different section. `currentSectionId` holds what the user *chose*
  and is never overwritten by a list change; `currentGroup` resolves it on read, falling back
  to the first section. That is what makes a backend section still be selected after a
  reconnect instead of the user being bounced to the first one.
- **Rows carry the card's only vertical padding.** A row centres its label block and its editor in
  at least 56px with at least 12px above and below; the card body adds nothing around the rows. A
  card margin on top of that would make the first and last rows lopsided — more space toward the
  card edge than toward the divider. Only the intro (the card's `help` line and `status` widget), which
  has no padding of its own, is padded, and at the bottom too only when no row follows it.
- **Subsection order across the two halves is the local group's `sectionOrder`.** Local
  subsections are folded in before the backend's, so without it a backend card can never lead its
  section. `Settings` applies the list after the merge: named ids first, in that order, everything
  unnamed after them in its natural order (so a subsection added later still appears). Media uses
  it to put the backend's *Ääni* card above the local *Spotify* card and the backend's *Radio*.
- **A group may name a `view`**, a screen `SettingsPane` renders in place of the card stack, built
  by a `Loader` only while that section is selected (so whatever it polls stops when the user moves
  on) and resolved in the pane's view table. `Settings::rebuildGroups` keeps such a group although it
  has no subsections — any other empty group is a placeholder waiting for its backend half. The one
  consumer is `systemStatus`, *Järjestelmän tila* (below).
- **Group `icon` is a SEMANTIC name** (`"charger"`, `"media"`, `"price"`, …), mapped to a
  resource by `SettingsSidebar.iconFor()`. The backend names icons without knowing anything
  about frontend assets; an unknown name falls back to the gear. Both schema builders copy
  *every* group-level key rather than an allow-list, so the next group field needs no code
  change (an allow-list would silently drop it).

## Schema keys the delegates understand

Beyond the basics (`key`, `type`, `label`, `help`, `unit`, `min`/`max`/`step`, `nullable`,
`options`): **`hidden`** (kept out of the rendered rows while stored and persisted normally — for a
setting whose editor lives in the subsection's status widget, or that only a flow writes; filtered
in `Settings::decorateSections`. A subsection whose entries are ALL hidden and that names no
`status` is dropped, which is how the backend's `spotify` subsection — `spotifyDeviceId` /
`spotifyDeviceName`, written only by the device scan — renders nothing while staying the write
allow-list), **`details`** (a row-level live block under the label — see *Row details* below),
**`relevantWhen`** (`{key, equals|notEquals}` or `{condition}`, or a list of such rules that must
ALL hold — it nests, hides or fades the row, see *Dependent rows* below), **`secret`** (a
`string` shown masked by `SettingText` except while it is being edited, and logged as `<hidden>` by
`Settings::setValue`; the saved file still holds it in clear, like `.env`. No setting carries it —
the MML map key is `.env`-only — but it stays as the guard the next secret needs), **`onSelect`** (`{value: action}` on an `enum`: choosing that value runs the action
INSTEAD of writing it — a dialog that asks something first and writes the value itself. The field
shows the current value again until that write returns, so a cancelled dialog leaves nothing to undo,
and it runs even when the value is already chosen. DEBUG in *Lokitaso* is its consumer),
**`confirm: false`** (an action that runs on the first tap, because the dialog it opens is the
confirmation — *Tyhjennä lokit*), **`runtime`** (facts the backend merges into an entry that change
with its value without being a setting — DEBUG's end time and the level it returns to; `shapeOf()`
drops it with `value`, or a write that sets it would rebuild the card) and **`warnBelow`
/ `warnAbove` + `warnMessage`** (issue
#34: `SettingRow` shows an inline caution while the value crosses the threshold; advisory only,
`min`/`max` remain the hard bounds — the myenergi poll interval is its consumer).

## Dependent rows (`relevantWhen`)

`SettingRules.qml` is the one evaluator of the rules; `SettingsPane` and `SettingRow` each act on a
different part of them.

- **Nested and hidden.** A row whose first `key` rule names a setting **earlier in the same card,
  with nothing between them but that setting's own nested rows**, is nested under it (`card.links`
  in `SettingsPane`): indented `Theme.settingChildIndent` per level beside a thin rail
  (`Theme.settingChildRail`), no divider between the parent and its first nested row, dividers
  between nested rows only from the indent, and a full-width one closing the block. It is **hidden
  while that rule fails or its parent is hidden** — a dimmed row for a feature that is off only
  asked what it belonged to. All of today's dependent rows nest this way: a switch's tuning rows,
  the warp rows under `mapFollowMode`, and the tariff rows under *Sähkösopimus* (`spotPrice.enabled`
  — *Hinta* under *Kiinteä*, *Marginaali* and *Arvonlisävero* under *Pörssi*). The looser
  placements (a later setting, another card, a row in between) are deliberately not nested, since
  the indent would claim the wrong parent.
- **Faded and disabled.** Every other failing rule — a `condition`, or a `key` rule that does not
  nest — makes `SettingRow` fade the row **and set `enabled: false` on it**, since a control that
  changes a value with no effect is worse than one that visibly cannot be used; `enabled`
  propagates down the item tree, so no editor needs to know about relevance. A row on screen has
  its nesting rule holding, so only these can fail there.
- A `key` rule resolves through `Settings.valueOf()`, which reaches **both** halves, with
  `Settings.valuesRevision` read purely to make the binding live. A `condition` rule names a
  runtime fact no setting holds, resolved in `SettingRules.conditionHolds()` — `screensaverPhotos`
  is `Photos.count > 0`, `equalizer` that the bass row's `runtime.state` is not `unavailable`,
  `backendLogin` that the backend has asked for the password (`Server.authState` `loginRequired` or
  `noPassword`) — the *Kirjaudu* row is usable only then. The screensaver card uses both: the switch is faded until the photo folder
  holds photos (hiding it would hide the feature, and the fix is right below), and its three tuning
  rows are nested under the switch *and* fade without photos.
- The row that FIXES a condition — *Kuvakansio*'s import button — must not carry the rule, or it
  becomes unusable exactly when it is needed. Likewise **an issue's fix row must never be a nested
  row**: the spotlight could be sent to a row that is hidden.
- **Appearing and going are animated** (`../util/Reveal.qml`; each entry is a `Reveal`). An entry
  that appears slides out from under the row above it, set back, then comes forward to level; the
  card ranks the entries that appeared in one change and staggers them top first
  (`Theme.revealStagger`), so a switch that reveals three rows drops them like dominoes. Entries
  that go fold back up, bottom first, at half the stagger. `card.animateShown()` does the ranking
  by diffing `shownEntries` against `lastShown`; an entry built with its card is `snap()`ped into
  place, so opening a section animates nothing. This only works because rows survive a write
  (*Layout*, above).

## Delegates

`SettingRow` dispatches on `setting.type` to
`SettingSwitch` / `SettingNumber` / `SettingSlider` / `SettingText` / `SettingSelect` (the
last subclasses `TripComboBox`, inheriting the dark styling and the #9/#19 dropdown fixes) /
`SettingAction`. `SettingSwitch` is only the shared `../util/ToggleSwitch.qml` bound to a setting,
and the pane scrolls in `../util/ElasticFlickable.qml` (soft ends, spring back on release) — the
motion and the reusable pieces are documented in `../util/CLAUDE.md`.

**Numeric settings default to `SettingNumber` — a `[−] [typed value] [+]` stepper — and sliders are
OPT-IN** via the schema's `editor: "slider"`. A slider only works when the exact number does not
matter; most settings here are the opposite — as a slider, `backendPort` (1–65535) would be ~205
ports per pixel of a 320px track. Only genuine coarse dials carry the hint — `screensaverStackCount`,
the map's `mapDefaultZoom` and the backend's `audio.volumePercent` (check `config/settings.json`
and `SETTINGS_SCHEMA` for the current set). **Rule of thumb: if the user knows the number they want, it is not a slider.** The slider is **one
line** — track, then the readout at its right, sized by `TextMetrics` for the widest text it can
show so the track keeps its length mid-drag — because an editor must centre on the label like the
others: a readout stacked above the track would push the track ~8px below the label's centre line.
`SettingNumber`'s ± buttons hold-to-repeat (`../util/HoldRepeatArea.qml`), and it accepts typing
for big jumps. **A hold steps a pending value that only the field shows and commits it once, on
release** — each write is a disk write (a backend one a `config.json` save, apply hooks and a schema
broadcast), so writing per step would make one hold dozens of them. **A mouse wheel steps it the same way**
(`../util/WheelStepArea.qml`): one step per notch into the pending value, one commit once the wheel
has been still for 400 ms. `SettingSlider` takes the wheel too, along its step grid. The plain
`field` editor has no steps, so it takes no wheel and the wheel scrolls the pane. `editor` is the
general per-type control HINT, not a numeric one — `slider`, `time`, `field` and `select` are its consumers today.
**`editor: "field"`** drops `SettingNumber`'s ± buttons and leaves the typed field, left-aligned like
`SettingText` — for a number that is an identifier rather than a quantity, which nobody nudges a
step at a time. `backendPort` is its consumer: it sits under the address field and is typed the
same way.
**`editor: "select"`** renders a `bool` as `SettingSelect` over its two `options` (`false` / `true`)
instead of a switch — for a choice between two named things rather than a feature on or off. The
value stays a bool, so the backend validates and every consumer reads it unchanged. *Sähkösopimus*
(`spotPrice.enabled`: *Kiinteä* / *Pörssi*) is its consumer.
**`editor: "time"`** keeps `SettingNumber` but reads the int as minutes since midnight (`HH:MM`), makes the ± buttons **wrap** past midnight (min 0, max 1440 − step) and the field
read-only: the number pad has no colon, and with wrapping, eight 15-minute steps back from 00:00
reach 22:00. The night-mode window (`nightStartMin` / `nightEndMin`) is its consumer.

**A dial whose real numbers are deliberately not shown is an `enum` of named levels**, rendered as
a dropdown, with `Theme` mapping each level to its number — the whole *Kuvaajat* card:
`graphResolution` (*Matala* … *Maksimi* → a bucket density), `graphGestureSensitivity` (*Matala* …
*Maksimi* → a gesture multiplier on both the pinch's zoom and its pan), `graphSettleDelay` (*Hidas* … *Välitön* → a settle time)
and `graphRenderMargin` (*Pieni* … *Erittäin suuri* → a margin fraction) — plus the *Kartta* card's
`mapGestureSensitivity`, which shares the graph's sensitivity table (`Theme.gestureSensitivityLevels`),
and its warp-mode `mapWarpDeadzone` / `mapWarpLead` (→ fractions of the map's shorter side).

**`type: "action"` is a button, not a value.** `SettingAction.qml` renders it and calls
`Settings::invokeAction(key)`; nothing is stored, persisted or sent as `CONFIG_SET`. Keeping
actions in the schema is what lets the *Ylläpito* section — **restart the dashboard**,
**restart the backend**, **reboot the host** (`HOST_REBOOT`, #40) — be ordinary sidebar rows
instead of a widget bolted onto the view.
Entries carry `actionLabel` and optionally `requiresConnection` (which greys an action the
backend runs — the backend restart, the reboot, the Spotify and USB-import flows — while
disconnected). An action needs a **second tap to confirm** (armed for 4 s, then it lapses) unless
it carries `confirm: false` — a modal would need a Cancel button and a way to dismiss it, which a
fullscreen keyboard-less panel does not have.

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
`screensaverPhotos` → `ScreensaverPhotosDetails`, `backendLogin` → `BackendLoginDetails`, `debugLog` → `DebugLogDetails`, which is handed
the row's setting: "Palautuu tasolle INFO klo 14:52 (vielä 30 min)" from `runtime.until` and
`runtime.returnTo`, in the warning text colour while the log is on). It is for facts
that belong to one row without being its value — these actions carry no `help`, and their
details are the whole explanation. *Kuvakansio*'s is a single live line styled as the `help` it
stands in for ("N kuvaa löydetty", from `Photos.count`). The two Spotify ones render through
**`SettingDetails.qml`**: a status line led
by a green / amber / red / grey dot, then label–value pairs. Grey means *could not be established*,
which is kept apart from red on purpose.

- **`SpotifyAuthDetails`** — account (e-mail, else display name), *Tunnistettu*, *Voimassa asti*.
  Red only when the backend says the grant does not work; amber within 30 days of `validUntil`, past
  it while Spotify still accepts the grant (the 180-day estimate is deliberately early), and when
  the dates are unknown — a grant with no grant record. Re-evaluates
  hourly, so amber arrives on a panel left on this view.
- **`SpotifyDeviceDetails`** — name (type) and id of the configured device. Amber when Spotify does
  not list it: Spotify lists only devices that are up, so *switched off* and *wrong id* look the
  same, and the text says both. It asks for `SpotifyDevice.configuredStatus` on construction; the
  row is rebuilt every time its section is shown, so the request is throttled in C++
  (`core/CLAUDE.md`).

## Write results

**A write's result is shown beside the title of the row that made it** — "Tallennettu" in
green for 2.5 s, a rejection in red for 6 s — not in a banner elsewhere on the screen. The state
lives in `SettingsView.rowFeedback`, passed down through `SettingsPane`, **not in the row**: a
write that changes the section's shape still rebuilds the cards (*Layout*), and the row that made
it may not outlive it. A **failure** with no row to sit beside — a keyless `CONFIG_SET_RESULT` (a
refused restart or reboot), a lost connection, a hidden setting — goes to the app's notification pill
(`Notifications.post("settings", …)`) instead; a row-less **success** is dropped, since a hidden
setting is written beside a visible one (the DEBUG duration beside the level) whose row reports it. A restart-tier write gets no extra
wording: the row's badge and the restart banner already say it.

**The restart badge names the half that restarts**: *sovelluksen uudelleenkäynnistys* on a local
restart-tier row (read once by `AppConfig` — today the backend address and port), *palvelimen
uudelleenkäynnistys* on a backend one (read once by a backend service — `timeZone`,
`spotPrice.enabled`, a hook setting whose service is absent). `SettingRow` picks it from the
entry's `origin`. They are two separate restarts with separate banner buttons, so a bare
*uudelleenkäynnistys* left the user guessing which one to press.

## Issues and the fix spotlight

The header shows **"Ongelmia havaittu" + *Tarkista*** only while `SettingsIssues` reports
something (red dot if any issue is an error, amber for warnings only). A lost backend is itself an
issue, which is what keeps a screen showing only the local sections from reading as a bug.

- **`SettingsIssues.qml`** is a plain binding over the singletons, so an issue appears and clears by
  itself. Each names the **setting key that fixes it**; its section is looked up in
  `Settings.groups` rather than hardcoded, and an issue whose row is not in the schema right now
  offers no *Korjaa*. **While disconnected, only the connection is reported** — every other check
  reads backend state that is stale until it returns — and a backend that wants the password counts
  as not there, reported as that (no password on the backend, or this display not logged in →
  `backendLogin`) rather than as unreachable. Today's checks: backend unreachable →
  `backendHost`; Spotify grant broken, or valid for ≤ 30 more days → `spotifyReauth`; no Spotify
  device chosen, or chosen but not listed → `spotifyIdentifyDevice` (only with a working grant).
  An empty screensaver folder is deliberately *not* an issue: the switch is unavailable without
  photos, so a user who wants no screensaver could never clear it. Add a check by pushing one more
  entry.
  The view refreshes `SpotifyDevice.configuredStatus` whenever it becomes current, since the device
  checks read it.
- **`SettingsIssuesPopup.qml`** is the list, a `ModalDialog` anchored under the header. A tap beside
  the card closes it.
- **`SettingSpotlight.qml`** is where *Korjaa* ends: the view selects the fix's section and the view
  blurs its content (the same layer the dialogs use), while this draws a **crisp copy** of the row —
  a `ShaderEffectSource` over an opaque plate recreating the card behind it, ringed in the accent —
  until the next tap. The row cannot leave the blurred layer, so a copy is the only way to show it
  sharp. **A press on the copy dismisses and is not accepted**, so it reaches the real row beneath
  (tapping the highlighted *Kirjaudu* works first time); a press anywhere else is swallowed, so a
  blind tap on the blur cannot flip a switch nobody could see. The row is found by key on every
  80 ms tick (rows name themselves `settingRow:<key>`, `SettingsPane.rowItem()`), because a shape
  change rebuilds every row and a status widget settling or a row revealing can move one; the first
  ticks also scroll it to
  the middle of the pane, since the section may only just have been built. The copy is not drawn
  before the first tick: a just-selected section has not been laid out yet.

## Status widgets

The hook is a **subsection-level `status` key**: a subsection may name a runtime status widget,
which `SettingsPane` renders in the card via a `Loader` above the rows, resolving the name against a
small component table (`backendProbe`, `appUpdate`, `screenPower`, `teslaProperties`, `equalizer`,
`pairedDisplays`;
`appUpdate` and `teslaProperties` are unused while their subsections are out of the schema). `active:` gates construction,
which is what keeps the probe from firing for a card that did not ask
for it. A subsection carrying a `status` but **no settings** is legitimate and is exempted from the
empty-section filter: the Tesla field table's card is entirely its widget. It exists because not
every fact about a section fits in a setting row: *is that address reachable* belongs to the host
and port **together**. The verdict follows the SAVED values (what startup will actually use),
debounced 400 ms so editing host then port probes once against the final pair. Advisory only — the
write is never blocked, since the backend legitimately may not be up yet.

## The backend login — `BackendLoginPrompt.qml`, Yhteydet's *Kirjautuminen*, Näytöt

The connection and its login are `ServerClient`'s (`../../core/CLAUDE.md`); these are its faces.
- **`BackendLoginPrompt`** is app-level in `Main.qml` (z:265), like the Spotify prompt: no view gets
  data until the display has logged in. A `ModalDialog` hung in the top half — the on-screen keyboard
  takes the bottom — with a password field, *Kirjaudu*, the reason the last attempt failed, and
  *Kirjaudutaan…* while the key is derived (seconds on a Pi). With no password on the backend it says
  so instead of asking. Its ✕ dismisses it, leaving the dock and this view usable (the backend
  address may be what is wrong); nothing typed survives a closed prompt.
- **Yhteydet › *Kirjautuminen*** is a `backendLogin` action row (`confirm: false`: the prompt is the
  confirmation) whose `backendLogin` details say whether this display is logged in, and why not. It
  brings the prompt back (`Server.showLoginPrompt()`, routed by `SettingsView`), and is the issues
  list's fix row for a missing login.
- **Ylläpito › Näytöt** is a backend subsection: the `pairedDisplays` widget lists every display that
  has logged in — connected or when last seen, address, when it logged in, *tämä näyttö* — with a
  *Poista* that arms and then confirms within 4 s (`SettingAction`'s guard); then *Palvelimen
  saavutettavuus* (`server.reachability`: *Lähiverkko* / *Vain päälaite*, restart-tier) and the
  `auth.tokenLifetimeDays` dropdown (*Ei koskaan* / 7 / 30 / 90 / 365 days, counted from last use).
  The local `sectionOrder` puts it straight after Yhteydet.

## Ylläpito › Lokit — `DebugLogPopup.qml`, `LogClearPopup.qml`

The backend's *Lokit* card: the **Lokitaso** dropdown and **Tyhjennä lokit**, with no help lines —
their names say it. Both act on the app's own log files; the journal follows the level but never
below INFO and is never cleared (`backend/src/system_service/CLAUDE.md`).
- Choosing DEBUG (`onSelect`) opens `DebugLogPopup`: a row of durations (15 min – 8 h, then
  **Toistaiseksi** — minutes 0, no end, for development, with a reminder that it survives restarts),
  starting from the one used last; *Ota käyttöön* writes `logging.debugMinutes` and `logging.level`. Cancelling writes nothing. The row's `debugLog` details then say when and to which
  level it returns, or *Päällä toistaiseksi*; the details collapse to no height otherwise, or the label would sit high.
- *Tyhjennä lokit* (`confirm: false`) opens `LogClearPopup`: *Tyhjennä kaikki* or *Säilytä varoitukset
  ja virheet* (the primary). The dialog closes on the choice; `Logs.finished` puts the outcome beside
  the row ("Tyhjennetty · 12.3 kB vapautettu"), through the view's ordinary row feedback.

## Järjestelmän tila — `SystemStatusSection.qml`

A vertical `ElasticFlickable`: **`SystemOverviewCard`** on top, then the backend host's last ten
minutes as a 2×2 grid of `SystemGraphCard`s (CPU per core, memory, disk, network) and a full-width CPU
temperature card, then **a `SystemServiceCard` per backend service**. Graphs from `SystemHistory`,
cards from `System` (`../../core/CLAUDE.md`), both retained only while the section is visible.

- **The overview** answers *is the system healthy* in one line (*Järjestelmä kunnossa* / *Ongelmia
  havaittu* / *Vikoja havaittu*, with a dot), lists the issues behind it, errors first, and gives
  the host's and the backend's uptime (`uptime_s`, `backend_uptime_s` in the status document). An
  issue is a service card in `error` or `warn` — never `off`, which is deliberate (no Zappi, a flat
  tariff) — or a host threshold judged here on the latest graph sample: disk ≥ 90 % used (error
  ≥ 95), memory ≥ 90 % (error ≥ 97), CPU ≥ 80 °C (error ≥ 85, where the Pi's firmware throttles
  hard). While disconnected it says only that: the last reply's services and uptimes are stale.

- **Service cards** render each row of the backend's `services` generically: the verdict as a dot
  plus *Toiminnassa* / *Ongelmia* / *Ei toiminnassa* / *Ei käytössä*, the detail line, the settings
  in effect as label–value pairs (typed values formatted here: `{time}` today as a clock time, another
  day with its date; both columns **wrap rather than elide** — a path cut in the middle hid the part
  being looked for, and with no spaces in it, it breaks at a slash or anywhere), the server card's
  connected displays with this one marked, and the warning and
  error counts with *Näytä* opening `SystemLogPopup` (newest first, date and time, level tag,
  logger, the message's first lines). Cards pair two to a row, each row as tall as its taller card;
  the Repeater's model is a **count**, since a poll replaces the list every 5 s and a new array
  would rebuild every card.
- **Temperature**'s headline gives the window's peak. A host with no sensor (`temp_available: false`,
  WSL2) shows *Tällä laitteella ei ole lämpötila-anturia* in place of the graph.
- **Every dialog is a `ModalDialog`** — the opaque card over a scrim that takes every press and
  wheel turn beside it (a MouseArea with no wheel handler lets the wheel through to the page behind;
  a list inside the card still scrolls, since it sits above the scrim). A new dialog is built on
  `ModalDialog`, not on another scrim and card.

- **Disk is graphed as I/O** (read / write rates) with the free space as the card's headline: space
  changes too slowly over ten minutes to be a line, and disk-full is still the failure worth seeing.
- **Colours are the dark categorical palette in its fixed order**, validated against the card
  surface (`#212121`, `Theme.tripCardBg` over `tripBackground`) for lightness, chroma, colour-blind
  separation of neighbours and contrast; `Theme.accent` is too light for that band and stays for the
  single memory line. A core keeps its colour by number. **Past eight cores the hues repeat dashed**
  (cores 9–16), rather than inventing a ninth colour, and the legend draws the dash too.
- **A legend only for two or more lines**, each entry naming its line and giving its value — a single
  line is named by the title. Values are fixed-width (`widestValue`) so the entries never shuffle.
- **Rates are drawn in one unit per window** — the largest that keeps the peak under 1000 of it — and
  the unit goes in the title ("Levy (kB/s)"), since the shared graph labels its axis with plain
  numbers, as every graph in the app does. Percentages and temperature use a fixed 0–100 range.

**The graphs are the app's own `HistoryGraph`** (`../history/HistoryGraph.qml`), so they look and
behave like History, Trips and Charging: the axes and clock-time ticks, the white inspect line with
its glass readout (hover with a mouse, one finger on touch), the pulsing live marker on a single
line, the draw-in, and pinch / left-drag zoom with *Palauta*. `SystemGraphCard` wraps it the way
`ChargingGraphCard` does — the translucent card, the title overlaid at the top left — and feeds it
like the Charging view's live graphs: the first data `reloadFull()`s, later updates
`advanceLive()` (keeping a zoom the user made). What `HistoryGraph` offers for this, all inert at
their defaults so no other graph is affected:
- **`extraSeries`** — further lines over the same axes (`{points, color, label, dashed}`), as extra
  `LineSeries` added to the GraphsView at runtime (an `Instantiator`; the view's own children can
  only be series). They join the y-fit, draw in with the main line, get a dot each when inspecting,
  and a multi-line readout lists every line with its colour. Dashes use the scoped
  `LineSeries.StrokeStyle.DashLine` — the unscoped form the docs show is undefined at runtime.
- **`lineColor`** / **`seriesLabel`** for the main line, **`fixedMinY` / `fixedMaxY`** in place of the
  fit, **`formatValue`** for the readout, and **`wheelZoom`** — off here, since the section scrolls
  and the wheel belongs to the page (a left-drag still pans, a pinch still zooms).

A multi-line graph turns the glow and the live marker off: a glow or a pulse on one line of several
would single it out.

## Media › Taajuuskorjain — `EqualizerPanel.qml`

The backend's *Taajuuskorjain* card (`backend/src/audio_service/CLAUDE.md`): this `status:
"equalizer"` widget draws the five bands as knobs on a curve, and the bass shelf is the ordinary
slider row under it. Load-bearing:
- **The band rows are hidden, and `Settings::decorateSections` strips hidden entries before any
  widget sees them** — so the widget takes the band list (key, label, range) from the subsection's
  own `bands`, which the backend repeats at subsection level for exactly this reason, and the values
  from `Settings.valueOf` (with `valuesRevision` read to make the binding live). The equalizer's
  `runtime.state` rides on the bass row, the card's one visible entry; *unavailable* fades the plot
  and, through the `equalizer` condition, the bass row too.
- **Only a press on a knob grabs** (within 36 px of its centre), with `preventStealing` so the
  settings Flickable cannot turn the drag into a scroll. Anywhere else the press is refused and goes
  to the page, so the plot is never a dead zone the page cannot be scrolled from.
- **The commit rules of the other editors**: a drag or a wheel spin (one dB per notch, per column)
  moves only the knob and writes once, on release or when the wheel settles. Until the schema
  confirms a write the knob holds the written value (`pending`), cleared on the confirming schema, on
  `writeFailed` (the knob goes back) and on an `unchanged` result (no schema follows one). **The
  pending value is set before the band is let go**: the other order re-evaluated the knob against the
  old saved value with its animation re-enabled in the same instant, so on release it slid back toward
  0 and returned (measured: +2.7 dB 0 ms after letting go of +7, back at +7 after ~200 ms).
- **The curve is a monotone cubic (Fritsch–Carlson)** through the knobs: a plain spline overshot
  between two knobs at opposite ends and drew past ±12. It runs through the knobs' **animated**
  values, so *Nollaa* morphs it back to flat, and from an extra point at each edge — the right one
  level with the top band, the left one the bottom band plus the bass shelf, which is how the bass
  slider shows on the curve. The look is the graphs': `HistoryGraph`'s fill stops under a 2 px accent
  line, the settings slider's handle and track stood on end.
- **The status row keeps its height** whether or not *Nollaa* shows, so the first band moved off
  flat does not push the bass row down under the finger. *Nollaa* writes each non-zero value once
  and is not armed — like the graphs' *Palauta*, it only puts a view back.

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
