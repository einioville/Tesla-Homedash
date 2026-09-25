# `display_service/` — panel power (issue #35)

Runs `wlopm --on/--off <output>` (`*` = every output). The **frontend decides when** (it is the only
side that sees touch input) and **this side does the switching**, because system calls belong to the
backend. Reports `available=0` when wlopm is absent so the dashboard never arms a timeout that could
do nothing, and `run()` powers the panel on at startup so a backend restart cannot leave it dark.
Needs the compositor socket: `XDG_RUNTIME_DIR` is already in a `systemd --user` unit's environment,
`WAYLAND_DISPLAY` is not (the unit is wanted by `default.target`), so the README's unit sets it.

**State is the outcome, never the intent.** `set_power()` skips a request for the state it believes
the panel is already in, so a wrongly recorded "on" silently drops every later wake. Every change
goes through `__switch()`, which sets `__on` from what actually happened: a refused `wlopm` call
leaves the panel as `wlopm --json` reports it, and a startup power-on that fails with no readable
answer is recorded as OFF (and broadcast), which costs at most a redundant `wlopm --on`. The
frontend throttles activity-driven wakes to one per 2 s, so a wake that keeps failing does not turn
into a process per touch event.

**Faults** (the third byte of `DISPLAY_POWER_STATE`, `protocol.DISPLAY_FAULT_*`), because both known
failures are otherwise silent:
- **`REFUSED`** — `wlopm` exited non-zero. A running **wayvnc** does this in both directions (#46),
  so the panel just never blanks. The state is read back rather than guessed (a VNC server blocks
  changes, not reads), so a lit panel under VNC stays "on" and the dashboard does not retry a wake
  on every touch. Cleared by the next successful change.
- **`OUTPUT_LOST`** — `wlopm --on` exited 0 but the output is **gone** from `wlopm --json`. On labwc
  0.20.1 / wlroots 0.20.2 (Raspberry Pi OS since September 2026) a long blank can drop the output
  from the compositor for good (#43); only `sudo systemctl restart lightdm` brings it back, and the
  backend survives that. **Sticky, and power-off is refused until the backend restarts** — on a
  keyboard-less panel every further blank risks a black screen only SSH can undo. Only a *missing*
  output counts: one that is present but still reports off is `REFUSED`, retried on the next wake,
  so a slow monitor cannot switch the feature off for good. An unreadable `--json` (an older wlopm)
  is never a fault.

There is no automatic recovery: `wlr-randr --output … --on` fails on a wedged output, and the one
modeset that revived it did so at the wrong resolution.
