'''
The Järjestelmän tila service cards: how each backend service is doing.

Request/response rather than a broadcast, deliberately.  The Options view is open
a fraction of the time the dashboard is running, and polling every service for
every connected client every few seconds to feed a screen nobody is looking at
would be pure waste.  Nothing here runs until someone asks.  (The host's graphs
are system_history.py's, sampled continuously.)

Per-service health comes from duck-typed `health()` methods — the same pattern as
`stream_everything()` and `apply_config()` — so each service answers for itself
from state it already keeps, and this module knows nothing about any of them.
Beside the verdict a probe may return its settings in effect (`config`, label /
value pairs) and a list (`items`, the connected clients); each row also gets the
warning and error counts of the loggers its probe claims, from the persistent
ErrorLog, whose entries SYSTEM_GET_LOG lists per card.  The document also carries
the host's uptime and the backend's own, for the overview above the graphs.
'''

import asyncio
import inspect
import logging
import time
from typing import Any, Callable

from ..utils import protocol
from . import system_metrics

logger = logging.getLogger("system_service")

# A wedged probe (InfluxDB's awaits a real ping) must not hang the whole reply.
_PROBE_TIMEOUT_SECONDS = 2.0
# The most entries one card's list sends; the store keeps up to 2000 in all.
_LOG_LIST_LIMIT = 500


class SystemStatusService:
    '''
    Serves SYSTEM_GET_STATUS by polling every registered service probe, and
    SYSTEM_GET_LOG from the persistent warning/error store.

    Deliberately NOT registered with Server.register_service: a status page
    nobody has opened is not worth polling for every connecting client.
    Arguments:
        server (Server): TCP server, used only to reply to the requesting client.
        error_log (ErrorLog): The persistent WARNING+ store from
            logger_configurator, read for the per-card counts and lists.
    '''

    def __init__(self, server, error_log):
        self.__server = server
        self.__errors = error_log
        # The backend's uptime runs on the monotonic clock: the Pi has no RTC and
        # steps its wall clock when NTP first answers, which would make "now
        # minus the start time" anything at all.  Built at startup, so close
        # enough to the process's own start.
        self.__started_monotonic = time.monotonic()
        # probe id -> (Finnish label, callable returning a health dict, logger
        # name prefixes whose warnings and errors are this card's)
        self.__probes: dict[str, tuple[str, Callable[[], Any], tuple[str, ...]]] = {}
        # The probe that answers for every logger no other probe claims, so no
        # warning is ever invisible.
        self.__catch_all: str | None = None

    # ── Wiring ────────────────────────────────────────────────────

    def register_probe(self, probe_id: str, label: str, probe: Callable[[], Any],
                       loggers: tuple[str, ...] = (), catch_all: bool = False) -> None:
        '''
        Registers one service's health probe.
        Arguments:
            probe_id (str): Stable id used as the row key.
            label (str): Finnish row label for the status view.
            probe (Callable): Returns a dict with "state" ("ok"/"warn"/"error"/
                "off") and optionally "detail", "config" ([[label, value]], the
                settings in effect, as display strings) and "items"; may be async.
            loggers (tuple[str, ...]): Logger names (prefixes, matched at a dot)
                whose warnings and errors this card counts and lists.
            catch_all (bool): This card also takes every logger no other probe
                claims.
        '''
        self.__probes[probe_id] = (label, probe, tuple(loggers))
        if catch_all:
            self.__catch_all = probe_id

    # ── Protocol handler ──────────────────────────────────────────

    async def handle_get_status(self, _payload: bytes, writer) -> None:
        '''
        SYSTEM_GET_STATUS handler: polls the probes and replies to the requesting
        client only.  Any failure still produces a reply, so the view
        never hangs waiting for one.
        Arguments:
            _payload (bytes): Unused; the request carries no body.
            writer (StreamWriter): The requesting client.
        '''
        try:
            document = await self.__build()
            status = protocol.CONFIG_STATUS_OK
        except Exception as e:
            logger.error("Could not build system status: %s", e)
            document = {}
            status = protocol.CONFIG_STATUS_ERROR

        await self.__server.send_to(
            writer, protocol.json_frame(protocol.SYSTEM_STATUS, status, document))

    async def handle_get_log(self, payload: bytes, writer) -> None:
        '''
        SYSTEM_GET_LOG handler: one card's warnings and errors, newest first, to
        the requesting client only.
        Arguments:
            payload (bytes): len(4B) + JSON {"service": <probe id>}.
            writer (StreamWriter): The requesting client.
        '''
        try:
            service = str(protocol.parse_json_body(payload).get("service", ""))
        except ValueError:
            service = ""
        probe = self.__probes.get(service)
        if probe is None:
            document = {"service": service, "label": "", "entries": []}
            status = protocol.CONFIG_STATUS_ERROR
        else:
            entries = self.__errors.entries(self.__matcher(service))
            document = {"service": service, "label": probe[0],
                        "entries": entries[:_LOG_LIST_LIMIT]}
            status = protocol.CONFIG_STATUS_OK
        await self.__server.send_to(
            writer, protocol.json_frame(protocol.SYSTEM_LOG, status, document))

    # ── Internals ─────────────────────────────────────────────────

    @staticmethod
    def __claims(prefixes: tuple[str, ...], name: str) -> bool:
        '''Whether a logger name is one of the prefixes or below one of them.'''
        return any(name == p or name.startswith(p + ".") for p in prefixes)

    def __matcher(self, probe_id: str) -> Callable[[str], bool]:
        '''
        The logger test for one card: its own prefixes, plus — for the catch-all
        card — every name no other card claims.
        Arguments:
            probe_id (str): The card.
        '''
        own = self.__probes[probe_id][2]
        if probe_id != self.__catch_all:
            return lambda name: self.__claims(own, name)
        others = tuple(p for pid, (_, _, prefixes) in self.__probes.items()
                       if pid != probe_id for p in prefixes)
        return lambda name: self.__claims(own, name) or not self.__claims(others, name)

    async def __build(self) -> dict:
        '''Polls every probe and assembles the document.'''
        return {
            "services": await self.__collect_services(),
            "sampled_ms": int(time.time() * 1000),
            "uptime_s": system_metrics.read_uptime_seconds(),
            "backend_uptime_s": time.monotonic() - self.__started_monotonic,
        }

    async def __collect_services(self) -> list[dict]:
        '''
        Runs every registered probe.  A probe that raises or hangs is reported as
        one broken service, never as a failed request — the point of the view is
        to show what is wrong, so it has to survive things being wrong.
        '''
        rows = []
        for probe_id, (label, probe, _loggers) in self.__probes.items():
            try:
                result = probe()
                if inspect.isawaitable(result):
                    result = await asyncio.wait_for(result, _PROBE_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                result = {"state": "error", "detail": "Ei vastausta"}
            except Exception as e:
                result = {"state": "error", "detail": f"{type(e).__name__}: {e}"}
            if not isinstance(result, dict):
                result = {"state": "off"}
            rows.append({"id": probe_id, "label": label, **result,
                         "errors": self.__errors.counts(self.__matcher(probe_id))})
        return rows
