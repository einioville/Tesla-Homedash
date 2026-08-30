'''
The Options view's maintenance dashboard: how the host and the backend are doing.

Request/response rather than a broadcast, deliberately.  The Options view is open
a fraction of the time the dashboard is running, and sampling /proc for every
connected client every few seconds to feed a screen nobody is looking at would be
pure waste.  Nothing here runs until someone asks.

Per-service health comes from duck-typed `health()` methods — the same pattern as
`stream_everything()` and `apply_config()` — so each service answers for itself
from state it already keeps, and this module knows nothing about any of them.
'''

import asyncio
import inspect
import json
import logging
import os
import time
from typing import Any, Callable

from ..utils import protocol
from . import system_metrics as metrics

logger = logging.getLogger("system_service")

# Older than this and the stored counter sample says nothing about "now" — it
# would report the average since the pane was last open, which may be hours.
_MAX_DELTA_SECONDS = 30.0
# The window used instead, when the stored sample is stale or missing.
_FRESH_SAMPLE_SECONDS = 0.25
# A wedged probe (InfluxDB's awaits a real ping) must not hang the whole reply.
_PROBE_TIMEOUT_SECONDS = 2.0


class SystemStatusService:
    '''
    Serves SYSTEM_GET_STATUS by sampling the host and polling every registered
    service probe.

    Deliberately NOT registered with Server.register_service: a status page
    nobody has opened is not worth snapshotting to every connecting client.
    Arguments:
        server (Server): TCP server, used only to reply to the requesting client.
        config (Config): Shared configuration; supplies config.path so the disk
            report covers wherever the configuration actually lives.
        error_counter (ErrorCounter): The counting log handler from
            logger_configurator, read for the WARNING+ tallies.
    '''

    def __init__(self, server, config, error_counter):
        self.__server = server
        self.__config = config
        self.__errors = error_counter
        # probe id -> (Finnish label, callable returning a health dict)
        self.__probes: dict[str, tuple[str, Callable[[], Any]]] = {}
        self.__prev_cpu: tuple[int, int] | None = None
        self.__prev_net: tuple[int, int] | None = None
        self.__prev_sample_ms: float | None = None
        self.__start_ms = int(time.time() * 1000)

    # ── Wiring ────────────────────────────────────────────────────

    def register_probe(self, probe_id: str, label: str, probe: Callable[[], Any]) -> None:
        '''
        Registers one service's health probe.
        Arguments:
            probe_id (str): Stable id used as the row key.
            label (str): Finnish row label for the status view.
            probe (Callable): Returns a dict with "state" ("ok"/"warn"/"error"/
                "off") and optionally "detail"; may be async.
        '''
        self.__probes[probe_id] = (label, probe)

    # ── Protocol handler ──────────────────────────────────────────

    async def handle_get_status(self, _payload: bytes, writer) -> None:
        '''
        SYSTEM_GET_STATUS handler: builds the status document and replies to the
        requesting client only.  Any failure still produces a reply, so the view
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

        body = json.dumps(document, ensure_ascii=False).encode("utf-8")
        payload = bytes((status,)) + len(body).to_bytes(4, "big") + body
        await self.__server.send_to(writer, protocol.frame(protocol.SYSTEM_STATUS, payload))

    # ── Internals ─────────────────────────────────────────────────

    async def __build(self) -> dict:
        '''Samples the host, polls every probe, and assembles the document.'''
        cpu_now = metrics.read_cpu_sample()
        net_now = metrics.read_net_sample()
        now_ms = time.monotonic() * 1000

        stale = (self.__prev_sample_ms is None
                 or (now_ms - self.__prev_sample_ms) > _MAX_DELTA_SECONDS * 1000)
        if stale:
            # First request after the pane opens. Reusing a half-hour-old sample
            # would report the average over that half hour, which is not what
            # "CPU now" means — so take a fresh short window instead.
            await asyncio.sleep(_FRESH_SAMPLE_SECONDS)
            prev_cpu, prev_net = cpu_now, net_now
            window_s = _FRESH_SAMPLE_SECONDS
            cpu_now = metrics.read_cpu_sample()
            net_now = metrics.read_net_sample()
        else:
            prev_cpu, prev_net = self.__prev_cpu, self.__prev_net
            window_s = (now_ms - self.__prev_sample_ms) / 1000.0

        self.__prev_cpu, self.__prev_net = cpu_now, net_now
        self.__prev_sample_ms = time.monotonic() * 1000

        rx_per_s = tx_per_s = None
        if prev_net is not None and net_now is not None and window_s > 0:
            rx_per_s = max(0.0, (net_now[0] - prev_net[0]) / window_s)
            tx_per_s = max(0.0, (net_now[1] - prev_net[1]) / window_s)

        memory = metrics.read_meminfo()
        load = metrics.load_average()
        now_wall_ms = int(time.time() * 1000)

        return {
            "host": {
                "uptime_s": metrics.read_uptime_seconds(),
                "cpu_pct": metrics.cpu_percent(prev_cpu, cpu_now),
                "cpu_count": os.cpu_count(),
                "cpu_temp_c": metrics.read_cpu_temp_c(),
                "load": list(load) if load else None,
                "mem_total_b": memory.get("MemTotal"),
                "mem_available_b": memory.get("MemAvailable"),
                "swap_total_b": memory.get("SwapTotal"),
                "swap_free_b": memory.get("SwapFree"),
                "net_rx_bytes_per_s": rx_per_s,
                "net_tx_bytes_per_s": tx_per_s,
                "net_rx_total_b": net_now[0] if net_now else None,
                "net_tx_total_b": net_now[1] if net_now else None,
                "disks": metrics.disk_usages(
                    ("/", os.path.dirname(self.__config.path), "/var/lib/influxdb2")
                ),
            },
            "backend": {
                "started_ms": self.__start_ms,
                "uptime_s": (now_wall_ms - self.__start_ms) / 1000.0,
                "rss_b": metrics.read_process_rss_bytes(),
                "pid": os.getpid(),
            },
            "services": await self.__collect_services(),
            "errors": self.__errors.snapshot(),
            "sampled_ms": now_wall_ms,
            "window_s": window_s,
        }

    async def __collect_services(self) -> list[dict]:
        '''
        Runs every registered probe.  A probe that raises or hangs is reported as
        one broken service, never as a failed request — the point of the view is
        to show what is wrong, so it has to survive things being wrong.
        '''
        rows = []
        for probe_id, (label, probe) in self.__probes.items():
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
            rows.append({"id": probe_id, "label": label, **result})
        return rows
