'''
Host metrics read straight from /proc and the stdlib.

Deliberately no third-party dependency: psutil would be one more thing to pin,
build for ARM and keep current, and everything wanted here is four files and
`shutil.disk_usage`.  The backend only ever runs on Linux, so /proc is a safe
assumption; anything that is nevertheless missing (a thermal zone on WSL2)
returns None rather than raising.

Pure functions with no state, so the caller holds the two counter samples the
rate maths needs and this module stays trivially testable.
'''

import logging
import os
import shutil

logger = logging.getLogger("system_service.metrics")

# Interfaces that are not the machine's real link. Container and VPN plumbing
# would otherwise double-count traffic that already crossed a physical NIC.
_SKIP_IFACE_PREFIXES = ("veth", "docker", "br-", "virbr", "tun", "tap")


def read_uptime_seconds() -> float | None:
    '''Host uptime in seconds, from the first field of /proc/uptime.'''
    try:
        with open("/proc/uptime", "r", encoding="utf-8") as fh:
            # Field 1 is summed idle time across cores, which is not wall time.
            return float(fh.readline().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def read_cpu_sample() -> tuple[int, int] | None:
    '''
    Returns (total_jiffies, idle_jiffies) from the aggregate "cpu" line of
    /proc/stat.  A single sample says nothing on its own — CPU load is the
    DELTA between two, which is what cpu_percent() computes.
    '''
    try:
        with open("/proc/stat", "r", encoding="utf-8") as fh:
            parts = fh.readline().split()
        if not parts or parts[0] != "cpu":
            return None
        fields = [int(value) for value in parts[1:]]
    except (OSError, ValueError):
        return None
    if len(fields) < 5:
        return None
    # user nice system idle iowait irq softirq steal ...
    return sum(fields), fields[3] + fields[4]


def cpu_percent(previous: tuple[int, int] | None,
                current: tuple[int, int] | None) -> float | None:
    '''
    Busy percentage between two read_cpu_sample() results.
    Arguments:
        previous (tuple | None): The earlier (total, idle) sample.
        current (tuple | None): The later (total, idle) sample.
    '''
    if previous is None or current is None:
        return None
    delta_total = current[0] - previous[0]
    delta_idle = current[1] - previous[1]
    if delta_total <= 0:
        # Counter reset, or both samples landed in the same jiffy.
        return None
    return max(0.0, min(100.0, 100.0 * (delta_total - delta_idle) / delta_total))


def read_meminfo() -> dict:
    '''
    MemTotal / MemAvailable / SwapTotal / SwapFree from /proc/meminfo, in BYTES.

    MemAvailable rather than MemFree: free memory on Linux is mostly page cache
    and reads alarmingly low, while MemAvailable is the honest answer to "how
    much could a new process actually get".
    '''
    wanted = {"MemTotal", "MemAvailable", "SwapTotal", "SwapFree"}
    out: dict[str, int] = {}
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as fh:
            for line in fh:
                name, _, rest = line.partition(":")
                if name in wanted:
                    out[name] = int(rest.split()[0]) * 1024  # the file is always kB
                    if len(out) == len(wanted):
                        break
    except (OSError, ValueError, IndexError):
        return {}
    return out


def read_net_sample() -> tuple[int, int] | None:
    '''
    Returns (rx_bytes, tx_bytes) summed over the host's real interfaces.

    Parsed with partition(":") rather than split(): once a counter grows past
    the column width the kernel prints "eth0:1234567890" with no space, and a
    split() would shift every field by one.
    '''
    rx = tx = 0
    try:
        with open("/proc/net/dev", "r", encoding="utf-8") as fh:
            lines = fh.readlines()[2:]  # two header lines
        for line in lines:
            name, _, rest = line.partition(":")
            name = name.strip()
            if not name or name == "lo" or name.startswith(_SKIP_IFACE_PREFIXES):
                continue
            fields = rest.split()
            rx += int(fields[0])
            tx += int(fields[8])
    except (OSError, ValueError, IndexError):
        return None
    return rx, tx


def disk_usages(candidates: tuple[str, ...]) -> list[dict]:
    '''
    Disk usage per candidate path, deduplicated by device.

    On the Pi the root filesystem, the config directory and InfluxDB's data all
    live on the same SD card, so reporting three identical rows would be noise.
    Arguments:
        candidates (tuple[str, ...]): Paths to report on; missing ones are skipped.
    '''
    seen: set[int] = set()
    out: list[dict] = []
    for path in candidates:
        if not path:
            continue
        try:
            device = os.stat(path).st_dev
            if device in seen:
                continue
            usage = shutil.disk_usage(path)
        except OSError:
            continue
        seen.add(device)
        out.append({
            "path": path,
            "total_b": usage.total,
            "used_b": usage.used,
            "free_b": usage.free,
            "used_pct": round(100.0 * usage.used / usage.total, 1) if usage.total else None,
        })
    return out


def read_cpu_temp_c() -> float | None:
    '''
    CPU temperature in degrees Celsius from the first thermal zone, or None.

    Absent on WSL2 and on plenty of other hosts, so the whole status view must
    survive it being missing — hence None rather than an exception.
    '''
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r", encoding="utf-8") as fh:
            return int(fh.read().strip()) / 1000.0
    except (OSError, ValueError):
        return None


def read_process_rss_bytes() -> int | None:
    '''The backend process's own resident set size, from /proc/self/status.'''
    try:
        with open("/proc/self/status", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def load_average() -> tuple[float, float, float] | None:
    '''1/5/15-minute load average, or None where the platform has none.'''
    try:
        return os.getloadavg()
    except (OSError, AttributeError):
        return None
