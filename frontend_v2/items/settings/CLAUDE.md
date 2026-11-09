# `items/settings/` — the Options view (Asetukset)

The QML for `views/SettingsView.qml`: `SettingsSidebar` + `SettingsPane`, the `Setting*` row
delegates, the status widgets and the popups. What they render is `frontend_v2/config/settings.json`
merged with the backend's `CONFIG_SCHEMA` (`backend/src/config_service/CLAUDE.md`). The singleton a
file reads is documented under its name in `../../core/CLAUDE.md`.

## Layout

`SettingsSidebar` lists the sections, each row only an icon and title (a second line naming the
subsections would be cut mid-word at its width, and the cards name them anyway); `SettingsPane`
renders the selected section as **one card per subsection** (#30). The pane is transparent — the
cards are the containers, so nothing nests inside a further border. *Järjestelmän tila* is a status
screen rather than options and renders its own `view` (below).

- **Rows survive a write.** Every write replaces `Settings.groups` (at once for a local key, on the
  schema broadcast for a backend one), and a Repeater handed a new array recreates every delegate —
  a switch would reappear already moved and nested rows pop in. So `SettingsPane` builds the cards
  from **`layout`**, replaced only when the section's **shape** changes (`shapeOf()`: the sections as
  JSON without each entry's `value`, the local `modified` flag and `runtime`), and each row reads its
  current entry by key from **`liveEntries`**. A value write leaves the shape, so the delegates stay
  and their bindings carry the value in; a section switch, other entries, a changed option list or
  apply tier rebuilds the cards. Every editor re-syncs on `onSettingChanged`. Measured offscreen:
  the toggled row is the same object afterwards.
- **Selection is a group id, and it is sticky.** The section list grows when the backend's schema
  arrives and shrinks if the connection drops, so an index would select a different section.
  `currentSectionId` holds what the user *chose* and no list change overwrites it; `currentGroup`
  resolves it on read, falling back to the first section — so a backend section is still selected
  after a reconnect.
- **Rows carry the card's only vertical padding**: a row centres its label and editor in at least
  56 px with at least 12 px above and below, and the card body adds nothing — a card margin as well
  would make the first and last rows lopsided against the dividers. Only the intro (the card's `help`
  and `status` widget) is padded, at the bottom only when no row follows it.
- **Subsection order across the halves is the local group's `sectionOrder`**: local subsections fold
  in before the backend's, so without it a backend card could never lead its section. Named ids come
  first in that order, everything else after in its natural order, so a subsection added later still
  appears.
- **A group may name a `view`**, a screen `SettingsPane` renders instead of the card stack, built by
  a `Loader` only while that section is selected (so whatever it polls stops when the user moves on).
  `Settings::rebuildGroups` keeps such a group although it has no subsections; any other empty group
  is a placeholder waiting for its backend half.
- **Group `icon` is a semantic name** (`"charger"`, `"media"`, `"price"`, …) mapped to a resource by
  `SettingsSidebar.iconFor()`, so the backend names icons knowing nothing of frontend assets; an
  unknown name falls back to the gear. Both schema builders copy *every* group-level key, not an
  allow-list, so the next group field needs no code change.

## Schema keys the delegates understand

Beyond the basics (`key`, `type`, `label`, `help`, `unit`, `min`/`max`/`step`, `nullable`, `options`):
- **`hidden`** — kept out of the rendered rows (filtered in `Settings::decorateSections`) while
  stored and persisted normally: for a setting whose editor is the subsection's status widget, or
  that only a flow writes. A subsection whose entries are all hidden and that names no `status` is
  dropped — how the backend's `spotify` subsection (`spotifyDeviceId` / `spotifyDeviceName`, written
  only by the device scan) renders nothing while staying the write allow-list.
- **`details`** — a live block under the row's label (*Row details*).
- **`relevantWhen`** — `{key, equals|notEquals}`, `{condition}`, or a list that must all hold; it
  nests, hides or fades the row (*Dependent rows*).
- **`secret`** — a `string` shown masked by `SettingText` except while edited, and logged as
  `<hidden>` by `Settings::setValue`; the file still holds it in clear, like `.env`. No setting
  carries it (the MML key is `.env`-only); it stays as the guard for the next secret.
- **`onSelect`** — `{value: action}` on an `enum`: choosing that value runs the action INSTEAD of
  writing it, for a dialog that asks first and writes the value itself. The field shows the current
  value until that write returns, so a cancelled dialog leaves nothing to undo, and it runs even when
  the value is already chosen (DEBUG in *Lokitaso*).
