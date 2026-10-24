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

## Frosted glass over a map — `GlassPanel.qml`, `FrostLayer.qml`

A `GlassPanel` frosts the backdrop behind it by capturing its own region (`ShaderEffectSource`),
blurring it (`MultiEffect`, several passes into textures of its own) and masking it round. Over a
map that follows the car, that re-renders every frame, for every panel — a few dozen render targets
on the Kartta view, all inside a view the view switch renders through a layer of its own while it
moves. **The glass has turned nearly clear at random** on the user's display, a few times, after no
action they could name (2026-10-18). It was never reproduced offscreen, so the cause is unconfirmed;
those nested per-panel passes are the suspect. **Panels over a map take their frost from one
`FrostLayer`** instead (`GlassPanel.frost`): the map
captured at a quarter of its size and blurred once, in the notification glass's tone, from which
each panel cuts its part with `resources/shaders/glassfrost.frag` (the rounded rectangle, a
one-pixel soft edge). That is three render targets for the whole view, and each panel's frost is a
plain texture lookup. The Kartta view's layer menu, zoom pill, data card, radar bar and warning
legend share one; the dashboard's map controls another, live only while they show. Panels not over
a moving backdrop (the notification pill) still frost themselves, and so does the Media view's
next-track card (`../media/MediaUpNext.qml`) over that view's drifting backdrop and spectrum: one
panel, live only for the last 20 s of a track. Its `backdropSource` is the view's `backdrop` item,
which holds every layer under the player and nothing over it, since a capture of an item that
contains the panel would contain the panel too.
