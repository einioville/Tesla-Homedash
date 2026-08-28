'''
Runtime configuration service — the backend half of the frontend's Options view.

Serves the CONFIG_* protocol codes (0x90-0x94): it publishes a *schema* of the
settings in config.json that are safe to change at runtime, validates incoming
writes against it, persists them, and applies them to the running services.

Why a schema rather than "let the frontend write any key": config.json also holds
structural data the rest of the stack mirrors (the `tesla data` property table is
duplicated in the frontend's TeslaData registry and in the graph-property wire
format), so a write-anything endpoint would let the dashboard desync itself from
the backend at runtime. The schema is the allow-list, and it doubles as the
frontend's UI description — label, type, bounds — so adding a tunable is one entry
here and no frontend change at all.

**Apply tiers.** Every service snapshots the values it needs into instance
attributes in its constructor and never re-reads Config, so mutating Config alone
changes nothing. Each editable setting therefore declares how it reaches the
running system:

  "hook"    — the owning service exposes apply_config(), which re-snapshots (and
              reschedules / refetches where that is needed). Applied immediately.
  "restart" — no safe live path: the value is consumed once at construction to
              build something that cannot be rebuilt in place (APScheduler cron
              jobs from timeZone, the resolved Zappi from zappiSerial, whether
              SpotPriceService has a run task at all from spotPrice.enabled).
              Written to config.json and picked up on the next process start.

A "hook" setting whose service is absent (no Zappi configured -> no
MyEnergiService) is reported back as "restart", because that is what it actually
is for that deployment.
'''
import asyncio
import json
import logging
import os
import struct
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..utils import protocol

logger = logging.getLogger("config_service.config_service")

# Exit code used when the Options view asks for a restart. Deliberately NON-ZERO
# so a systemd unit with the repo's default `Restart=on-failure` restarts the
# process too — `Restart=always` is nicer (it also covers a clean shutdown) but is
# not required for the Options view's restart button to work.
RESTART_EXIT_CODE = 42

# Grace period between arming the restart and killing the process, so the reply
# that preceded it reaches the client instead of dying in the socket buffer.
_RESTART_DRAIN_SECONDS = 0.25


# ── Value validators ──────────────────────────────────────────────────────────
# Each returns the coerced value, or raises ValueError with a message shown
# verbatim in the frontend. Referenced by name from the schema's "validator" key.

def _validate_timezone(value: str) -> str:
    '''
    Checks that a string is a resolvable IANA timezone.  This is the single most
    important validator in the file: an unresolvable zone makes Config.__init__
    raise, and because timeZone is a restart-tier setting the process would be
    told to restart straight into that failure — a restart loop.  Rejecting here
    means the bad value is never written.
    Arguments:
        value (str): Candidate IANA zone name, e.g. "Europe/Helsinki".
    '''
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise ValueError(f"Tuntematon aikavyöhyke: {value!r}") from e
    return value


def _validate_market(value: str) -> str:
    '''
    Checks an ISO 3166-1 alpha-2 country code for the Spotify market.
    Arguments:
        value (str): Candidate two-letter country code, e.g. "FI".
    '''
    code = value.strip().upper()
    if len(code) != 2 or not code.isalpha():
        raise ValueError("Maakoodin on oltava kaksi kirjainta (esim. FI)")
    return code


def _validate_url(value: str) -> str:
    '''
    Checks that a string looks like an http(s) endpoint.  Not a full URL parse —
    just enough to stop an obvious typo being written and silently breaking the
    next price fetch.
    Arguments:
        value (str): Candidate base URL.
    '''
    url = value.strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError("Osoitteen on alettava http:// tai https://")
    return url


def _validate_place(value: str) -> str:
    '''
    Checks a non-empty FMI place name.  FMI itself decides whether the place
    resolves; an unknown one makes the fetch return nothing, which the service
    already treats as a failed cycle (it keeps the previous forecast).
    Arguments:
        value (str): Candidate place name, e.g. "Tampere".
    '''
    place = value.strip()
    if not place:
        raise ValueError("Paikkakunta ei voi olla tyhjä")
    return place


_VALIDATORS: dict[str, Callable[[str], str]] = {
    "timezone": _validate_timezone,
    "market": _validate_market,
    "url": _validate_url,
    "place": _validate_place,
}


