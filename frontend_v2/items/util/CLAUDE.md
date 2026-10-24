# `items/util/` — shared components

The view switch and the menu's swipe-up strip over every view are in `frontend_v2/CLAUDE.md`.

## `ScreenSaver.qml` and its photo folder

The photos come from one **fixed folder**, `~/.config/Tesla-Homedash/screensaver` (the `Photos`
singleton, `../../core/CLAUDE.md`). It is filled over scp or by the Options view's USB import
(`../settings/CLAUDE.md`). `FolderListModel.folder` binds to `Photos.url`, and the model watches the
folder, so photos copied in appear without a restart. With no photos the screensaver does not start
(`hasPhotos`).

Two measured facts about `FolderListModel` shape it. **An empty `folder` at component
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
onto the dashboard. The view menu's auto-pick delay (`menuAutoPickSec`, `frontend_v2/CLAUDE.md`,
*View switching*) sits in the same card.

**Spotify's takeover opens the Media view** (`spotifyAutoOpen`, on by default, in the same card),
also in `Main.qml`: the media type turning Spotify, from the radio or from nothing, which happens
once per Spotify session, so a pause and resume does not count and a Media view left while the
music plays stays left. It holds back in three cases:
- **Someone is using the panel**: a touch (`Idle.activity()`) within
  `Theme.spotifyAutoOpenQuietMs`, 30 s, a fixed value by choice.
- **The Options view's device scan is running** (`SpotifyDevice.flowActive`): re-identifying the
  device already in use takes playback over mid-scan, and leaving the view cancels the scan.
- **The snapshot a (re)connection brings** (3 s from `Server.connected`): it shows a takeover that
  happened earlier, and a backend restart would otherwise turn every display to the Media view.

With home return on as well, the dashboard comes back after its delay like after any other view.

## `HoldRepeatArea.qml` — tap to step, hold to repeat

