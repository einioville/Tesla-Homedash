# `config_service/config_service.py` — runtime configuration (the Options view)

`ConfigService` serves `CONFIG_GET_SCHEMA` / `CONFIG_SET` / `CONFIG_RESTART` and snapshots the
schema to every new client (`register_service`). `SETTINGS_SCHEMA` is a literal list of groups
→ **subsections** → settings (issue #30), each group declaring `id` / `label` / `icon` and each
subsection `id` / `label` / optional `help`. **Group ids are shared with the frontend's own
bundled schema and a group present in both halves MERGES into one sidebar section** — which is
how `general` shows the frontend's screensaver card beside this file's location card. Every
setting declares `key` (dotted), `type` (`bool|int|float|string|enum`), Finnish
`label`/`help`, `unit`, numeric `min`/`max`/`step`, `nullable`, `options` (or the string
`"dynamic"`, resolved at schema-build time by the provider the owning service registered with
`register_options` — `audio.outputDevice`'s choices are the host's sinks; `timeZone`'s, which this
service registers itself, are covered under *Timezone* below), an optional `validator` name, and its **apply tier**. It is both the
write allow-list and the frontend's UI description, so adding a tunable is one entry here and
**no frontend change at all**.

> **Apply tiers — the load-bearing design point.** Every service snapshots the values it needs
> into instance attributes in its constructor and *never re-reads* `Config`, so mutating
> `Config` alone changes nothing at runtime. There is therefore no "live" tier:
> - **`hook`** — the owning service exposes **`apply_config()`**, which re-snapshots from
>   `Config` and does whatever else applying means (`MyEnergiService` reschedules through its
>   single `__apply_interval` point; `WeatherService` drops its cached frame and refetches).
>   Registered in `start_services` via `config_service.register_hook(name, svc.apply_config)`.
>   Implemented on: `WeatherService`, `MyEnergiService`, `TripLoader`, `ChargingLoader`,
>   `SpotPriceProvider`, `DebugLogging` (the `logging` block, `../system_service/CLAUDE.md`), and
>   `MediaManager.apply_config_spotify()` (which forwards to the Spotify player) /
>   `_media()` (the manager's own `media` block), and `AudioService`. `SpotPriceProvider` needs no cache flush — it caches *raw* prices and
>   applies VAT/margin on read.
> - **`restart`** — the value builds something that cannot be rebuilt in place: `timeZone`
>   (APScheduler cron jobs), `spotPrice.enabled` (whether `SpotPriceService` has a run task at
>   all). `myenergi.zappiSerial` (the Zappi resolved at connect) would be one too, but it is
>   `config.json`-only and not in the schema, like `spotPrice.baseUrl`.
>
> A `hook` setting whose hooks are all **unregistered** (no Zappi → no `MyEnergiService`) is
> reported to the frontend as `restart`, because that is what it truly is for that deployment.

**Restart.** `CONFIG_RESTART` sets an `asyncio.Event`; `run()` awaits it, waits
`_RESTART_DRAIN_SECONDS` so the preceding reply flushes, then flushes the log handlers and
calls `os._exit(RESTART_EXIT_CODE)`. The code is **42 — deliberately non-zero**, so the
README's `Restart=on-failure` unit restarts it without needing `Restart=always`. `os._exit`
rather than `raise SystemExit`: asyncio does not store SystemExit on a task, it propagates it
through the runner's teardown and prints a full traceback plus *"Task exception was never
retrieved"* — misleading noise in the journal for an intentional restart.

**Timezone.** `timeZone` is an enum: `"auto"` (the default, and what an absent key means) follows
the host's own zone through `tzlocal` (`utils/config_parser.system_timezone_name`, UTC when the host
names none), then `UTC`, then every zone in the tz database's continent/ocean areas, each labelled
with its offset *today* ("Europe/Helsinki (UTC+3)"). Legacy aliases and `Etc/GMT±N` are left out,
since the latter's sign is inverted from what its name says. A value outside the list that is
already in `config.json` is added so its row still shows it. The zones are cached, because
`available_timezones()` opens every zoneinfo file and the schema is rebuilt on every connect and write.

**Safety.** Validation happens before any write. The `timeZone` membership check is the important
one: an unresolvable zone makes `Config.__init__` raise, and since `timeZone` is restart-tier that
would be a restart *loop*. A failed `save()` rolls the in-memory value back so services and disk never
disagree. A hook that raises is logged and swallowed: the value is already saved, so failing the
write there would leave the reply and the disk disagreeing. **Talks to:** `Config` (set/save),
`Server` (send_to/broadcast), every hooked service.

**Restart vetoes.** `register_restart_veto(name, callable)` is the sibling of `register_guard`:
a callable returning a non-empty Finnish reason refuses a `CONFIG_RESTART` before it is armed.
`UpdateService` registers one, because the restart buttons sit three rows below the update card
and killing the backend mid-checkout is exactly what everything else there exists to prevent.
`request_restart(force=True)` skips the vetoes — the updater's own final restart IS the thing
they protect.

**Host reboot** (issue #40). `HOST_REBOOT` (`0x95`) lives here beside `CONFIG_RESTART` because it
shares its **vetoes** (`__veto_reason()`, used by both — rebooting mid-update is the same harm as
restarting mid-update) and its refusal reply (the `CONFIG_SET_RESULT` shape with an empty key, so
the Options view shows it with no new parsing — a keyless result goes to the notification pill). The backend is unprivileged, so the host must grant the right:
`__reboot()` tries `systemctl --no-ask-password reboot` (a polkit rule for
`org.freedesktop.login1.reboot*`) and then `sudo -n systemctl reboot` (a narrow sudoers entry, or
the Pi's default passwordless sudo). **Neither may prompt** — a keyboard-less panel cannot answer
one, and a hung prompt would hold the handler; with neither granted the user gets a message naming
the README section. A started reboot replies nothing, like an armed restart. Test it only with the
subprocess call stubbed: on a dev box with passwordless sudo it really reboots.
