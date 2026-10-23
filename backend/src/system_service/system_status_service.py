'''
The Järjestelmän tila service cards: how each backend service is doing.

Request/response, and deliberately not register_service'd: the Options view is
open a fraction of the time, and polling every service for every connected client
to feed a screen nobody is looking at would be pure waste.  Nothing here runs
until someone asks.  (The host's graphs are system_history.py's, sampled
continuously.)

Each card is a service's duck-typed `health()` probe (register_probe() has the
contract), plus the warning and error counts of the loggers it claims, from the
persistent ErrorLog: the open ones, logged since the service last worked, and the
past ones, which it has worked since.  The document also carries the host's
uptime and the backend's own, for the overview above the graphs.
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
# How far back a card counts its past warnings and errors; its list holds them
# all, back to the last full clear.
_PAST_WINDOW_MS = 24 * 3600 * 1000


class SystemStatusService:
    '''
    Serves SYSTEM_GET_STATUS by polling every registered service probe, and
    SYSTEM_GET_LOG from the persistent warning/error store.
    Arguments:
        server (Server): TLS server, used only to reply to the requesting client.
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
        # Where a failing card with no last good cycle opens its entries: this
        # run's.  Wall clock, as the entries' times are.
        self.__started_ms = int(time.time() * 1000)
        # probe id -> (Finnish label, callable returning a health dict, logger
        # name prefixes whose warnings and errors are this card's)
        self.__probes: dict[str, tuple[str, Callable[[], Any], tuple[str, ...]]] = {}
        # The probe that answers for every logger no other probe claims, so no
        # warning is ever invisible.
        self.__catch_all: str | None = None
        # probe id -> (state, last_ok_ms) from its latest run, for SYSTEM_GET_LOG,
        # which is asked for from a card a status reply has just drawn.
        self.__latest: dict[str, tuple[str, int | None]] = {}

    def register_probe(self, probe_id: str, label: str, probe: Callable[[], Any],
                       loggers: tuple[str, ...] = (), catch_all: bool = False) -> None:
        '''
        Registers one service's health probe.
        Arguments:
            probe_id (str): Stable id used as the row key.
            label (str): Finnish row label for the status view.
            probe (Callable): Returns a dict with "state" ("ok"/"warn"/"error"/
                "off") and optionally "detail", "config" ([[label, value]], the
                settings in effect: a value is a display string or a {time} /
                {bytes} / {duration} object the frontend formats), "items" and
                "last_ok_ms" (epoch ms of the service's last good cycle, where
                it has one; the card's open entries begin there while it fails);
                may be async.
            loggers (tuple[str, ...]): Logger names (prefixes, matched at a dot)
                whose warnings and errors this card counts and lists.
            catch_all (bool): This card also takes every logger no other probe
                claims.
        '''
        self.__probes[probe_id] = (label, probe, tuple(loggers))
        if catch_all:
            self.__catch_all = probe_id

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
            document = {"service": service, "label": "", "open_since": None, "entries": []}
            status = protocol.CONFIG_STATUS_ERROR
        else:
            if service not in self.__latest:
                await self.__run_probe(service, probe[1])
            open_since = self.__open_since(*self.__latest[service])
            # Copies: the store's own dicts must not take the flag.
            entries = [{**entry, "open": open_since is not None and entry["t"] >= open_since}
                       for entry in self.__errors.entries(self.__matcher(service))[:_LOG_LIST_LIMIT]]
            document = {"service": service, "label": probe[0],
                        "open_since": open_since, "entries": entries}
            status = protocol.CONFIG_STATUS_OK
        await self.__server.send_to(
            writer, protocol.json_frame(protocol.SYSTEM_LOG, status, document))

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

    def __open_since(self, state: str, last_ok_ms: int | None) -> int | None:
        '''
        Where a card's open warnings and errors begin, or None when it has none.
        A card that is fine as it stands (ok, off) has nothing open, whatever it
        logged before; a failing one has everything since it last worked, or,
        with no last good cycle to go by, everything since this backend started.
        Arguments:
            state (str): The probe's state.
            last_ok_ms (int | None): The probe's last good cycle, if it reports one.
        '''
        if state not in ("warn", "error"):
            return None
        return last_ok_ms if last_ok_ms is not None else self.__started_ms

    async def __build(self) -> dict:
        '''Polls every probe and assembles the document.'''
        return {
            "services": await self.__collect_services(),
            "sampled_ms": int(time.time() * 1000),
            "uptime_s": system_metrics.read_uptime_seconds(),
            "backend_uptime_s": time.monotonic() - self.__started_monotonic,
        }

    async def __collect_services(self) -> list[dict]:
        '''Runs every registered probe, in card order.'''
        rows = []
        past_since = int(time.time() * 1000) - _PAST_WINDOW_MS
        for probe_id, (label, probe, _loggers) in self.__probes.items():
            result = await self.__run_probe(probe_id, probe)
            open_since = self.__open_since(*self.__latest[probe_id])
            rows.append({"id": probe_id, "label": label, **result,
                         "errors": self.__errors.counts(self.__matcher(probe_id),
                                                        open_since, past_since)})
        return rows

    async def __run_probe(self, probe_id: str, probe: Callable[[], Any]) -> dict:
        '''
        Runs one probe and records its state and last good cycle.  A probe that
        raises or hangs is reported as one broken service, never as a failed
        request — the point of the view is to show what is wrong, so it has to
        survive things being wrong.  Returns the card's fields, last_ok_ms taken
        out.
        Arguments:
            probe_id (str): The card.
            probe (Callable): Its health() probe.
        '''
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
        last_ok_ms = result.pop("last_ok_ms", None)
        self.__latest[probe_id] = (result.get("state", "off"), last_ok_ms)
        return result