The press area behind every ± button (the climate card's target arrows, `SettingNumber`'s
steppers), so they all behave the same (#48). A tap steps on **release**, so a press that becomes a
drag steps nothing; a hold repeats after a 400 ms delay, and the release ending a hold adds no
extra step (a naive `onClicked` + running `Timer` steps twice on any slightly long tap).
`canStep` false stops the repeat and swallows the tap, so a held button stops at its limit instead
of hammering it. `finished()` fires once per press however it ended, for callers that batch steps:
**`SettingNumber` must**, because every settings write is a disk write (`../settings/CLAUDE.md`),
whereas the climate arrows can send every step — `Vehicle.plus_temp` only moves the local setpoint
and nothing reaches the car until climate is next toggled.

## Shared motion and controls — use these, don't re-draw them

Five pieces exist so every future control moves and responds the same way. Their timings are
`Theme` tokens (*Motion*), so retuning one retunes every use.

- **`ToggleSwitch.qml`** — the on/off switch. `checked` in, `toggled()` out; the caller writes the
  value wherever it lives and the knob follows `checked`, whoever changed it. On a change the
  knob's **leading edge runs to the far end first** (`switchStretchDuration`), making it a pill
  across the track, then the tail follows (`switchSettleDuration`) and it is a circle again. The
  two edges are separate properties animated in sequence from wherever they are, so a second tap
  mid-change turns the knob around instead of jumping it. It never animates at construction.
  Sized with `trackWidth` / `trackHeight` (`touchMargin` widens the press area of a small one —
  `TeslaFieldTable`'s compact switch). It does not fade itself when disabled: the settings row
  already fades, and a second fade on top would leave it at about a sixth of full opacity.
- **`Reveal.qml`** — content that appears **slides out from under the item above it**, set back
  (`revealSetBackScale` / `revealSetBackOpacity`), then comes forward to level; hiding folds it back.
  The box grows from 0 to `fullHeight` while the content travels down from one full height above,
  clipped to the box — so in a Column it emerges from the shared edge and pushes everything below
  down. Clipping is what makes "under" work without drawing anything on top: the settings cards are
  translucent and rows have no background to hide behind. **Imperative on purpose**:
  `show(delay)` / `hide(delay)` / `snap(shown)`, because only the caller knows the order — the
  domino stagger (`revealStagger`) is the caller ranking what appeared in one change
  (`SettingsPane`'s `card.animateShown()`). Children go inside; they lay out at `fullHeight`.
  **It needs a delegate that outlives the change** — a Repeater recreating its items on every model
  update leaves nothing to animate (`../settings/CLAUDE.md`, *Rows survive a write*).
- **`ElasticFlickable.qml`** — a vertical Flickable with soft ends: dragged past the top or bottom it
  follows at half the finger's distance (measured in Qt 6.11's `qquickflickable.cpp`), a fast flick
  overshoots, and on release it springs back over `reboundDuration`. `VerticalFlick` rather than
  the default, so a short page still gives under the finger and never moves sideways. Use it for
  any scrolling page in place of a bare Flickable. (A ListView is its own Flickable: give it the
  same `boundsBehavior` and `rebound` to match.)
- **`WheelStepArea.qml`** — mouse wheel → value steps, the wheel's counterpart to
  `HoldRepeatArea` with the same contract (`settled()` in place of `finished()`):
  `stepped(direction)` per notch (120 units, touchpad deltas added up), `settled()` once the wheel
  has been still for `settleDelay`. Lay it over the whole control: `acceptedButtons: Qt.NoButton`
  lets presses and drags through, and it accepts every wheel event it gets, so the page does not
  start scrolling when the value hits its limit. A disabled control disables it too, and then the
  wheel scrolls the page as usual.
- **`ReleaseVelocity.qml`** — the speed a drag is let go at, for deciding whether a release is a
  flick: `start(position)` on press, `move(position)` per move, `release(position)` gives px/s.
  It measures over only the last `window` (100) ms, so a finger that stops before lifting releases
  at rest — the speed of the last move event would still read as a flick after a pause, and move
  events arrive in bursts whose 1 ms gaps are spikes of thousands of px/s. The view switch's three
  gestures use it (`../../CLAUDE.md`, *View switching*).

## `MarqueeText.qml` — a line too long for its place

The media title and artists on the dashboard card and the Media view. A line that fits stands
still at its `horizontalAlignment`; one that does not rests at its start, the cut end faded rather
than elided, and every `marqueeRestDuration` scrolls one loop — a copy following `gap` behind, so
it ends where it began — at `marqueeSpeed` line heights a second, so large and small lines read at
the same pace. The rest is a `Timer` and only the scroll a `NumberAnimation`, so a resting line
costs no frames (`../../CLAUDE.md`, *Motion that keeps running*); a `PauseAnimation` in a
sequence would redraw the window all through the rest. `active` gates the start of a scroll (the
callers pass their view's `isCurrent` and `Media.isPlaying`), as does the effective `visible`, so
nothing scrolls under the screensaver. The fade is a `MultiEffect` mask over a gradient, with
`RoundedImage`'s threshold and spread (smoothstep over the mask's alpha); the near edge's fade
follows the offset, so it grows in as the line leaves its start and is gone again as the copy
arrives.

## Frosted glass — `GlassPanel.qml`, `FrostLayer.qml`

**One container, one source of frost.** `GlassPanel` is the glass everything sits on — the
notification pill, the map panels, a dialog over a map, the Media view's next-track card, the
graph's inspect readout: a dark tint, a rim and a highlight over its part of a `FrostLayer`
(`frost`, with `backdropOrigin` the panel's top-left in the layer's source item). A `FrostLayer` is
the only thing that makes frost: its backdrop captured at a quarter of its size and blurred once, in
the notification glass's tone, from which each panel cuts its part with
`resources/shaders/glassfrost.frag` (the rounded rectangle, a one-pixel soft edge) — three render
targets per backdrop however many panels share it, and a texture lookup per panel. A panel never
captures or blurs on its own; one with no `frost` is the glass alone (the graph's readout, whose
backdrop would be its own ancestor). A FrostLayer is declared beside its backdrop, never inside it:
a capture of an item that holds the panels would hold the panels too. One per backdrop: the Kartta
view's panels share one and its dialogs have another, blurring further and darker
(`Theme.dialogFrost*`); the dashboard's map controls share one, live only while they show, and its
dialogs frost all of the dashboard (`surface`); the Sää view's radar bar has one and its dialogs
another; the notification pill frosts the whole view host while it shows; the next-track card
frosts the Media view's `backdrop` item (every layer under the player and nothing over it) for the
last 20 s of a track.

**A FrostLayer rebuilds itself** — capture, blur and output thrown away and made anew — each time
it goes live and every `Theme.glassRebuildMs` (60 s) while live. The reason is Qt's: an effect holds
a link to the provider of each texture it reads, and when that provider is destroyed Qt drops the
link and never looks it up again (`QSGRhiShaderEffectNode::handleTextureProviderDestroyed`; it looks
again only when the effect's source *property* changes or its node is rebuilt, not on a resize).
The effect then samples a transparent dummy, with no warning, until the app restarts. That is how
the glass went clear for good on the dev box (the Kartta layer menu 2026-10-18, the Sää radar bar
2026-10-24), through map drags, resizes and view switches. What destroyed the provider was never
found: nothing in the app does, and offscreen neither random view switching nor a watcher on every
provider caught one dying. A rebuild links everything afresh, so a lost link lasts a minute at
most, or until its view is opened again. Measured offscreen: a provider released the way Qt
releases one turns the glass dark (`glassfrost.frag` draws the frost opaque), and a rebuild, a view
switch and the timer each bring it back; the first frame after a rebuild is already frosted; a
rebuild costs 0.36 ms of GUI thread on the dev box; memory settles after a few hundred rebuilds
(measured over 3000).
