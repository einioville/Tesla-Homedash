# `audio_service/` — host audio (issue #37) and the equalizer

`audio_backend.py` holds one abstract `AudioBackend` plus four implementations, and
`detect_backend()` probes the host in the order **`pactl` → `wpctl` → `amixer`**, falling back to
`NullAudioBackend`. `pactl` goes first because it covers real PulseAudio *and* pipewire-pulse with
one adapter **and addresses sinks by a stable name** — `wpctl set-default` takes only a
session-scoped numeric id, so that path resolves the stored `node.name` against `pw-dump` on every
write. Bookworm ships PipeWire + WirePlumber + pipewire-pulse, but `pipewire-pulse` only *suggests*
`pulseaudio-utils`, so `pactl` is not guaranteed and `wpctl` is the always-present fallback.
Enumeration on that path uses `pw-dump`'s JSON, never `wpctl status`'s box-drawing tree.
`AudioService` applies `audio.volumePercent` / `audio.outputDevice` and refreshes the device list
every 15 s (HDMI and Bluetooth hotplug). Load-bearing details:
- **A volume nobody stored is adopted, never pushed** (#47). An existing `config.json` has no
  `audio` block, and `audio_config` merges `_AUDIO_DEFAULTS` over that — so force-applying on first
  start would silently drop a host set to 85 % down to the schema's 60 %. With no stored
  `volumePercent`, `run()` applies the device only, then reads the host's volume and stores it
  through `ConfigService.apply_write` (wired after construction by `attach_config_service`, since
  ConfigService takes this service's hook/options/guard). Once a value is stored, the startup
  force-apply is right and stays.
- **Device first, volume second, always.** A sink carries its *own* volume, so switching output
  without re-applying the volume makes the user's setting silently stop holding.
- **`wpctl` does not clamp** — `set-volume 150%` is accepted and overdrives the sink — and
  **`wpctl get-volume` exits 0 even for a missing node**, so the `Volume: ` prefix is the test, not rc.
- There is **no audio protocol code**: two `config.json` keys, one hook, one schema subsection. Two
  generic `ConfigService` registrations carry it — `register_options(key, provider)` (a service
  owns its own dynamic enum) and `register_guard(name, guard)` (a pre-write veto that, unlike a
  hook, runs *before* anything is persisted and can honestly reject "this host cannot do that").

## The equalizer — `equalizer.py`

Media › *Taajuuskorjain*: five peaking bands (60 Hz, 250 Hz, 1 kHz, 4 kHz, 12 kHz, ±12 dB, Q 0.8)
plus a 90 Hz low shelf (`bassBoost`, 0…+12 dB), all `audio.*` keys under the `"equalizer"` hook
and guard. The radio (libVLC) and Spotify (spotifyd) are unrelated clients, so the only place one
equalizer reaches both is the audio server: **a PipeWire filter-chain sink** built from the module's
built-in biquads, which the stock `pipewire` package ships (Bookworm and Trixie) — nothing to install.
Load-bearing:
- **It runs only while the curve is not flat.** All-zero gains run no chain at all, so a host where
  nobody touches the equalizer keeps exactly the audio path it had. Leaving flat starts it; returning
  to flat stops it.
- **The chain is a `pipewire -c <file>` client process this service owns** (config and pid file in
  `$XDG_RUNTIME_DIR/tesla-homedash/`), not a drop-in in the user's PipeWire config: nothing outside
  the app's runtime directory is written and stopping it needs no audio-server restart. It is
  launched through `setpriv --pdeathsig TERM`, so it dies with the backend however the backend dies
  (verified: no orphan after the backend process was dropped); a pid file plus a `/proc` cmdline
  check stops one left by a run without `setpriv`.
- **Gains change in place** with `pw-cli set-param <sink> Props '{ params = [ "eqBand3:Gain" 6.0 … ] }'`
  — no restart, no gap. Measured through the chain: a 250 Hz tone at exactly +12.0 / −12.0 dB.
- **While it runs, the chain IS the default output.** Streams that follow the default (VLC, spotifyd)
  move into it; the chosen output becomes where the *chain* plays, set live through the
  `target.object` metadata on its output node (`pw-metadata`, measured on WirePlumber 0.4.17). When
  that output disappears, WirePlumber falls back to the next sink rather than going silent
  (measured), and it never links the chain into itself — the two nodes share a link group.
- **The chain's target is never left to WirePlumber.** With *Oletuslaite* it plays into the host's
  own default from before the chain took the default over — WirePlumber would pick by priority and
  move the sound from, say, the HDMI output chosen on the desktop to the headphone jack. That default
  is **stored as `audio.hostDefaultDevice`** (state, in no schema, written straight through `Config`
  like the radio's station), because once the chain has run WirePlumber remembers IT as the default
  and the host's choice can no longer be read back after a power cut. Stopping hands the default back
  (to the chosen output, else the stored one) **before** the chain stops, so streams move straight
  to the right output; a flat start with a stored value restores it (the last run never handed back).
- **Volume goes to the real output by name** while the chain runs (`set_volume(percent, device)`);
  the chain's sink stays at 100 %. So the dashboard's volume means the same with the equalizer on or
  off, and a chain that dies leaves the output at the user's level, not at full.
- **Moving streams skips filter outputs.** `PulseAudioBackend` moves every sink-input on an output
  switch; the chain's own output is one, and moving it into the chain would feed it its own sound.
  Streams carrying `node.link-group` are skipped (parsed from `pactl list sink-inputs` under
  `LC_ALL=C`, since pactl translates the headings the blocks are split on).
- **`pw-dump` can print more than one JSON array** when the graph changes mid-dump (measured on the
  chain's start); `parse_pw_dump()` merges them. Plain `json.loads` failed, and the health check read
  that as the chain having died. A dump that cannot be read is "unknown", never "gone".
- **The 15 s timer restarts a chain that died or left the graph** (a PipeWire restart), once per
  loss. A start that fails sets state `failed` and is retried only by the next equalizer write, so
  an impossible host does not log a failure every 15 s.
- **State for the Options view** is `equalizer_runtime()` — `detecting` → `unavailable` | `off` |
  `on`, or `failed` — merged into the **bass row's** entry as `runtime`: the band rows are hidden,
  and the frontend strips hidden entries before any widget sees them. Detection ends with a
  `ConfigService.broadcast_schema()`, since a view may have connected while it ran. `guard_equalizer`
  refuses writes only once detection has said `unavailable`. On WSL the chain runs on PipeWire's dummy
  sink while VLC plays through WSLg's PulseAudio, so it is testable there but not audible.
- **Not handled:** the host's own volume applet now drives the chain's sink (the default), so its
  level multiplies with the dashboard's; and choosing another default output outside the dashboard
  bypasses the chain until it next starts (a backend restart, or the curve leaving flat again).

## The Media view's spectrum — `spectrum.py`

`AudioSpectrum` serves `MEDIA_SPECTRUM_WATCH` (`0x1F`): while at least one display shows the Media
view it runs `pw-record` on the **default output's monitor** (`stream.capture.sink`), mono at 48 kHz,
and sends each watching display `MEDIA_SPECTRUM` (`0x20`) about 30 times a second — 40 log-spaced
bands, 40 Hz to 16 kHz. The frontend draws them as pill bars or a line (`frontend_v2/items/media/MediaSpectrum.qml`).
The monitor hears the radio and Spotify alike, since both play into the default output — the
equalizer's chain when it runs. Load-bearing:
- **Only while watched.** The display sends `on` when the view comes live and `off` when it leaves,
  and again after a reconnect, since a watcher is forgotten with its connection. The server swallows
  a write to a dead display, so the service drops watchers whose writer `is_closing()` itself (the
  device scan's rule, `../media_service/CLAUDE.md`); after the last one the recording stops.
- **The recording is passive** (`node.passive`), so it never keeps an idle output awake. With nothing
  playing it receives nothing; after `QUIET_S` without sound the watchers get one flat frame and then
  nothing until it returns, so the displays stop redrawing too.
- **Levels follow the loudest band.** Each band's power is summed (the bands widen with frequency,
  so pink noise comes out level — measured), and the dB values map a `RANGE_DB` window under a
  ceiling that rises at once and falls `CEILING_FALL_DB` a second, never below `MIN_CEILING_DB` —
  so a quiet recording or a low volume fills the height as a loud one does.
  Tuned on Radio Rock and Radio Suomipop recordings: mean levels about 0.3–0.45, peaks near 0.7.
  The bands below ~100 Hz are narrower than an FFT bin and read the power at their centre,
  interpolated, so neighbours there still differ.
- **`SpectrumAnalyser` is apart from the recording**, so it can be fed from a file — how the tuning
  above was done. On WSL the radio plays through WSLg's PulseAudio, not PipeWire, so the monitor
  hears only what `pw-play` sends it; on the Pi everything passes through PipeWire.
- `pw-record` runs through `setpriv --pdeathsig TERM` like the equalizer's chain, and a recording
  that dies is restarted after `RESTART_DELAY_S` while someone watches. A host without `pw-record`
  logs one warning and the line stays flat.