# ── The schema ────────────────────────────────────────────────────────────────
# Groups render as SECTIONS in the Options view's left sidebar, in this order —
# one sidebar entry per group, its settings filling the detail pane. Labels are
# Finnish per the project's UI-language convention.
#
# Per-group keys: id, label, icon, settings.
#   icon  a SEMANTIC name ("charger", "media", "price", …), not a file path — the
#         frontend maps it to one of its own resources. The backend must not name
#         a frontend asset; an unknown name falls back to the generic gear.
#
# Per-setting keys:
#   key       dotted path into config.json ("myenergi.pollIntervalIdleSeconds")
#   type      bool | int | float | string | enum
#   label     Finnish row label
#   help      Finnish one-liner shown under the row (optional)
#   unit      suffix rendered after the value (optional)
#   min/max/step   numeric bounds (int/float only)
#   nullable  True if the setting may be cleared to null
#   options   enum choices; "dynamic" instead means built at schema time
#   validator name in _VALIDATORS (string only)
#   editor    optional UI hint. Numeric settings render as a [-] value [+] stepper
#             by default; "slider" opts into a slider, which is only usable when
#             the exact number does not matter (a range spanning thousands of
#             steps is undraggable). None of the settings below want one — a port,
#             a tariff and a poll interval are all values you need to hit exactly.
#   apply     "hook" | "restart"
#   hooks     names of apply_config() hooks to run; see ConfigService.register_hook

SETTINGS_SCHEMA: list[dict] = [
    {
        "id": "general",
        "icon": "gear",
        "label": "Yleiset",
        "settings": [
            {
                "key": "weatherPlace",
                "type": "string",
                "label": "Sääpaikkakunta",
                "help": "Ilmatieteen laitoksen havainto- ja ennustepaikka.",
                "validator": "place",
                "apply": "hook",
                "hooks": ["weather"],
            },
            {
                "key": "timeZone",
                "type": "string",
                "label": "Aikavyöhyke",
                "help": "IANA-tunnus, esim. Europe/Helsinki.",
                "validator": "timezone",
                "apply": "restart",
                "hooks": [],
            },
        ],
    },
    {
        "id": "media",
        "icon": "media",
        "label": "Media",
        "settings": [
            {
                "key": "defaultRadioStation",
                "type": "enum",
                "label": "Oletusradiokanava",
                "help": "Kanava, jolle radio palaa Spotifyn lopetettua.",
                "options": "dynamic",
                "apply": "hook",
                "hooks": ["radio"],
            },
            {
                "key": "spotifyMarket",
                "type": "string",
                "label": "Spotify-markkina",
                "help": "ISO-maakoodi, vaikuttaa kappaleiden saatavuuteen.",
                "validator": "market",
                "apply": "hook",
                "hooks": ["spotify"],
            },
        ],
    },
    {
        "id": "charger",
        "icon": "charger",
        "label": "Laturi",
        "settings": [
            {
                "key": "myenergi.pollIntervalIdleSeconds",
                "type": "int",
                "label": "Kyselyväli, lepotila",
                "help": "Alle 20 s ruuhkauttaa myenergi-pilven (429).",
                "unit": "s",
                "min": 20,
                "max": 900,
                "step": 5,
                "apply": "hook",
                "hooks": ["myenergi"],
            },
            {
                "key": "myenergi.pollIntervalActiveSeconds",
                "type": "int",
                "label": "Kyselyväli, lataus käynnissä",
                "unit": "s",
                "min": 10,
                "max": 600,
                "step": 5,
                "apply": "hook",
                "hooks": ["myenergi"],
            },
            {
                "key": "myenergi.minSessionEnergyKwh",
                "type": "float",
                "label": "Latauksen vähimmäisenergia",
                "help": "Tätä pienemmät latausistunnot jätetään listalta pois.",
                "unit": "kWh",
                "min": 0.0,
                "max": 20.0,
                "step": 0.1,
                "apply": "hook",
                "hooks": ["charging"],
            },
            {
                "key": "myenergi.sessionMergeMinutes",
                "type": "int",
                "label": "Istuntojen yhdistysväli",
                "help": "Tätä lyhyempi tauko ei katkaise latausistuntoa.",
                "unit": "min",
                "min": 0,
                "max": 120,
                "step": 1,
                "apply": "hook",
                "hooks": ["charging"],
            },
            {
                "key": "myenergi.zappiSerial",
                "type": "string",
                "label": "Zappin sarjanumero",
                "help": "Tyhjä = valitse tilin ensimmäinen Zappi.",
                "apply": "restart",
                "hooks": [],
            },
        ],
    },
    {
        "id": "pricing",
        "icon": "price",
        "label": "Sähkön hinta",
        "settings": [
            {
                "key": "spotPrice.enabled",
                "type": "bool",
                "label": "Pörssisähkön hinnoittelu",
                "help": "Pois päältä = kiinteä hinta alla.",
                "apply": "restart",
                "hooks": [],
            },
            {
                "key": "spotPrice.vatPercent",
                "type": "float",
                "label": "Arvonlisävero",
                "unit": "%",
                "min": 0.0,
                "max": 100.0,
                "step": 0.5,
                "apply": "hook",
                "hooks": ["spot_price"],
            },
            {
                "key": "spotPrice.marginCentsPerKwh",
                "type": "float",
                "label": "Myyjän marginaali",
                "help": "Lisätään pörssihintaan ennen alv:tä.",
                "unit": "c/kWh",
                "min": 0.0,
                "max": 20.0,
                "step": 0.05,
                "apply": "hook",
                "hooks": ["spot_price"],
            },
            {
                "key": "spotPrice.baseUrl",
                "type": "string",
                "label": "Hintalähde",
                "help": "sähkötin.fi-yhteensopiva rajapinta.",
                "validator": "url",
                "apply": "hook",
                "hooks": ["spot_price"],
            },
            {
                "key": "electricityPriceEurPerKwh",
                "type": "float",
                "label": "Kiinteä sähkön hinta",
                "help": "Varahinta tunneille, joille ei saada pörssihintaa.",
                "unit": "€/kWh",
                "min": 0.0,
                "max": 2.0,
                "step": 0.001,
                "nullable": True,
                "apply": "hook",
                "hooks": ["charging"],
            },
        ],
    },
    {
        "id": "trips",
        "icon": "trip",
        "label": "Matkat",
        "settings": [
            {
                "key": "trip.min_stop_minutes",
                "type": "int",
                "label": "Pysähdyksen vähimmäiskesto",
                "help": "Tätä lyhyempi pysäköinti ei katkaise matkaa.",
                "unit": "min",
                "min": 1,
                "max": 180,
                "step": 1,
                "apply": "hook",
                "hooks": ["trip"],
            },
            {
                "key": "trip.min_trip_distance_km",
                "type": "float",
                "label": "Matkan vähimmäispituus",
                "help": "Tätä lyhyemmät ajot jätetään listalta pois.",
                "unit": "km",
                "min": 0.0,
                "max": 50.0,
                "step": 0.1,
                "apply": "hook",
                "hooks": ["trip"],
            },
        ],
    },
]

