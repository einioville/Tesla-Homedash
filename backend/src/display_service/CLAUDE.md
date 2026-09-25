# `display_service/` — panel power (issue #35)

Runs `wlopm --on/--off <output>` (`*` = every output). The **frontend decides when** (it is the only
side that sees touch input) and **this side does the switching**, because system calls belong to the
backend. Reports `available=0` when wlopm is absent so the dashboard never arms a timeout that could
do nothing, and `run()` powers the panel on at startup so a backend restart cannot leave it dark.
Needs the compositor socket: `XDG_RUNTIME_DIR` is already in a `systemd --user` unit's environment,
`WAYLAND_DISPLAY` is not (the unit is wanted by `default.target`), so the README's unit sets it.

**State is the outcome, never the intent.** `set_power()` skips a request for the state it believes
the panel is already in, so a wrongly recorded "on" silently drops every later wake. `run()` and
`shutdown()` therefore set `__on` from what `wlopm` actually returned: a failed startup power-on is
recorded as OFF (and broadcast), which costs at most a redundant `wlopm --on` on the next wake. The
frontend throttles activity-driven wakes to one per 2 s, so a wake that keeps failing does not turn
into a process per touch event.
