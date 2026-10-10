'''
Host metrics read straight from /proc and /sys, for the Järjestelmän tila graphs.

Deliberately no third-party dependency: psutil would be one more thing to pin,
build for ARM and keep current, and everything wanted here is a handful of files.
The backend only ever runs on Linux, so /proc is a safe assumption; anything that
is nevertheless missing (a thermal zone on WSL2) returns None rather than raising.

Pure functions with no state (the CPU's thermal zone aside, resolved once), so the
caller holds the two counter samples the rate maths needs and this module stays
trivially testable.
'''

import logging
import os

logger = logging.getLogger("system_service.metrics")

# Interfaces that are not the machine's real link. Container and VPN plumbing
# would otherwise double-count traffic that already crossed a physical NIC.
_SKIP_IFACE_PREFIXES = ("veth", "docker", "br-", "virbr", "tun", "tap")

# Block devices that are not physical disks: loop images, RAM disks and the
# device-mapper / md layers stacked on top of the real disks.
_SKIP_DISK_PREFIXES = ("loop", "ram", "zram", "dm-", "md", "sr", "fd", "nbd")


def _jiffies(fields: list[int]) -> tuple[int, int] | None:
    '''
    (total, idle) from one /proc/stat cpu line's counters.
    Arguments:
        fields (list[int]): The line's numeric fields, in kernel order.
    '''
    if len(fields) < 5:
        return None
    # user nice system idle iowait irq softirq steal guest guest_nice. Only the
    # first eight count: guest time is already inside user and nice, so summing
    # all ten would count a VM host's guest time twice.
    return sum(fields[:8]), fields[3] + fields[4]


def read_cpu_core_samples() -> dict[int, tuple[int, int]] | None:
    '''
    Returns {core number: (total_jiffies, idle_jiffies)} from the "cpuN" lines of
    /proc/stat.  Keyed by the kernel's core number rather than by position, so an
    offline core leaves a hole instead of shifting every later core onto the
    wrong line (and the wrong colour) in the graph.
    '''
    cores: dict[int, tuple[int, int]] = {}
    try:
        with open("/proc/stat", "r", encoding="utf-8") as fh:
            for line in fh:
                # The cpu lines come first, as one block.
                if not line.startswith("cpu"):
                    break
                parts = line.split()
                if parts[0] == "cpu":
                    continue
                sample = _jiffies([int(value) for value in parts[1:]])
                if sample is not None:
                    cores[int(parts[0][3:])] = sample
    except (OSError, ValueError):
        return None
    return cores or None


def cpu_percent(previous: tuple[int, int] | None,
                current: tuple[int, int] | None) -> float | None:
    '''
    Busy percentage between two (total, idle) jiffy samples of one core.
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


def block_device_for(path: str) -> str | None:
    '''
    The /proc/diskstats name of the block device holding `path` (a partition
    such as "mmcblk0p2" on the Pi), matched by major:minor.  None when the
    filesystem has no single backing device of its own — btrfs subvolumes,
    overlayfs and network mounts report a virtual device number.
    Arguments:
        path (str): Any path on the filesystem of interest.
    '''
    try:
        device = os.stat(path).st_dev
        wanted = (os.major(device), os.minor(device))
        with open("/proc/diskstats", "r", encoding="utf-8") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) > 2 and (int(parts[0]), int(parts[1])) == wanted:
                    return parts[2]
    except (OSError, ValueError):
        return None
    return None


def read_disk_io_sample(device: str | None) -> tuple[int, int] | None:
    '''
    Returns (bytes_read, bytes_written) since boot for one block device, or
    summed over the host's physical disks when `device` is None.  Like the CPU
    and network samples, only the delta between two of these means anything.

    The sum skips loop, RAM and device-mapper / md devices: those are layers
    over the physical disks, so counting them too would count the same I/O
    twice.  /proc/diskstats counts in 512-byte sectors whatever the device's
    real sector size.
    Arguments:
        device (str | None): A /proc/diskstats name from block_device_for().
    '''
    if device is None:
        try:
            wanted = {name for name in os.listdir("/sys/block")
                      if not name.startswith(_SKIP_DISK_PREFIXES)}
        except OSError:
            return None
    else:
        wanted = {device}
    read = written = 0
    found = False
    try:
        with open("/proc/diskstats", "r", encoding="utf-8") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) < 10 or parts[2] not in wanted:
                    continue
                read += int(parts[5]) * 512
                written += int(parts[9]) * 512
                found = True
    except (OSError, ValueError):
        return None
    return (read, written) if found else None


# Thermal zone types that are the CPU (or the SoC it lives in), best first: the
# Pi's "cpu-thermal", an Intel package sensor, the usual SoC names. A host whose
# zones match none of them falls back to zone 0.
_CPU_ZONE_TYPES = ("cpu-thermal", "cpu_thermal", "x86_pkg_temp", "soc_thermal", "cpu", "soc")

_cpu_zone: str | None | bool = False  # False = not resolved yet


def cpu_thermal_zone() -> str | None:
    '''
    The sysfs temp file of the CPU's thermal zone, resolved once: the zone whose
    `type` best matches _CPU_ZONE_TYPES, else zone 0, else None — WSL2 and many
    VMs have no thermal zones at all.
    '''
    global _cpu_zone
    if _cpu_zone is not False:
        return _cpu_zone
    base = "/sys/class/thermal"
    best: tuple[int, str] | None = None
    try:
        zones = sorted(name for name in os.listdir(base) if name.startswith("thermal_zone"))
    except OSError:
        zones = []
    for zone in zones:
        try:
            with open(os.path.join(base, zone, "type"), "r", encoding="utf-8") as fh:
                kind = fh.read().strip().lower()
        except OSError:
            continue
        for rank, wanted in enumerate(_CPU_ZONE_TYPES):
            if wanted in kind and (best is None or rank < best[0]):
                best = (rank, zone)
    chosen = best[1] if best else (zones[0] if zones else None)
    _cpu_zone = os.path.join(base, chosen, "temp") if chosen else None
    return _cpu_zone


def read_cpu_temp_c() -> float | None:
    '''
    CPU temperature in degrees Celsius, or None.

    Absent on WSL2 and on plenty of other hosts, so everything showing it must
    survive it being missing — hence None rather than an exception.
    '''
    path = cpu_thermal_zone()
    if path is None:
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
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