# Dotted-path prefix -> the Config accessor that merges that optional block over
# its defaults. Reading through these means the Options view shows the value
# actually in EFFECT, not null, for a block the real config.json omits.
_MERGED_BLOCKS = {
    "trip": "trip_config",
    "myenergi": "myenergi_config",
    "spotPrice": "spot_price_config",
}


def _iter_settings():
    '''Yields every setting dict in the schema, flattened across groups.'''
    for group in SETTINGS_SCHEMA:
        for setting in group["settings"]:
            yield setting


class ConfigService:
    '''
    Serves the CONFIG_* protocol codes: publishes the editable-settings schema,
    validates and persists writes, applies them through per-service hooks, and
    carries the restart request the Options view can raise.

    Registered with the Server both as a handler target (register_handler) and as
    a snapshot source (register_service), so a connecting frontend receives the
    schema without asking.
    Arguments:
        config (Config): Shared in-memory configuration; mutated and saved here.
        server (Server): TCP server used for send_to / broadcast.
    '''

    def __init__(self, config, server):
        self.__config = config
        self.__server = server
        # hook name -> callable. Populated by start_services once every service
        # exists; a name with no registration downgrades its settings to
        # "restart" in both the schema and the write result.
        self.__hooks: dict[str, Callable[[], Any]] = {}
        # Set by the CONFIG_RESTART handler and awaited by run(), which turns it
        # into a process exit for the service manager to restart.
        self.__restart_requested = asyncio.Event()

    # ── Wiring ────────────────────────────────────────────────────

    def register_hook(self, name: str, hook: Callable[[], Any]) -> None:
        '''
        Registers one service's apply_config() under the name the schema uses.
        Arguments:
            name (str): Hook name as it appears in a setting's "hooks" list.
            hook (Callable): Zero-argument callable; may return an awaitable.
        '''
        self.__hooks[name] = hook
        logger.debug("Registered config hook: %s", name)

    # ── Schema + values ───────────────────────────────────────────

    def __current_value(self, key: str) -> Any:
        '''
        Reads the value currently in effect for a dotted key.  Optional blocks
        are read through their merged Config accessor so an omitted block reports
        its default rather than null.
        Arguments:
            key (str): Dotted path into the config document.
        '''
        if "." in key:
            prefix, leaf = key.split(".", 1)
            accessor = _MERGED_BLOCKS.get(prefix)
            if accessor is not None:
                return getattr(self.__config, accessor).get(leaf)
            block = self.__config.get(prefix) or {}
            return block.get(leaf)
        return self.__config.get(key)

    def __effective_apply(self, setting: dict) -> str:
        '''
        Returns the apply tier this setting really has in THIS deployment: a
        "hook" setting whose hooks are all unregistered (e.g. no Zappi, so no
        MyEnergiService) is genuinely restart-tier, and saying so keeps the
        Options view honest rather than claiming a change took effect.
        Arguments:
            setting (dict): One schema setting entry.
        '''
        if setting["apply"] != "hook":
            return setting["apply"]
        if any(name in self.__hooks for name in setting.get("hooks", ())):
            return "hook"
        return "restart"

    def build_schema(self) -> dict:
        '''
        Builds the JSON document sent as CONFIG_SCHEMA: the static schema with
        each setting's current value, its effective apply tier, and any dynamic
        enum options resolved.
        '''
        groups = []
        for group in SETTINGS_SCHEMA:
            settings = []
            for setting in group["settings"]:
                entry = {k: v for k, v in setting.items() if k != "options"}
                entry["apply"] = self.__effective_apply(setting)
                entry["value"] = self.__current_value(setting["key"])

                options = setting.get("options")
                if options == "dynamic":
                    entry["options"] = self.__dynamic_options(setting["key"])
                elif options is not None:
                    entry["options"] = options
                settings.append(entry)
            # Copy every group-level key except "settings" rather than naming
            # them one by one: a new group field (the sidebar icon was the first)
            # then reaches the frontend without touching this function.
            entry = {k: v for k, v in group.items() if k != "settings"}
            entry["settings"] = settings
            groups.append(entry)
        return {"groups": groups}

    def __dynamic_options(self, key: str) -> list[dict]:
        '''
        Resolves an enum whose choices come from config rather than the schema.
        Currently only defaultRadioStation, whose choices are the configured
        radioMediaIds keys.
        Arguments:
            key (str): The setting key whose options are being built.
        '''
        if key == "defaultRadioStation":
            return [
                {"value": name, "label": name}
                for name in self.__config.radio_media_ids.keys()
            ]
        logger.warning("No dynamic options builder for %s", key)
        return []

    # ── Validation ────────────────────────────────────────────────

    @staticmethod
    def __coerce(setting: dict, value: Any) -> Any:
        '''
        Validates and coerces an incoming JSON value against one schema entry.
        Raises ValueError with a Finnish message the frontend shows verbatim.
        Arguments:
            setting (dict): The schema entry the value is being written to.
            value (Any): The JSON-decoded value from the CONFIG_SET payload.
        '''
        if value is None:
            if setting.get("nullable"):
                return None
            raise ValueError("Arvo ei voi olla tyhjä")

        kind = setting["type"]

        if kind == "bool":
            if not isinstance(value, bool):
                raise ValueError("Odotettiin tosi/epätosi-arvoa")
            return value

        if kind in ("int", "float"):
            # bool is a subclass of int in Python; reject it explicitly so a
            # stray true does not silently become 1.
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("Odotettiin numeroa")
            number = int(value) if kind == "int" else float(value)
            if kind == "int" and float(value) != number:
                raise ValueError("Odotettiin kokonaislukua")
            low, high = setting.get("min"), setting.get("max")
            if low is not None and number < low:
                raise ValueError(f"Arvon on oltava vähintään {low}")
            if high is not None and number > high:
                raise ValueError(f"Arvon on oltava enintään {high}")
            return number

        if kind == "string":
            if not isinstance(value, str):
                raise ValueError("Odotettiin tekstiä")
            validator = _VALIDATORS.get(setting.get("validator", ""))
            return validator(value) if validator else value.strip()

        if kind == "enum":
            # Dynamic options are not in the static schema, so membership is
            # checked by the caller (which has the resolved list).
            if not isinstance(value, str):
                raise ValueError("Odotettiin tekstiä")
            return value

        raise ValueError(f"Tuntematon asetustyyppi: {kind}")

    # ── Handlers ──────────────────────────────────────────────────

    async def handle_get_schema(self, _payload: bytes, writer) -> None:
        '''
        CONFIG_GET_SCHEMA handler: replies with the schema to the requesting
        client only.
        Arguments:
            _payload (bytes): Unused; the request carries no payload.
            writer (StreamWriter): The requesting client.
        '''
        await self.__server.send_to(writer, self.__schema_frame())

    async def handle_set(self, payload: bytes, writer) -> None:
        '''
        CONFIG_SET handler: validates one {"key", "value"} write against the
        schema, persists it, applies it through the setting's hooks, and replies
        to the requesting client.  A successful write also broadcasts the fresh
        schema so any other connected frontend updates its displayed values.

        Nothing is written unless validation passes, and a failed save rolls the
        in-memory value back — the running services must never disagree with what
        is on disk.
        Arguments:
            payload (bytes): len(4B) + UTF-8 JSON request body.
            writer (StreamWriter): The requesting client.
        '''
        try:
            key, value = self.__parse_set_payload(payload)
        except ValueError as e:
            logger.warning("Malformed CONFIG_SET: %s", e)
            await self.__reply_error(writer, "", None, str(e))
            return

        setting = next((s for s in _iter_settings() if s["key"] == key), None)
        if setting is None:
            logger.warning("CONFIG_SET for unknown key %s", key)
            await self.__reply_error(writer, key, value, f"Tuntematon asetus: {key}")
            return

        try:
            coerced = self.__coerce(setting, value)
            if setting.get("options") == "dynamic":
                allowed = [o["value"] for o in self.__dynamic_options(key)]
                if coerced not in allowed:
                    raise ValueError(f"Tuntematon valinta: {coerced}")
        except ValueError as e:
            logger.info("CONFIG_SET rejected for %s: %s", key, e)
            await self.__reply_error(writer, key, value, str(e))
            return

        previous = self.__current_value(key)
        if coerced == previous:
            await self.__reply_ok(writer, key, coerced, "unchanged", "")
            return

        self.__config.set(key, coerced)
        try:
            self.__config.save()
        except OSError as e:
            # Put the in-memory document back so services and disk stay in
            # agreement, then report the failure.
            self.__config.set(key, previous)
            logger.error("Could not save config after setting %s: %s", key, e)
            await self.__reply_error(
                writer, key, value, "Asetuksen tallennus epäonnistui"
            )
            return

        applied = self.__effective_apply(setting)
        if applied == "hook":
            await self.__run_hooks(setting)

        logger.info("Config set %s = %r (%s)", key, coerced, applied)
        await self.__reply_ok(writer, key, coerced, applied, "")
        # Tell every client (including this one) the new authoritative values.
        await self.__server.broadcast(self.__schema_frame())

    async def handle_restart(self, _payload: bytes, _writer) -> None:
        '''
        CONFIG_RESTART handler: arms the restart, which run() turns into a
        process exit.  Fire-and-forget — the client's socket is about to close,
        so there is nothing useful to reply.
        Arguments:
            _payload (bytes): Unused; the command carries no payload.
            _writer (StreamWriter): Unused.
        '''
        logger.warning("Restart requested by a client")
        self.__restart_requested.set()

    # ── Snapshot + run task ───────────────────────────────────────

    async def stream_everything(self, writer) -> None:
        '''
        On-connect snapshot: sends the schema so the Options view is populated
        without an explicit request.  Duck-typed interface used by
        Server.register_service.
        Arguments:
            writer (StreamWriter): The newly connected client.
        '''
        await self.__server.send_to(writer, self.__schema_frame())

    async def run(self) -> None:
        '''
        Waits for a restart request and turns it into a process exit.  Without a
        request this coroutine never returns, so gathering it unconditionally in
        start_services.main is harmless.

        The exit is deliberately immediate (os._exit) rather than a raised
        SystemExit.  SystemExit from a gathered task is not stored on the task —
        asyncio propagates it through the runner's own teardown, which prints a
        full traceback plus "Task exception was never retrieved" before exiting.
        That is misleading noise in the journal for what is an intentional,
        user-requested restart, and the journal is the only forensics this
        deployment has.  Logging handlers are flushed first because os._exit
        skips atexit and buffered writes.

        _RESTART_DRAIN_SECONDS gives the event loop a moment to flush pending
        socket writes (the CONFIG_SET_RESULT that preceded the request) before
        the process disappears.
        '''
        await self.__restart_requested.wait()
        await asyncio.sleep(_RESTART_DRAIN_SECONDS)
        logger.warning(
            "Exiting with code %s so the service manager restarts the backend",
            RESTART_EXIT_CODE,
        )
        for handler in logging.getLogger().handlers + logger.handlers:
            try:
                handler.flush()
            except Exception:  # noqa: BLE001 - never block the restart on logging
                pass
        os._exit(RESTART_EXIT_CODE)

    def get_run_task(self):
        '''Returns the restart-watch task, mirroring the other services' API.'''
        return asyncio.create_task(self.run())

    # ── Internals ─────────────────────────────────────────────────

    @staticmethod
    def __parse_set_payload(payload: bytes) -> tuple[str, Any]:
        '''
        Unpacks a CONFIG_SET body: len(4B) + UTF-8 JSON {"key", "value"}.
        Arguments:
            payload (bytes): The raw payload after the message-type byte.
        '''
        if len(payload) < 4:
            raise ValueError("Vaillinainen pyyntö")
        (length,) = struct.unpack("!I", payload[:4])
        body = payload[4:4 + length]
        if len(body) != length:
            raise ValueError("Vaillinainen pyyntö")
        try:
            request = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ValueError("Virheellinen JSON") from e
        if not isinstance(request, dict) or "key" not in request:
            raise ValueError("Pyynnöstä puuttuu avain")
        return str(request["key"]), request.get("value")

    async def __run_hooks(self, setting: dict) -> None:
        '''
        Runs the registered apply_config() hooks for one setting.  A hook that
        raises is logged and swallowed: the value is already saved, so failing
        the whole write here would leave disk and reply disagreeing.
        Arguments:
            setting (dict): The schema entry whose hooks should run.
        '''
        for name in setting.get("hooks", ()):
            hook = self.__hooks.get(name)
            if hook is None:
                continue
            try:
                result = hook()
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:  # noqa: BLE001 - a hook must not break the write
                logger.error("Config hook %s failed: %s", name, e)

    def __schema_frame(self) -> bytes:
        '''Builds a framed CONFIG_SCHEMA packet from the current schema+values.'''
        try:
            body = json.dumps(self.build_schema(), ensure_ascii=False).encode("utf-8")
        except (TypeError, ValueError) as e:
            logger.error("Could not serialize settings schema: %s", e)
            return protocol.frame(
                protocol.CONFIG_SCHEMA,
                bytes((protocol.CONFIG_STATUS_ERROR,)) + struct.pack("!I", 0),
            )
        return protocol.frame(
            protocol.CONFIG_SCHEMA,
            bytes((protocol.CONFIG_STATUS_OK,)) + struct.pack("!I", len(body)) + body,
        )

    @staticmethod
    def __result_frame(status: int, key: str, value: Any, applied: str, message: str) -> bytes:
        '''
        Builds a framed CONFIG_SET_RESULT packet.
        Arguments:
            status (int): protocol.CONFIG_STATUS_OK or _ERROR.
            key (str): The key the write targeted (echoed so a stale reply is
                discardable).
            value (Any): The value now in effect for that key.
            applied (str): "hook", "restart" or "unchanged".
            message (str): Human-readable failure reason, empty on success.
        '''
        body = json.dumps(
            {"key": key, "value": value, "applied": applied, "message": message},
            ensure_ascii=False,
        ).encode("utf-8")
        return protocol.frame(
            protocol.CONFIG_SET_RESULT,
            bytes((status,)) + struct.pack("!I", len(body)) + body,
        )

    async def __reply_ok(self, writer, key: str, value: Any, applied: str, message: str) -> None:
        '''Sends a successful CONFIG_SET_RESULT to the requesting client.'''
        await self.__server.send_to(
            writer,
            self.__result_frame(protocol.CONFIG_STATUS_OK, key, value, applied, message),
        )

    async def __reply_error(self, writer, key: str, value: Any, message: str) -> None:
        '''Sends a rejected CONFIG_SET_RESULT to the requesting client.'''
        await self.__server.send_to(
            writer,
            self.__result_frame(protocol.CONFIG_STATUS_ERROR, key, value, "", message),
        )