- **`confirm: false`** — an action that runs on the first tap, because the dialog it opens is the
  confirmation.
- **`runtime`** — facts the backend merges into an entry that change with its value without being a
  setting (DEBUG's end time and the level it returns to); `shapeOf()` drops it with `value`, or a
  write that sets it would rebuild the card.
- **`warnBelow` / `warnAbove` + `warnMessage`** (#34) — an inline caution while the value crosses the
  threshold; advisory, `min`/`max` stay the hard bounds.
- **`editor`** — the per-type control hint (*Delegates*).

## Dependent rows (`relevantWhen`)

`SettingRules.qml` is the one evaluator; `SettingsPane` and `SettingRow` act on different parts.

- **Nested and hidden.** A row whose first `key` rule names a setting **earlier in the same card,
  with nothing between but that setting's own nested rows**, is nested under it (`card.links`):
  indented `Theme.settingChildIndent` per level beside a rail (`Theme.settingChildRail`), no divider
  under the parent, dividers between nested rows only from the indent, and a full-width one closing
  the block. It is **hidden while that rule fails or its parent is hidden** — a dimmed row for a
  feature that is off only asked what it belonged to. Looser placements (a later setting, another
  card, a row between) are deliberately not nested, since the indent would claim the wrong parent.
- **Faded and disabled.** Every other failing rule — a `condition`, or a `key` rule that does not
  nest — fades the row **and sets `enabled: false`**, since a control that changes a value with no
  effect is worse than one that visibly cannot be used; `enabled` propagates, so no editor knows
  about relevance.
- A `key` rule resolves through `Settings.valueOf()`, which reaches both halves (`valuesRevision`
  read to make the binding live). A `condition` names a runtime fact no setting holds, resolved in
  `SettingRules.conditionHolds()`. The screensaver card uses both: the switch fades until the photo
  folder holds photos (hiding it would hide the feature, and the fix is right below), and its tuning
  rows nest under it *and* fade without photos.
- **The row that FIXES a condition must not carry the rule** (*Kuvakansio*'s import button), or it is
  unusable exactly when it is needed. Likewise **an issue's fix row must never be nested**: the
  spotlight could be sent to a hidden row.
- **Appearing and going are animated** (`../util/Reveal.qml`, an entry each): rows that appear in one
  change drop in top first, staggered by `Theme.revealStagger`, and rows that go fold up bottom first
  at half the stagger. `card.animateShown()` ranks them by diffing `shownEntries` against
  `lastShown`; an entry built with its card is `snap()`ped, so opening a section animates nothing.
  This works only because rows survive a write.

## Delegates

`SettingRow` dispatches on `setting.type`; `SettingSelect` subclasses `TripComboBox` for its styling
and the #9/#19 dropdown fixes, `SettingSwitch` is `../util/ToggleSwitch.qml`, and the pane scrolls in
`../util/ElasticFlickable.qml` (`../util/CLAUDE.md`).

**Numbers default to `SettingNumber`, a `[−] [value] [+]` stepper; a slider is opt-in**
(`editor: "slider"`), only for a coarse dial where the exact number does not matter — as a slider,
`backendPort` would be ~205 ports per pixel. **If the user knows the number they want, it is not a
slider.** The slider is **one line**, its readout at the track's right and sized by `TextMetrics` for
its widest text so the track keeps its length mid-drag — a readout above the track would push it
~8 px off the label's centre line.

**A hold or a wheel steps a pending value only the field shows, and commits once** — on release, or
once the wheel has been still for 400 ms (`../util/HoldRepeatArea.qml`, `../util/WheelStepArea.qml`):
each write is a disk write (a backend one a `config.json` save, apply hooks and a schema broadcast).
`SettingSlider` takes the wheel along its step grid; the plain `field` editor has no steps, so the
wheel scrolls the pane.

The other `editor` hints:
- **`field`** — the typed field alone, left-aligned like `SettingText`, for a number that is an
  identifier rather than a quantity (`backendPort`).
- **`select`** — a `bool` as `SettingSelect` over its two `options`, for a choice between two named
  things rather than a feature on or off; the value stays a bool (*Sähkösopimus*: *Kiinteä* /
  *Pörssi*).
- **`time`** — the int as minutes since midnight (`HH:MM`), ± buttons that **wrap** past midnight
  (min 0, max 1440 − step) and a read-only field: the number pad has no colon.

**A dial whose real numbers are deliberately not shown is an `enum` of named levels** in a dropdown,
`Theme` mapping each level to its number — the *Kuvaajat* card, and the map's gesture sensitivity
(sharing the graphs' table, `Theme.gestureSensitivityLevels`) and warp dials.

**`type: "location"`** (the backend's `home`, *Yleinen › Sijainti › Koti*: `{address, lat, lon,
timeZone}`) is edited in `HomeLocationPopup.qml`, opened by the row's `SettingAction` button
(`confirm: false`) through `SettingsView`. `HomeLocationDetails.qml` shows the address, coordinates
and zone, with a warning line when the zone is not the running backend's (`runtime.zoneInEffect`;
`backend/src/config_service/CLAUDE.md`, *Location and timezone*). The dialog searches through
`Geocoder` on *Hae* or Enter, **never per keystroke** (Nominatim's rule), or takes a tap on its map;
*Tallenna* writes `{address, lat, lon}` and the backend adds the zone. It hangs from the top so the
field and the hits stay above the keyboard, and Enter closes the keyboard so the map shows. Its map
is a plain `Map` on the app's imagery (`BasemapPlugin`) with handlers of its own — it shares nothing
else with the car's map. The pin is `location.svg`'s two paths as one even-odd `Shape` path, red with
a black outline and the inner circle hollow, since a tinted icon has one colour.

**`type: "action"` is a button, not a value**: `SettingAction.qml` calls `Settings::invokeAction(key)`
and nothing is stored or sent as `CONFIG_SET`, which is what makes the restarts and the host reboot
(`HOST_REBOOT`, #40) ordinary rows. `requiresConnection` greys an action the backend runs while
disconnected. An action needs a **second tap within 4 s** unless it carries `confirm: false` — a
modal would need a Cancel and a way to dismiss it, which a keyboard-less fullscreen panel lacks.

Write rate and meaning:
- the **slider commits on release**, not per frame (a drag would rewrite the file, or fire a
  `CONFIG_SET`, dozens of times a second);
- **text and number fields commit on `editingFinished`**, not per keystroke (every prefix would be
  sent and rejected);
- a **nullable setting that is null renders as "—" / an empty field, not as its minimum**, and can be
  cleared back to null: `electricityPriceEurPerKwh` null means "no flat tariff, show —", not energy
  at 0.000 €/kWh.

**Typing** goes through the app's own keyboard (`frontend_v2/CLAUDE.md`). `SettingText` turns off
auto-capitalisation and prediction (its values are hosts, URLs and serials, and prediction holds text
in pre-edit, off `text`); `SettingNumber` asks for the number pad, digits-only unless the setting can
go negative (that pad has no minus). Both close the keyboard on Enter without dropping focus. While
the keyboard is up `SettingsPane` gives the Flickable its height as `bottomMargin` (or the last rows
could never scroll above it), and `revealFocused()` scrolls the focused field into the strip still
visible — on both a focus change and the inset change, since the inset settles only after the
panel's slide-in.

## Dialogs

Every dialog is a `ModalDialog`: the opaque card over a scrim that takes every press and wheel turn
beside it (a MouseArea with no wheel handler lets the wheel through to the page; a list inside the
card still scrolls, being above the scrim). Over a map, where nothing blurs the view, a dialog gives
a `backdrop` (and its `frost`) and the card is frosted glass (`RoadCameraPopup`) — darker than a
panel's (`Theme.dialogGlass*`), over a FrostLayer that blurs further (`Theme.dialogFrost*`), so the
text behind cannot be read through it. The scrim stops presses but not the pointer handlers beneath,
which still see a press another item took — so a map under a dialog is switched off
(`TeslaMap.interactive`).

## Row details

**`details: "<id>"`** makes `SettingRow` load a component under the label from its own small table,
for facts that belong to one row without being its value — these rows carry no `help`, and their
details are the whole explanation. `DebugLogDetails` is handed the row's setting ("Palautuu tasolle
INFO klo 14:52 (vielä 30 min)" from `runtime.until` / `runtime.returnTo`, in the warning colour while
on). The Spotify ones render through **`SettingDetails.qml`** — a status line led by a green / amber /
red / grey dot, then label–value pairs; grey means *could not be established*, kept apart from red
on purpose.

- **`SpotifyAuthDetails`** — red only when the backend says the grant does not work; amber within 30
  days of `validUntil`, past it while Spotify still accepts the grant (the 180-day estimate is
  deliberately early), and when the dates are unknown (no grant record). Re-evaluates hourly, so
  amber arrives on a panel left on this view.
- **`SpotifyDeviceDetails`** — amber when Spotify does not list the configured device: Spotify lists
  only devices that are up, so *switched off* and *wrong id* look the same, and the text says both.
  It asks for `SpotifyDevice.configuredStatus` on construction, throttled in C++ since the row is
  rebuilt whenever its section is shown.

## Write results

**A write's result shows beside the title of the row that made it** — "Tallennettu" in green for
2.5 s, a rejection in red for 6 s. The state lives in `SettingsView.rowFeedback`, **not in the row**:
a write that changes the section's shape rebuilds the cards, and the row may not outlive it. A
**failure** with no row to sit beside — a keyless `CONFIG_SET_RESULT` (a refused restart or reboot),
a lost connection, a hidden setting — goes to the notification pill
(`Notifications.post("settings", …)`); a row-less **success** is dropped, since a hidden setting is
written beside a visible one (the DEBUG duration beside the level) whose row reports it. A
restart-tier write gets no extra wording: the badge and the banner say it.

**The restart badge names the half that restarts**, from the entry's `origin`: *sovelluksen
uudelleenkäynnistys* on a local restart-tier row (read once by `AppConfig`) and on an action that
restarts the app (`apply: "restart"` on an action only badges it, since an action holds no value for
the banner to compare); *palvelimen uudelleenkäynnistys* on a backend one (read once by a backend
service, or a hook setting whose service is absent). They are separate restarts
with separate banner buttons, so a bare *uudelleenkäynnistys* left the user guessing which to press.

## Issues and the fix spotlight

The header shows **"Ongelmia havaittu" + *Tarkista*** only while `SettingsIssues` reports something
(a red dot if any issue is an error, amber for warnings only). A lost backend is itself an issue, so
a screen showing only the local sections does not read as a bug.

- **`SettingsIssues.qml`** is a plain binding over the singletons, so an issue appears and clears by
  itself. Each names the **setting key that fixes it**, its section looked up in `Settings.groups`;
  an issue whose row is not in the schema right now offers no *Korjaa*. **While disconnected, only
  the connection is reported** — every other check reads backend state that is stale until it
  returns — and a backend that wants the password counts as not there, reported as that
  (`backendLogin`) rather than as unreachable. An empty screensaver folder is deliberately *not* an
  issue: the switch is unavailable without photos, so a user who wants no screensaver could never
  clear it. The view refreshes `SpotifyDevice.configuredStatus` whenever it becomes current, since
  the device checks read it.
- **`SettingsIssuesPopup.qml`** lists them in a `ModalDialog` under the header.
- **`SettingSpotlight.qml`** is where *Korjaa* ends: the view selects the fix's section and blurs its
  content (the dialogs' layer), and this draws a **crisp copy** of the row — a `ShaderEffectSource`
  over an opaque plate recreating the card, ringed in the accent — until the next tap; the row cannot
  leave the blurred layer, so a copy is the only way to show it sharp. **A press on the copy
  dismisses and is not accepted**, so it reaches the real row beneath (the highlighted *Kirjaudu*
  works first time); a press anywhere else is swallowed, so a blind tap on the blur flips nothing.
  The row is found by key on every 80 ms tick (`settingRow:<key>`, `SettingsPane.rowItem()`), since a
  shape change rebuilds every row and a settling widget or a reveal can move one; the first ticks
  also scroll it to the middle. Nothing is drawn before the first tick: a just-selected section is
  not laid out yet.

## Status widgets

A subsection may name a **`status`** widget, which `SettingsPane` loads in the card above the rows
from a small component table; `active:` gates construction, so the probe does not fire for a card
that did not ask for it. A subsection with a `status` and **no settings** is exempt from the
empty-section filter. The hook exists because not every fact fits a row: *is that address reachable*
belongs to the host and port **together**. The probe follows the SAVED values (what startup will
use), debounced 400 ms so editing host then port probes once; advisory only — the backend may
legitimately not be up yet.

## The backend login — `BackendLoginPrompt.qml`, *Kirjautuminen*, Näytöt

The connection and its login are `ServerClient`'s (`../../core/CLAUDE.md`); these are its faces.
- **`BackendLoginPrompt`** is app-level in `Main.qml`, like the Spotify prompt: no view gets data
  until the display has logged in. A `ModalDialog` in the top half (the keyboard takes the bottom),
  showing *Kirjaudutaan…* while the key is derived (seconds on a Pi), and saying so instead of asking
  when the backend has no password. Its ✕ leaves the views usable (the backend address may be what
  is wrong); nothing typed survives a closed prompt.
- **Yhteydet › *Kirjautuminen*** is a `backendLogin` action row (`confirm: false`) whose details say
  whether this display is logged in, and why not; it brings the prompt back
  (`Server.showLoginPrompt()`) and is the issues list's fix row for a missing login.
- **Ylläpito › Näytöt**'s `pairedDisplays` widget lists every display that has logged in, with a
  *Poista* that arms and confirms within 4 s (`SettingAction`'s guard).

## Ylläpito › Lokit — `DebugLogPopup.qml`, `LogClearPopup.qml`

Both act on the app's own log files; the journal follows the level but never below INFO and is never
cleared (`backend/src/system_service/CLAUDE.md`).
- Choosing DEBUG (`onSelect`) opens `DebugLogPopup`: durations from 15 min to 8 h, then
  **Toistaiseksi** (minutes 0, no end, for development; it survives restarts and says so), starting
  from the one used last. *Ota käyttöön* writes `logging.debugMinutes` and `logging.level`;
  cancelling writes nothing. The `debugLog` details collapse to no height when DEBUG is off, or the
  label would sit high.
- *Tyhjennä lokit* (`confirm: false`) opens `LogClearPopup`: *Tyhjennä kaikki* or *Säilytä
  varoitukset ja virheet* (the primary). It closes on the choice; `Logs.finished` reports beside the
  row through the ordinary row feedback.

## Järjestelmän tila — `SystemStatusSection.qml`

A vertical `ElasticFlickable`: `SystemOverviewCard`, then the backend host's last ten minutes as
`SystemGraphCard`s (CPU per core, memory, disk, network, and a full-width CPU temperature card), then
a `SystemServiceCard` per backend service. `SystemHistory` and `System` (`../../core/CLAUDE.md`) are
retained only while the section is visible.

- **The overview** answers *is the system healthy* in one line, lists the issues behind it, errors
  first, and gives the host's and the backend's uptime. An issue is a service card in `error` or
  `warn` — never `off`, which is deliberate (no Zappi, a flat tariff) — or a host threshold judged on
  the latest graph sample: disk ≥ 90 % used (error ≥ 95), memory ≥ 90 % (error ≥ 97), CPU ≥ 80 °C
  (error ≥ 85, where the Pi's firmware throttles hard). While disconnected it says only that: the
  last reply is stale.
- **Service cards** render each of the backend's `services` generically. Their label–value columns
  **wrap rather than elide** — a path cut in the middle hid the part being looked for, and with no
  spaces it breaks at a slash or anywhere. They count only the **open** warnings and errors (none
  while *Toiminnassa*; the backend decides which are open, `backend/src/system_service/CLAUDE.md`)
  beside a muted *N aiempaa (24 h)*, with *Näytä* opening `SystemLogPopup`. The Repeater's model is a
  **count**, since a poll replaces the list every 5 s and a new array would rebuild every card.
- **Temperature**: a host with no sensor (`temp_available: false`, WSL2) shows a line in place of
  the graph.
- **Disk is graphed as I/O**, with the free space as the headline: space changes too slowly over ten
  minutes to be a line, and disk-full is still the failure worth seeing.
- **Colours are the dark categorical palette in its fixed order**, validated against the card surface
  (`#212121`) for lightness, chroma, colour-blind separation of neighbours and contrast;
  `Theme.accent` is too light for that band and stays for the single memory line. A core keeps its
  colour by number; **past eight cores the hues repeat dashed**, and the legend draws the dash too.
- **A legend only for two or more lines**, each entry with its value, fixed-width (`widestValue`) so
  the entries never shuffle; a single line is named by the title.
- **Rates use one unit per window** — the largest that keeps the peak under 1000 of it — named in the
  title ("Levy (kB/s)"), since the graph labels its axis with plain numbers. Percentages and
  temperature use a fixed 0–100.

**The graphs are the app's own `HistoryGraph`**, wrapped by `SystemGraphCard` as `ChargingGraphCard`
wraps it and fed like the Charging view's live graphs: the first data `reloadFull()`s, later updates
`advanceLive()` (keeping a zoom the user made). What it offers for this, inert at the defaults so no
other graph changes:
- **`extraSeries`** — further lines over the same axes (`{points, color, label, dashed}`, the points
  `Qt.point`s), traced by `GraphSeries` and drawn as Shapes beneath the main line, so they move with
  its transforms and the draw-in uncovers them with it. They join the y-fit, get a dot each when
  inspecting, and a multi-line readout lists every line. Dashed is `ShapePath.DashLine`, `[2, 1.5]`.
- **`lineColor`** / **`seriesLabel`**, **`fixedMinY` / `fixedMaxY`** in place of the fit,
  **`formatValue`** for the readout, and **`wheelZoom`** — off here, since the section scrolls and
  the wheel belongs to the page.
- A multi-line graph has no glow or live marker: on one line of several, they would single it out.

## Media › Taajuuskorjain — `EqualizerPanel.qml`

The backend's *Taajuuskorjain* card (`backend/src/audio_service/CLAUDE.md`): this `equalizer` widget
draws the five bands as knobs on a curve; the bass shelf is the ordinary slider row under it.

- **The band rows are hidden, and `decorateSections` strips hidden entries before any widget sees
  them** — so the widget takes the band list (key, label, range, `hz`) from the subsection's own
  `bands`, which the backend repeats there for exactly this, and the values from `Settings.valueOf`.
  The equalizer's `runtime.state` rides on the bass row, the card's one visible entry; *unavailable*
  fades the plot and, through the `equalizer` condition, the bass row.
- **Only a press on a knob grabs** (within 36 px of its centre), with `preventStealing` so the
  Flickable cannot turn the drag into a scroll; anywhere else the press goes to the page, so the plot
  is never a dead zone the page cannot be scrolled from.
- **The other editors' commit rules**: a drag or a wheel spin (1 dB per notch, per column) moves only
  the knob and writes once. Until the schema confirms, the knob holds the written value (`pending`),
  cleared on the confirming schema, on `writeFailed` (the knob goes back) and on an `unchanged`
  result (no schema follows one). **The pending value is set before the band is let go**: the other
  order re-evaluated the knob against the old value with its animation on, so on release it slid
  back toward 0 and returned.
- **The curve is a monotone cubic (Fritsch–Carlson)** through the knobs — a plain spline overshot
  between knobs at opposite ends and drew past ±12. It runs through their **animated** values, so
  *Nollaa* morphs it flat, and through an extra point at each edge: the right level with the top
  band, the left the bottom band plus the bass shelf, which is how the bass slider shows on the curve.
- **The status row keeps its height** whether or not *Nollaa* shows, so the first band moved off
  flat does not push the bass row under the finger. *Nollaa* writes each non-zero value once and is
  not armed — like the graphs' *Palauta*, it only puts a view back.
- **Behind the curve is the spectrum of what is playing** (`MediaSpectrum`), recorded **after the
  filters** (`backend/src/audio_service/CLAUDE.md`), so a knob shows its effect on the sound. Log
  frequency is fitted to its columns by least squares from each band's `hz`, which puts every band
  within a tenth of a column of its knob — the bands are two octaves apart but the top one less, so
  no single scale hits all five. It is clipped, since the line style closes its fill outside itself,
  and records only while the Settings view is current (`SettingsPane.live`) and the card is built
  (`SpectrumLevels`, `../../core/CLAUDE.md`).

## USB photo import — `UsbImportPopup.qml`

*Kuvakansio*'s *Tuo USB:ltä* opens it through `Settings.invokeAction` → `actionRequested` →
`UsbImport.begin()`, as the Spotify dialogs do: the drive list, what the drive's
`tesla_homedash_screensaver` folder holds, then the copy — every step done by the backend.

- **Top-anchored and short.** A popup inside a view cannot cover the menu's swipe-up strip
  (`frontend_v2/CLAUDE.md`, *Overlays and z-order*), so the drive list scrolls past four entries
  rather than growing the card into it.
- **Buttons pinned to the card's edges**: the import button appears when the scan answers, and a
  button joining a centred row would slide the others under a finger already reaching for them.
- **Leaving the view closes the dialog and unmounts the stick — except mid-copy**: the home return
  fires after minutes without a touch, which a long copy outlasts; the dialog is simply still there
  on the way back.
