# `display_service/` — panel power (issue #35)

Runs `wlopm --on/--off <output>` (`*` = every output). The **frontend decides when** (it is the only
side that sees touch input) and **this side does the switching**, because system calls belong to the
backend. Reports `available=0` when wlopm is absent so the dashboard never arms a timeout that could
do nothing, and `run()` powers the panel on at startup so a backend restart cannot leave it dark.
Needs the compositor socket: `XDG_RUNTIME_DIR` is already in a `systemd --user` unit's environment,
`WAYLAND_DISPLAY` is not (the unit is wanted by `default.target`), so the README's unit sets it.
