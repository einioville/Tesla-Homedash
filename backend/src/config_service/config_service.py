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
import shutil
import struct
import time
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

# A reboot command either starts the shutdown at once or is refused at once;
# neither may ask for a password, so anything slower is a stuck call.
_REBOOT_TIMEOUT_SECONDS = 15.0


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


def _validate_spotify_device_id(value: str) -> str:
    '''
    Refuses an empty Spotify Connect device id.  Unlike myenergi.zappiSerial,
    where "" legitimately means "auto-select the first device", an empty id here
    has no meaning at all: _target_device_id never matches a playing device, so
    Spotify never claims control and every transport button silently does
    nothing — with a success toast and not one warning in the log.  That is
    precisely the failure the device scan exists to remove, so clearing the
    field (the obvious way to "reset before scanning") must not be accepted.
    Arguments:
        value (str): Candidate Spotify Connect device id.
    '''
    device_id = value.strip()
    if not device_id:
        raise ValueError("Laitetunnus ei voi olla tyhjä")
    return device_id


_VALIDATORS: dict[str, Callable[[str], str]] = {
    "timezone": _validate_timezone,
    "market": _validate_market,
    "url": _validate_url,
    "place": _validate_place,
    "spotify_device_id": _validate_spotify_device_id,
}


# ── The schema ────────────────────────────────────────────────────────────────
# Two levels. GROUPS render as sections in the Options view's left sidebar, in
# this order; each group holds SUBSECTIONS, and each subsection is one card in the
# detail pane. Labels are Finnish per the project's UI-language convention.
#
# Group ids are shared with the frontend's own bundled schema and a group present
# in both halves MERGES: "general" shows the frontend's screensaver card and this
# file's location card in one section. The frontend's schema is canonical for a
# group's order, label and icon; a group id it does not know is appended rather
# than dropped, so a new section here needs no frontend change.
#
# Per-group keys: id, label, icon, sections.
#   icon  a SEMANTIC name ("charger", "media", "price", …), not a file path — the
#         frontend maps it to one of its own resources. The backend must not name
#         a frontend asset; an unknown name falls back to the generic gear.
#
# Per-subsection keys: id, label, help (optional, shown under the card title),
#   settings.
#
# Per-setting keys:
#   key       dotted path into config.json ("myenergi.pollIntervalIdleSeconds")
#   type      bool | int | float | string | enum
#   label     Finnish row label
#   help      Finnish one-liner shown under the row (optional)
#   unit      suffix rendered after the value (optional)
#   min/max/step   numeric bounds (int/float only)
#   relevantWhen
#             {"key": <other setting>, "equals": <value>} (or "notEquals") — the
#             row is FADED, not disabled, while the rule does not hold, so a
#             setting the current toggle state makes meaningless still reads as
#             editable. May name a setting in either half. Advisory only.
#   warnBelow / warnAbove / warnMessage
#             advisory threshold: the row shows a caution when the current value
#             crosses it. Never blocks the write — min/max are the hard bounds.
#   nullable  True if the setting may be cleared to null
#   options   enum choices; "dynamic" instead means built at schema time
#   validator name in _VALIDATORS (string only)
#   editor    optional UI hint. Numeric settings render as a [-] value [+] stepper
#             by default; "slider" opts into a slider, which is only usable when
#             the exact number does not matter (a range spanning thousands of
#             steps is undraggable). None of the settings below want one — a port,
#             a tariff and a poll interval are all values you need to hit exactly.
#   guard     name of a register_guard() callable run before the write is
#             persisted; raising ValueError rejects it with a message shown to
#             the user (an audio stack that cannot switch outputs, say)
#   apply     "hook" | "restart"
#   hooks     names of apply_config() hooks to run; see ConfigService.register_hook

