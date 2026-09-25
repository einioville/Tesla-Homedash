# `audio_service/` — host audio (issue #37)

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
- **Device first, volume second, always.** A sink carries its *own* volume, so switching output
  without re-applying the volume makes the user's setting silently stop holding.
- **`wpctl` does not clamp** — `set-volume 150%` is accepted and overdrives the sink — and
  **`wpctl get-volume` exits 0 even for a missing node**, so the `Volume: ` prefix is the test, not rc.
- The feature needed **no protocol code and no frontend change**: two `config.json` keys, one hook,
  one schema subsection. Two generic additions to `ConfigService` carry it — `register_options(key,
  provider)` (a service owns its own dynamic enum) and `register_guard(name, guard)` (a pre-write
  veto that, unlike a hook, runs *before* anything is persisted and can honestly reject
  "this host cannot do that").
