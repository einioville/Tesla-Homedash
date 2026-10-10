'''
The Järjestelmän tila graphs' data: a rolling window of host samples.

Unlike the status document (system_status_service.py), this IS sampled all the
time, in the background.  A graph that started empty every time its section was
opened — and took ten minutes to fill — would answer nothing; the point of the
graph is "what has the host been doing", which needs the samples from before
anyone looked.  One tick is four small /proc reads every two seconds, which is
noise even on the Pi.  The samples still only leave the process on request
(SYSTEM_GET_HISTORY), and incrementally: a client asks for what is newer than the
last sample it holds.
'''

import asyncio
import json
import logging
import os
import shutil
import time
from collections import deque

from ..utils import protocol
from . import system_metrics as metrics

logger = logging.getLogger("system_service.history")

# One sample per this many seconds. CPU and the rates are averaged over it, so
# it is also the graph's time resolution.
INTERVAL_SECONDS = 2.0
# How far back the buffer reaches, and so what the graphs span.
WINDOW_SECONDS = 600
# The filesystem whose device the disk graph follows, and whose space it reports.
_DISK_PATH = "/"


class SystemHistory:
    '''
    Samples the host every INTERVAL_SECONDS into a WINDOW_SECONDS ring buffer and
    serves SYSTEM_GET_HISTORY from it.

    Each sample holds per-core CPU load, memory in use, the disk and network
    rates over the interval, and the CPU temperature.  Memory total and disk space change too rarely to be
    worth a column, so a reply carries them once, beside the samples.
    Arguments:
        server (Server): TCP server, used only to reply to the requesting client.
    '''

    def __init__(self, server):
        self.__server = server
        self.__samples: deque[dict] = deque(
            maxlen=int(WINDOW_SECONDS / INTERVAL_SECONDS) + 1
        )
        self.__mem_total_b: int | None = None
        # Resolved once: the device under / does not move while we run.
        self.__disk_device = metrics.block_device_for(_DISK_PATH)

    def get_run_task(self) -> asyncio.Task:
        '''Starts the sampling loop as a task for start_services to gather.'''
        return asyncio.create_task(self.run())

    async def run(self) -> None:
        '''
        Samples forever.  A tick that fails is logged and skipped, never raised:
        this task is gathered with the rest of the backend, so an exception here
        would take the whole process down over a graph.
        '''
        logger.info("Sampling the host every %.0f s (disk: %s)", INTERVAL_SECONDS,
                    self.__disk_device or "all physical disks")
        loop = asyncio.get_running_loop()
        previous = self.__read()
        previous_at = loop.time()
        next_at = previous_at + INTERVAL_SECONDS
        while True:
            await asyncio.sleep(max(0.0, next_at - loop.time()))
            now = loop.time()
            # Scheduled from the plan rather than from "now", so the interval does
            # not drift; a loop stalled past a whole interval starts afresh.
            next_at = next_at + INTERVAL_SECONDS if now - next_at < INTERVAL_SECONDS \
                else now + INTERVAL_SECONDS
            try:
                current = self.__read()
                self.__append(self.__sample(previous, current, now - previous_at))
                previous, previous_at = current, now
            except Exception as e:
                logger.warning("Could not sample the host: %s", e)

    # ── Protocol handler ──────────────────────────────────────────

    async def handle_get_history(self, payload: bytes, writer) -> None:
        '''
        SYSTEM_GET_HISTORY handler: replies with every sample newer than the
        request's `since_ms`, to the requesting client only.

        `reset` tells the client to drop what it holds instead of appending: the
        client asked for everything, or holds samples newer than any here — the
        host clock went backwards, so its timeline and ours no longer line up.
        Arguments:
            payload (bytes): since_ms(8B, signed); empty or 0 = everything.
            writer (StreamWriter): The requesting client.
        '''
        since = int.from_bytes(payload[:8], "big", signed=True) if len(payload) >= 8 else 0
        samples = list(self.__samples)
        newest = samples[-1]["t"] if samples else 0
        reset = since <= 0 or (bool(samples) and since > newest)
        if not reset:
            samples = [sample for sample in samples if sample["t"] > since]

        try:
            document = {
                "interval_s": INTERVAL_SECONDS,
                "window_s": WINDOW_SECONDS,
                "reset": reset,
                "mem_total_b": self.__mem_total_b,
                "cpu_count": os.cpu_count(),
                "disk": self.__disk_space(),
                # False on a host with no thermal zone (WSL2), so the graph can
                # say so instead of waiting for data that will never come.
                "temp_available": metrics.cpu_thermal_zone() is not None,
                "samples": samples,
            }
            body = json.dumps(document, separators=(",", ":")).encode("utf-8")
            status = protocol.CONFIG_STATUS_OK
        except Exception as e:
            logger.error("Could not build the system history: %s", e)
            body = b"{}"
            status = protocol.CONFIG_STATUS_ERROR

        reply = bytes((status,)) + len(body).to_bytes(4, "big") + body
        await self.__server.send_to(writer, protocol.frame(protocol.SYSTEM_HISTORY, reply))

    # ── Internals ─────────────────────────────────────────────────

    def __read(self) -> dict:
        '''Reads every raw counter one sample needs.'''
        return {
            "cpu": metrics.read_cpu_core_samples(),
            "net": metrics.read_net_sample(),
            "disk": metrics.read_disk_io_sample(self.__disk_device),
            "mem": metrics.read_meminfo(),
            "temp": metrics.read_cpu_temp_c(),
        }

    def __sample(self, previous: dict, current: dict, window_s: float) -> dict:
        '''
        Turns two raw reads into one sample.  A value that cannot be computed —
        a counter missing on this host, a core that went offline — is None,
        which the graph draws as a gap rather than as zero.
        Arguments:
            previous (dict): The earlier __read() result.
            current (dict): The later __read() result.
            window_s (float): Seconds between the two reads.
        '''
        cpu: list[float | None] = []
        if previous["cpu"] and current["cpu"]:
            cpu = [None] * (max(current["cpu"]) + 1)
            for core, now in current["cpu"].items():
                pct = metrics.cpu_percent(previous["cpu"].get(core), now)
                cpu[core] = round(pct, 1) if pct is not None else None

        def rate(key: str, index: int) -> int | None:
            '''Bytes per second for one field of a counter pair.'''
            before, after = previous[key], current[key]
            if before is None or after is None or window_s <= 0:
                return None
            # A counter that went backwards was reset (a re-plugged interface).
            return max(0, round((after[index] - before[index]) / window_s))

        memory = current["mem"]
        total, available = memory.get("MemTotal"), memory.get("MemAvailable")
        if total:
            self.__mem_total_b = total
        return {
            "t": int(time.time() * 1000),
            "cpu": cpu,
            # MemAvailable, for the reason read_meminfo() gives.
            "mem_used_b": total - available if total and available is not None else None,
            "disk_read_bps": rate("disk", 0),
            "disk_write_bps": rate("disk", 1),
            "net_rx_bps": rate("net", 0),
            "net_tx_bps": rate("net", 1),
            "cpu_temp_c": round(current["temp"], 1) if current["temp"] is not None else None,
        }

    def __append(self, sample: dict) -> None:
        '''
        Adds a sample and drops what has fallen out of the window — by TIME as
        well as by count, so a clock that jumped forward (the Pi has no RTC and
        steps its clock when NTP first answers) does not leave a stretch of
        samples from "months ago" in the graph.  A clock that went backwards
        starts the buffer over, since the timeline is no longer in order.
        Arguments:
            sample (dict): One __sample() result.
        '''
        if self.__samples and sample["t"] < self.__samples[-1]["t"]:
            self.__samples.clear()
        self.__samples.append(sample)
        cutoff = sample["t"] - WINDOW_SECONDS * 1000
        while self.__samples and self.__samples[0]["t"] < cutoff:
            self.__samples.popleft()

    def __disk_space(self) -> dict | None:
        '''Space on the graphed filesystem, read per request (a statvfs call).'''
        try:
            usage = shutil.disk_usage(_DISK_PATH)
        except OSError:
            return None
        return {
            "path": _DISK_PATH,
            "device": self.__disk_device,
            "total_b": usage.total,
            "used_b": usage.used,
            "free_b": usage.free,
            "used_pct": round(100.0 * usage.used / usage.total, 1) if usage.total else None,
        }
