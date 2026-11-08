# `display_service/` — panel power (issue #35)

Runs `wlopm --on/--off *`, always every output. The **frontend decides when** (it is the only
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
- **`OUTPUT_LOST`** — `wlopm --on` exited 0 but the output is **gone** from `wlopm --json` and
  the recovery below could not bring it back to its native mode. On labwc 0.20 / wlroots 0.20
  (Raspberry Pi OS since September 2026) a long blank can drop the output from the compositor
  (#43). **Sticky, and power-off is refused while it holds** — on a keyboard-less panel every
  further blank risks a black screen only SSH can undo. Each later wake tries the recovery again,
  and one that works clears it, as does a backend restart; an output brought back by hand does
  not, since it says nothing about whether this host can recover the next one. Only a *missing*
  output counts: one that is present but still reports off is `REFUSED`, retried on the next wake,
  so a slow monitor cannot switch the feature off for good. An unreadable `--json` (an older
  wlopm) is never a fault. Lit at the kick mode below counts as on, and still as the fault.

**Recovery of a dropped output** (#89) is through `wlr-randr`, which can set modes where wlopm
only switches power. On a wedged output `wlopm --on` and a modeset to the native mode both fail
(`failed to apply configuration`); a modeset through another listed mode (1920×1080) and back to
the native one brings the picture back, about 7 s after the wake. The reference Pi's journal held
seven wedges in three days (2026-10-29…31, labwc 0.20.1 / wlroots `0.20.2-1+rpt3`), all revived
that way; none since its 2026-10-31 reboot onto labwc 0.20.2 / wlroots `+rpt4`. So after a power-on
that finds the output missing, `__recover()` re-applies the native mode, then modesets through
the kick mode and back, waiting `_SETTLE_SECONDS` (2 s) after each modeset and checking after each
step; done means lit in `wlopm` and on the native mode in `wlr-randr`. A session restart
(`systemctl restart lightdm`) is deliberately not a step: it was never needed, and it would need
root and restart the frontend.
- **The modes are learned while the panel is lit** — `wlr-randr --json` at startup and after every
  power-on that worked, each enabled output's name and current (native) mode, and as the kick
  another listed resolution — because a dropped output is listed disabled, with no current mode.
  A backend started while the output is already dropped has nothing to restore. The panel
  advertises no preferred mode, so `--preferred` would fail.
- **The modes are passed as wlr-randr prints them** (`1280x800@60.023998`), so the refresh
  matches the listed mode exactly.
- **Wakes coalesce during a recovery.** It holds the lock for seconds while the frontend sends a
  wake per 2 s of touching; `set_power()` drops a request for the state the running switch is
  heading for (`__switching`), and one queued on the lock re-checks once it gets it.
- **Without `wlr-randr`** a dropped output is reported and not recovered; the Näyttö card says
  *Palautus: wlr-randr puuttuu*. Otherwise it counts the recoveries and gives the last one's time
  and step.
- `tests/test_display_service.py` acts the wedge out with fake `wlopm` / `wlr-randr` commands.