SETTINGS_SCHEMA: list[dict] = [
    {
        "id": "general",
        "icon": "app",
        "label": "Yleinen",
        "sections": [
            {
                "id": "location",
                "label": "Sijainti ja aika",
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
        ],
    },
    {
        "id": "media",
        "icon": "media",
        "label": "Media",
        "sections": [
            {
                "id": "radio",
                "label": "Radio",
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
                        "key": "media.autoplayRadio",
                        "type": "bool",
                        "label": "Soita radiota käynnistyksessä",
                        "help": "Oletuskanava alkaa soida, kun palvelin käynnistyy. "
                                "Pois päältä radio vain valmistellaan.",
                        "apply": "hook",
                        "hooks": ["media"],
                    },
                    {
                        "key": "media.resumeRadioAfterSpotify",
                        "type": "bool",
                        "label": "Jatka radiota Spotifyn jälkeen",
                        "help": "Kun Spotify lopettaa kesken soiton, radio jatkaa — jos "
                                "se soi Spotifyn alkaessa. Tauolle jätetty Spotify ei "
                                "käynnistä radiota myöhemmin.",
                        "apply": "hook",
                        "hooks": ["media"],
                    },
                ],
            },
            {
                "id": "spotify",
                "label": "Spotify",
                "settings": [
                    {
                        "key": "spotifyMarket",
                        "type": "string",
                        "label": "Spotify-markkina",
                        "help": "ISO-maakoodi, vaikuttaa kappaleiden saatavuuteen.",
                        "validator": "market",
                        "apply": "hook",
                        "hooks": ["spotify"],
                    },
                    {
                        # Written by the Options view's "Tunnista laite" scan
                        # (SpotifyDeviceService), which needs a legal key here to
                        # write through — the schema is the allow-list. Listing it
                        # also makes the configured id inspectable, which matters
                        # because a wrong one fails completely silently.
                        "key": "spotifyDeviceId",
                        "type": "string",
                        "label": "Spotify-laite",
                        "validator": "spotify_device_id",
                        "help": "Spotify Connect -laitteen tunnus, jolta soitto "
                                "poimitaan. Asetetaan yleensä \"Tunnista laite\" "
                                "-painikkeella; väärä tunnus ei anna virhettä vaan "
                                "saa soittimen painikkeet toimimaan tyhjää.",
                        "apply": "hook",
                        "hooks": ["spotify"],
                    },
                ],
            },
            {
                "id": "audio",
                "label": "Ääni",
                "help": "Järjestelmän äänentoisto — koskee sekä radiota että Spotifyta.",
                "settings": [
                    {
                        "key": "audio.volumePercent",
                        "type": "int",
                        "label": "Äänenvoimakkuus",
                        "help": "Järjestelmän oletuslaitteen voimakkuus.",
                        "unit": "%",
                        "min": 0,
                        "max": 100,
                        "step": 5,
                        # The exception that proves the no-sliders rule: volume is
                        # the canonical case where the exact number does not matter.
                        "editor": "slider",
                        "apply": "hook",
                        "hooks": ["audio"],
                        "guard": "audio",
                    },
                    {
                        "key": "audio.outputDevice",
                        "type": "enum",
                        "label": "Toistolaite",
                        "help": "Tyhjä = järjestelmän oma oletus. ALSA-järjestelmässä "
                                "laitetta ei voi vaihtaa ajon aikana.",
                        "options": "dynamic",
                        "apply": "hook",
                        "hooks": ["audio"],
                        "guard": "audio",
                    },
                ],
            },
        ],
    },
    {
        "id": "electricity",
        "icon": "price",
        "label": "Sähkö",
        "sections": [
            {
                "id": "pricing",
                "label": "Hinnoittelu",
                "help": "Kumpi hinnoittelu on käytössä ja millä lisillä.",
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
                        "relevantWhen": {"key": "spotPrice.enabled", "equals": True},
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
                        "relevantWhen": {"key": "spotPrice.enabled", "equals": True},
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
                        "relevantWhen": {"key": "spotPrice.enabled", "equals": True},
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
                "id": "charger",
                "label": "Laturi",
                "help": "myenergi Zappin kyselyväli ja latausistuntojen tunnistus.",
                "settings": [
                    {
                        "key": "myenergi.pollIntervalIdleSeconds",
                        "type": "int",
                        "label": "Kyselyväli, lepotila",
                        "help": "Kuinka usein Zappin tilaa kysytään lepotilassa.",
                        "unit": "s",
                        "min": 20,
                        "max": 900,
                        "step": 5,
                        "warnBelow": 60,
                        "warnMessage": ("Alle minuutin kyselyväli ruuhkauttaa myenergi-pilven: "
                                        "429-vastaukset kasvattavat odotusta entisestään."),
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
        ],
    },
    {
        "id": "tesla",
        "icon": "trip",
        "label": "Tesla",
        "sections": [
            {
                "id": "trips",
                "label": "Matkojen tunnistus",
                "help": "Milloin ajo lasketaan omaksi matkakseen.",
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
            {
                # The per-field flags of config.json's `tesla data` (issue #29).
                # Not settings: a table with its own delegate family, served by
                # tesla_service/property_editor.py over TESLA_*_PROPERTY codes,
                # so the subsection is nothing but its status widget.
                "id": "telemetryFields",
                "label": "Telemetriakentät",
                "help": "Mitkä kentät tallennetaan historiaan ja miten ne piirretään "
                        "Historia-näkymän graafiin.",
                "status": "teslaProperties",
                "settings": [],
            },
        ],
    },
    {
        "id": "maintenance",
        "icon": "system",
        "label": "Ylläpito",
        "sections": [
            {
                "id": "diagnostics",
                "label": "Vianetsintä",
                "help": "Tilapäinen yksityiskohtainen loki sekä palvelimelle että "
                        "näytölle, kun vikaa pitää selvittää ilman SSH-yhteyttä.",
                "settings": [
                    {
                        "key": "logging.debugEnabled",
                        "type": "bool",
                        "label": "Vianetsintäloki",
                        "help": "Kirjaa kaiken DEBUG-tasolla. Kytkeytyy pois itsestään "
                                "alla olevan ajan kuluttua, koska loki täyttyy muuten "
                                "nopeasti ja vanhat tapahtumat katoavat.",
                        "apply": "hook",
                        "hooks": ["logging"],
                    },
                    {
                        "key": "logging.debugMinutes",
                        "type": "int",
                        "label": "Kesto",
                        "help": "Laskenta alkaa alusta, kun lokin kytkee päälle tai "
                                "palvelin käynnistyy uudelleen.",
                        "unit": "min",
                        "min": 5,
                        "max": 240,
                        "step": 5,
                        "apply": "hook",
                        "hooks": ["logging"],
                    },
                ],
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
    "audio": "audio_config",
    "media": "media_config",
    "logging": "logging_config",
}


def _iter_settings():
    '''Yields every setting dict in the schema, flattened across groups and
    their subsections.'''
    for group in SETTINGS_SCHEMA:
        for section in group["sections"]:
            for setting in section["settings"]:
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
        # key -> zero-arg callable returning [{"value", "label"}].  Lets a service
        # own its own dynamic enum instead of __dynamic_options growing a
        # hardcoded branch per key (defaultRadioStation predates this and stays
        # as the built-in fallback).
        self.__options_providers: dict[str, Callable[[], list[dict]]] = {}
        # guard name -> callable(key, value), raising ValueError to REJECT a write
        # that could not take effect.  Distinct from a hook: a hook runs after the
        # value is already on disk and its failure is swallowed, so a guard is the
        # only place an honest "this cannot work here" reaches the user.
        self.__guards: dict[str, Callable[[str, Any], None]] = {}
        # Set by the CONFIG_RESTART handler and awaited by run(), which turns it
        # into a process exit for the service manager to restart.
        # name -> callable returning a refusal reason, or "" to allow. See
        # register_restart_veto: some restarts can only be refused honestly by
        # the service that knows what is in flight.
        self.__restart_vetoes: dict[str, Callable[[], str]] = {}
        self.__restart_requested = asyncio.Event()
        # Identifies THIS process in every schema it sends.  The frontend uses it
        # to tell "the backend restarted, so the values it now reports are the new
        # baseline" from "the socket blipped and reconnected" — a distinction the
        # schema's content cannot make, since __current_value reports what is in
        # config.json, not what each service snapshotted at construction.
        self.__started_at_ms = int(time.time() * 1000)

    # ── Wiring ────────────────────────────────────────────────────

    def register_options(self, key: str, provider: Callable[[], list[dict]]) -> None:
        '''
        Registers the enum-choice provider for one `"options": "dynamic"` setting.
        Arguments:
            key (str): Dotted setting key, e.g. "audio.outputDevice".
            provider (Callable): Returns [{"value", "label"}]; must be synchronous
                because build_schema() is.
        '''
        self.__options_providers[key] = provider

    def register_guard(self, name: str, guard: Callable[[str, Any], None]) -> None:
        '''
        Registers a pre-write guard, run after coercion and before anything is
        persisted.  Raising ValueError rejects the write and the message is shown
        to the user verbatim.
        Arguments:
            name (str): Name a setting's "guard" key refers to.
            guard (Callable): guard(key, coerced_value) -> None, raises ValueError.
        '''
        self.__guards[name] = guard

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
        enum options resolved, plus the path of the config.json being edited and
        the identity of this backend process (see __started_at_ms).
        '''
        groups = []
        for group in SETTINGS_SCHEMA:
            sections = []
            for section in group["sections"]:
                settings = []
                for setting in section["settings"]:
                    entry = {k: v for k, v in setting.items() if k != "options"}
                    entry["apply"] = self.__effective_apply(setting)
                    entry["value"] = self.__current_value(setting["key"])

                    options = setting.get("options")
                    if options == "dynamic":
                        entry["options"] = self.__dynamic_options(setting["key"])
                    elif options is not None:
                        entry["options"] = options
                    settings.append(entry)
                # Copy every subsection-level key except "settings", for the same
                # reason as the group level below.
                section_entry = {k: v for k, v in section.items() if k != "settings"}
                section_entry["settings"] = settings
                sections.append(section_entry)
            # Copy every group-level key except "sections" rather than naming
            # them one by one: a new group field (the sidebar icon was the first)
            # then reaches the frontend without touching this function.
            entry = {k: v for k, v in group.items() if k != "sections"}
            entry["sections"] = sections
            groups.append(entry)
        # The path lets the Options view name the file its remote half writes,
        # alongside the frontend's own settings file.  Top-level rather than
        # per-group: it describes the whole document, and an older frontend that
        # does not read it simply ignores the extra key.
        return {
            "path": self.__config.path,
            "startedAt": self.__started_at_ms,
            "groups": groups,
        }

    def __dynamic_options(self, key: str) -> list[dict]:
        '''
        Resolves an enum whose choices come from config rather than the schema.
        Currently only defaultRadioStation, whose choices are the configured
        radioMediaIds keys.
        Arguments:
            key (str): The setting key whose options are being built.
        '''
        provider = self.__options_providers.get(key)
        if provider is not None:
            return provider()
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

        result = await self.__write(key, value)
        if not result["ok"]:
            # The ORIGINAL value is echoed on failure, not the coerced one: the
            # frontend uses it to put back what it tried to send.
            await self.__reply_error(writer, key, value, result["message"])
            return

        await self.__reply_ok(writer, key, result["value"], result["applied"], "")
        if result["applied"] != "unchanged":
            # Tell every client (including this one) the new authoritative values.
            await self.__server.broadcast(self.__schema_frame())

    async def apply_write(self, key: str, value: Any) -> dict:
        '''
        Writes one setting exactly as a CONFIG_SET would, but on behalf of another
        backend service rather than a client — so it replies to nobody and returns
        the outcome instead.  SpotifyDeviceService uses it to store the device id
        its scan found.

        Going through here rather than touching Config directly is the point: a
        service-initiated write gets the same schema coercion, the same guard, the
        same atomic save with its .bak snapshot and rollback, the same apply hooks
        and the same schema re-broadcast that keeps every open Options view showing
        the truth.
        Arguments:
            key (str): Dotted config key; must be in SETTINGS_SCHEMA.
            value (Any): The value to write, before coercion.
        '''
        result = await self.__write(key, value)
        if result["ok"] and result["applied"] != "unchanged":
            await self.__server.broadcast(self.__schema_frame())
        return result

    async def __write(self, key: str, value: Any) -> dict:
        '''
        Validates, persists and applies one setting write, replying to nobody.
        The shared body of handle_set and apply_write; returns
        {"ok", "applied", "message", "value"} so each caller can report the
        outcome its own way.  Broadcasting the fresh schema is left to the caller,
        which is what keeps handle_set's reply-then-broadcast order intact.

        Nothing is written unless validation passes, and a failed save rolls the
        in-memory value back — the running services must never disagree with what
        is on disk.
        Arguments:
            key (str): Dotted config key; must be in SETTINGS_SCHEMA.
            value (Any): The value to write, before coercion.
        '''
        setting = next((s for s in _iter_settings() if s["key"] == key), None)
        if setting is None:
            logger.warning("CONFIG_SET for unknown key %s", key)
            return {"ok": False, "applied": "", "value": value,
                    "message": f"Tuntematon asetus: {key}"}

        try:
            coerced = self.__coerce(setting, value)
            if setting.get("options") == "dynamic":
                allowed = [o["value"] for o in self.__dynamic_options(key)]
                if coerced not in allowed:
                    raise ValueError(f"Tuntematon valinta: {coerced}")
            # Last check before anything is persisted: a guard knows whether the
            # host can actually honour this value at all.
            guard = self.__guards.get(setting.get("guard", ""))
            if guard is not None:
                guard(key, coerced)
        except ValueError as e:
            logger.info("CONFIG_SET rejected for %s: %s", key, e)
            return {"ok": False, "applied": "", "value": value, "message": str(e)}

        previous = self.__current_value(key)
        if coerced == previous:
            return {"ok": True, "applied": "unchanged", "value": coerced, "message": ""}

        self.__config.set(key, coerced)
        try:
            self.__config.save()
        except OSError as e:
            # Put the in-memory document back so services and disk stay in
            # agreement, then report the failure.
            self.__config.set(key, previous)
            logger.error("Could not save config after setting %s: %s", key, e)
            return {"ok": False, "applied": "", "value": previous,
                    "message": "Asetuksen tallennus epäonnistui"}

        applied = self.__effective_apply(setting)
        if applied == "hook":
            await self.__run_hooks(setting)

        logger.info("Config set %s = %r (%s)", key, coerced, applied)
        return {"ok": True, "applied": applied, "value": coerced, "message": ""}

    async def handle_restart(self, _payload: bytes, writer) -> None:
        '''
        CONFIG_RESTART handler: arms the restart, which run() turns into a
        process exit.  An armed restart replies nothing — the client's socket is
        about to close, so there is nothing useful to say — but a REFUSED one
        must, or the user completes a deliberate two-tap confirmation and sees
        absolutely nothing happen, which is worse than a button that visibly
        cannot be used.  The refusal is sent in the CONFIG_SET_RESULT shape, so
        the Options view renders it as an ordinary failed-write toast with no new
        parsing on that side.
        Arguments:
            _payload (bytes): Unused; the command carries no payload.
            writer (StreamWriter): The requesting client, told when it is refused.
        '''
        logger.warning("Restart requested by a client")
        refusal = self.request_restart()
        if refusal:
            logger.warning("Restart refused: %s", refusal)
            await self.__reply_error(writer, "", None, refusal)

    def register_restart_veto(self, name: str, veto: Callable[[], str]) -> None:
        '''
        Registers a pre-restart veto: a callable returning a non-empty reason to
        refuse the restart, or "" to allow it.

        The sibling of register_guard, and for the same reason — some things can
        only be refused honestly by the service that owns them.  The one that
        matters is an update in flight: this button sits three rows below the
        update card, and pressing it mid-checkout would kill the process while
        the working tree is half-moved.
        Arguments:
            name (str): Identifier for the log line.
            veto (Callable): Returns a Finnish refusal reason, or "" to allow.
        '''
        self.__restart_vetoes[name] = veto

    def request_restart(self, force: bool = False) -> str:
        '''
        Arms the restart CONFIG_RESTART arms, for a service that needs the
        backend to come back on new code — the updater, after it has rewritten
        the checkout this process is running from.  Public so there is exactly
        one way out of the process rather than a second os._exit somewhere else.

        Returns the refusal reason when a veto objected and nothing was armed.
        Arguments:
            force (bool): Skip the vetoes. For the updater's own final restart,
                which IS the thing the vetoes exist to protect.
        '''
        if not force:
            refusal = self.__veto_reason()
            if refusal:
                return refusal
        self.__restart_requested.set()
        return ""

    async def handle_reboot(self, _payload: bytes, writer) -> None:
        '''
        HOST_REBOOT handler (issue #40): reboots the whole machine.  Subject to
        the same vetoes as a restart — rebooting mid-update is the same harm as
        restarting mid-update, only worse.  A started reboot replies nothing, as
        an armed restart does; a refused one replies in the CONFIG_SET_RESULT
        shape so the Options view shows it as an ordinary toast.
        Arguments:
            _payload (bytes): Unused; the command carries no payload.
            writer (StreamWriter): The requesting client, told when it is refused.
        '''
        logger.warning("Host reboot requested by a client")
        refusal = self.__veto_reason() or await self.__reboot()
        if refusal:
            logger.warning("Host reboot refused: %s", refusal)
            await self.__reply_error(writer, "", None, refusal)

    def __veto_reason(self) -> str:
        '''
        The first restart veto's refusal reason, or "" when none objects.  A
        veto that raises is logged and skipped: a broken veto must not block.
        '''
        for name, veto in self.__restart_vetoes.items():
            try:
                refusal = veto()
            except Exception as e:  # noqa: BLE001 - a broken veto must not block
                logger.warning("Restart veto %s failed: %s", name, e)
                continue
            if refusal:
                return refusal
        return ""

    async def __reboot(self) -> str:
        '''
        Starts a host reboot, or returns why it could not.

        The backend runs unprivileged, so the right has to be granted on the
        host, and either of the two usual ways works — tried in this order:
        `systemctl reboot` through logind (a polkit rule allowing
        org.freedesktop.login1.reboot*), then `sudo -n systemctl reboot` (a
        sudoers entry for exactly that command, or the Pi's default passwordless
        sudo).  Neither may prompt: `--no-ask-password` and `sudo -n` fail at
        once instead, because a keyboard-less panel cannot answer a prompt.
        '''
        systemctl = shutil.which("systemctl")
        if systemctl is None:
            return "Laitetta ei voi käynnistää uudelleen: systemctl puuttuu"
        attempts = [[systemctl, "--no-ask-password", "reboot"]]
        if shutil.which("sudo") is not None:
            attempts.append(["sudo", "-n", systemctl, "reboot"])

        for argv in attempts:
            try:
                process = await asyncio.create_subprocess_exec(
                    *argv,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
            except OSError as e:
                logger.warning("Could not run %s: %s", " ".join(argv), e)
                continue
            try:
                _, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=_REBOOT_TIMEOUT_SECONDS
                )
            except asyncio.TimeoutError:
                process.kill()
                logger.warning("%s timed out", " ".join(argv))
                continue
            if process.returncode == 0:
                logger.warning("Host reboot started via: %s", " ".join(argv))
                return ""
            logger.info("%s refused (%s): %s", " ".join(argv), process.returncode,
                        stderr.decode("utf-8", "replace").strip())
        return ("Palvelimella ei ole oikeutta käynnistää laitetta uudelleen. Lisää "
                "polkit-sääntö tai sudoers-rivi (README: Laitteen uudelleenkäynnistys).")

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
