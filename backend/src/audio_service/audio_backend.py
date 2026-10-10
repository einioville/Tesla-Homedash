'''
Host-audio control surfaces, one per audio stack the dashboard may run on.

Mirrors `media_service/base_media_player.py`: one abstract interface, several
concrete implementations, and a detector that picks whichever the host actually
has.  Raspberry Pi OS Bookworm — the reference deployment — ships PipeWire with
WirePlumber and a PulseAudio compatibility layer, so both the `pulse` and the
`wireplumber` adapters apply there; `pactl` is preferred where present because
its device identifiers are stable strings, while `wpctl` addresses nodes by a
session-scoped numeric id that has to be resolved from a stored name every time.

Nothing here raises for an ordinary runtime failure.  The caller is a config
hook whose value is already committed to disk, so a stopped daemon or a device
that has been unplugged must degrade to "no answer", not to an exception.
'''

import asyncio
import json
import logging
import re
import shutil
from abc import ABC, abstractmethod
from typing import NamedTuple

logger = logging.getLogger("audio_service.audio_backend")

# Every external call is bounded. This is the lesson CLAUDE.md 5.2.4 records
# about fmiopendata: one untimed external call cost this project 16 days of
# weather, and pactl against a half-dead server blocks on its socket the same way.
_TIMEOUT_SECONDS = 2.0


class AudioDevice(NamedTuple):
    '''
    One selectable audio output.
    Arguments:
        identifier (str): STABLE string stored in config.json — a PulseAudio sink
            name or a PipeWire node.name, never a numeric id (PipeWire ids are
            session-scoped and change across reboots and hotplugs).
        label (str): Human-readable name for the Options view.
    '''
    identifier: str
    label: str


async def run_command(argv: list[str], timeout: float = _TIMEOUT_SECONDS) -> tuple[int, str]:
    '''
    Runs one external command and returns (returncode, stdout).  The single place
    this package spawns a process, so the timeout and the never-raise contract
    are enforced exactly once.  A timeout kills the child and returns (-1, "").
    Arguments:
        argv (list[str]): Program and arguments.  Never passed through a shell.
        timeout (float): Seconds before the child is killed.
    '''
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError as e:
        logger.debug("Could not run %s: %s", argv[0], e)
        return -1, ""

    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("%s timed out after %.1f s", " ".join(argv), timeout)
        process.kill()
        await process.wait()
        return -1, ""
    return process.returncode, stdout.decode("utf-8", "replace")


class AudioBackend(ABC):
    '''
    Abstract host-audio control surface.  Every method is async because every one
    shells out, and none may raise for an ordinary failure.
    '''

    name = "none"
    # False when the stack cannot switch outputs at runtime, which makes the
    # Options view offer no choices rather than accept a write that does nothing.
    supports_device_selection = False

    @abstractmethod
    async def get_volume(self) -> int | None:
        '''Current output volume as 0-100, or None when it cannot be read.'''

    @abstractmethod
    async def set_volume(self, percent: int) -> bool:
        '''
        Sets the output volume.
        Arguments:
            percent (int): Target volume, already clamped to 0-100 by the caller.
        '''

    @abstractmethod
    async def list_devices(self) -> list[AudioDevice]:
        '''Selectable outputs; empty when the stack cannot enumerate or switch.'''

    @abstractmethod
    async def get_default_device(self) -> str | None:
        '''Identifier of the current default output, or None.'''

    @abstractmethod
    async def set_default_device(self, identifier: str) -> bool:
        '''
        Makes one output the default.
        Arguments:
            identifier (str): A stable identifier from list_devices().
        '''


class NullAudioBackend(AudioBackend):
    '''No controllable audio stack on this host.  Every answer is the empty one.'''

    name = "none"
    supports_device_selection = False

    async def get_volume(self) -> int | None:
        return None

    async def set_volume(self, percent: int) -> bool:
        return False

    async def list_devices(self) -> list[AudioDevice]:
        return []

    async def get_default_device(self) -> str | None:
        return None

    async def set_default_device(self, identifier: str) -> bool:
        return False


class PulseAudioBackend(AudioBackend):
    '''
    PulseAudio protocol control via `pactl` — covers real PulseAudio AND
    pipewire-pulse, since the latter implements the same server protocol on the
    same socket.  Preferred over WirePlumber where available: sinks are addressed
    by a stable NAME, which is exactly what a value persisted in config.json
    needs.
    Arguments:
        flavour (str): "pipewire-pulse" or "pulseaudio"; logging only, the
            command set is identical either way.
    '''

    name = "pulse"
    supports_device_selection = True

    _VOLUME_RE = re.compile(r"(\d+)%")

    def __init__(self, flavour: str = "pulseaudio"):
        self.flavour = flavour

    async def get_volume(self) -> int | None:
        rc, out = await run_command(["pactl", "get-sink-volume", "@DEFAULT_SINK@"])
        if rc != 0:
            return None
        match = self._VOLUME_RE.search(out)
        return int(match.group(1)) if match else None

    async def set_volume(self, percent: int) -> bool:
        rc, _ = await run_command(
            ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{percent}%"]
        )
        return rc == 0

    async def list_devices(self) -> list[AudioDevice]:
        rc, out = await run_command(["pactl", "-f", "json", "list", "sinks"])
        if rc == 0:
            try:
                return [
                    AudioDevice(sink["name"], sink.get("description") or sink["name"])
                    for sink in json.loads(out)
                    if sink.get("name")
                ]
            except (ValueError, KeyError, TypeError) as e:
                logger.warning("Could not parse pactl JSON sink list: %s", e)

        # Older pactl without -f json: the short listing is tab-separated and has
        # no description column, so the name doubles as the label.
        rc, out = await run_command(["pactl", "list", "sinks", "short"])
        if rc != 0:
            return []
        devices = []
        for line in out.splitlines():
            fields = line.split("\t")
            if len(fields) >= 2 and fields[1]:
                devices.append(AudioDevice(fields[1], fields[1]))
        return devices

    async def get_default_device(self) -> str | None:
        rc, out = await run_command(["pactl", "get-default-sink"])
        if rc == 0 and out.strip():
            return out.strip()
        rc, out = await run_command(["pactl", "info"])
        if rc != 0:
            return None
        for line in out.splitlines():
            if line.startswith("Default Sink:"):
                return line.split(":", 1)[1].strip()
        return None

    async def set_default_device(self, identifier: str) -> bool:
        rc, _ = await run_command(["pactl", "set-default-sink", identifier])
        if rc != 0:
            logger.warning("pactl could not select sink %s", identifier)
            return False
        # Changing the default only affects NEW streams. spotifyd and libVLC are
        # already connected, so without this the radio keeps playing out of the
        # old jack after the user switches to HDMI.
        await self.__move_streams(identifier)
        return True

    async def __move_streams(self, identifier: str) -> None:
        '''
        Moves every live playback stream onto the newly selected sink.
        Arguments:
            identifier (str): Target sink name.
        '''
        rc, out = await run_command(["pactl", "list", "sink-inputs", "short"])
        if rc != 0:
            return
        for line in out.splitlines():
            index = line.split("\t")[0].strip()
            if not index.isdigit():
                continue
            moved, _ = await run_command(["pactl", "move-sink-input", index, identifier])
            if moved != 0:
                logger.debug("Could not move sink-input %s to %s", index, identifier)


class WirePlumberBackend(AudioBackend):
    '''
    PipeWire control via `wpctl`, the fallback for a PipeWire host with no
    pulseaudio-utils installed (pipewire-pulse only *suggests* that package, so
    pactl is not guaranteed).  Enumeration goes through `pw-dump` rather than
    `wpctl status`: the latter renders a box-drawing tree whose layout changed
    between WirePlumber 0.4 and 0.5, while pw-dump is real JSON and ships with
    pipewire-bin, which the pipewire package hard-depends on.
    '''

    name = "wireplumber"
    supports_device_selection = True

    _DEFAULT_SINK = "@DEFAULT_AUDIO_SINK@"
    # wpctl prints a 0.0-1.0 float, plus " [MUTED]" when muted.
    _VOLUME_RE = re.compile(r"^Volume:\s+([0-9]*\.?[0-9]+)")
    _NODE_NAME_RE = re.compile(r'^\s*\*?\s*node\.name\s*=\s*"(.+)"\s*$')

    async def get_volume(self) -> int | None:
        rc, out = await run_command(["wpctl", "get-volume", self._DEFAULT_SINK])
        # NOTE: wpctl exits 0 even for a node that does not exist, printing
        # "Node 'N' not found" — so the "Volume: " prefix, not rc, is the test.
        if rc != 0:
            return None
        match = self._VOLUME_RE.match(out.strip())
        return round(float(match.group(1)) * 100) if match else None

    async def set_volume(self, percent: int) -> bool:
        # wpctl does NOT clamp: "150%" is accepted and overdrives the sink. The
        # caller clamps, and this is the second line of defence.
        percent = max(0, min(100, percent))
        rc, _ = await run_command(["wpctl", "set-volume", self._DEFAULT_SINK, f"{percent}%"])
        return rc == 0

    async def list_devices(self) -> list[AudioDevice]:
        return [device for device, _ in await self.__scan_sinks()]

    async def get_default_device(self) -> str | None:
        rc, out = await run_command(["wpctl", "inspect", self._DEFAULT_SINK])
        if rc != 0:
            return None
        for line in out.splitlines():
            match = self._NODE_NAME_RE.match(line)
            if match:
                return match.group(1)
        return None

    async def set_default_device(self, identifier: str) -> bool:
        # wpctl set-default takes only a numeric id, and those are session-scoped,
        # so the stored name has to be resolved against the live graph each time.
        for device, node_id in await self.__scan_sinks():
            if device.identifier == identifier:
                rc, _ = await run_command(["wpctl", "set-default", str(node_id)])
                return rc == 0
        logger.warning("PipeWire node %s is not present; leaving the output alone", identifier)
        return False

    async def __scan_sinks(self) -> list[tuple[AudioDevice, int]]:
        '''Reads the PipeWire graph and returns each audio sink with its live id.'''
        rc, out = await run_command(["pw-dump"])
        if rc != 0:
            return []
        try:
            objects = json.loads(out)
        except ValueError as e:
            logger.warning("Could not parse pw-dump output: %s", e)
            return []

        sinks = []
        for obj in objects:
            if obj.get("type") != "PipeWire:Interface:Node":
                continue
            props = (obj.get("info") or {}).get("props") or {}
            if props.get("media.class") != "Audio/Sink":
                continue
            node_name = props.get("node.name")
            if not node_name:
                continue
            label = props.get("node.description") or node_name
            sinks.append((AudioDevice(node_name, label), obj.get("id")))
        return sinks


class AlsaBackend(AudioBackend):
    '''
    Bare ALSA via `amixer`.  Volume works; the output device does NOT, because
    the ALSA default lives in static config (pcm.!default in ~/.asoundrc) that
    each client reads when it opens the device — switching it at runtime would
    mean rewriting a dotfile AND restarting VLC and spotifyd.  So
    supports_device_selection is False and the Options view offers no choices.
    Arguments:
        control (str): Simple mixer control to drive, e.g. "Master".
    '''

    name = "alsa"
    supports_device_selection = False

    _PERCENT_RE = re.compile(r"\[(\d+)%\]")
    _CONTROL_RE = re.compile(r"Simple mixer control '([^']+)',(\d+)")
    # In preference order: the first of these the card actually exposes.
    _CONTROL_PREFERENCE = ("Master", "PCM", "Speaker", "Headphone", "Digital")

    def __init__(self, control: str = "Master"):
        self.control = control

    @classmethod
    async def discover_control(cls) -> str | None:
        '''Returns the best simple mixer control on this card, or None.'''
        rc, out = await run_command(["amixer", "scontrols"])
        if rc != 0:
            return None
        found = cls._CONTROL_RE.findall(out)
        names = [name for name, _ in found]
        for preferred in cls._CONTROL_PREFERENCE:
            if preferred in names:
                return preferred
        return names[0] if names else None

    async def get_volume(self) -> int | None:
        # -M is the mapped (perceptual) scale, which is what a user means by "%".
        rc, out = await run_command(["amixer", "-M", "sget", self.control])
        if rc != 0:
            return None
        match = self._PERCENT_RE.search(out)
        return int(match.group(1)) if match else None

    async def set_volume(self, percent: int) -> bool:
        rc, _ = await run_command(
            ["amixer", "-M", "-q", "sset", self.control, f"{percent}%"]
        )
        return rc == 0

    async def list_devices(self) -> list[AudioDevice]:
        return []

    async def get_default_device(self) -> str | None:
        return None

    async def set_default_device(self, identifier: str) -> bool:
        return False


async def detect_backend() -> AudioBackend:
    '''
    Probes the host for a controllable audio stack and returns the first that
    answers, in the order pactl -> wpctl -> amixer.

    pactl goes first because it covers both PulseAudio and pipewire-pulse with
    one adapter and addresses sinks by stable name.  wpctl is the fallback for a
    PipeWire host without pulseaudio-utils (which pipewire-pulse only suggests).
    amixer is last: it can set a volume but cannot switch outputs at runtime.
    A host with none of them gets NullAudioBackend, which lets the Options view
    say so instead of silently accepting writes that do nothing.
    '''
    if shutil.which("pactl"):
        rc, out = await run_command(["pactl", "info"])
        if rc == 0:
            flavour = "pipewire-pulse" if "PipeWire" in out else "pulseaudio"
            logger.info("Audio backend: pactl (%s)", flavour)
            return PulseAudioBackend(flavour)

    if shutil.which("wpctl"):
        rc, out = await run_command(["wpctl", "status"])
        if rc == 0 and out.startswith("PipeWire "):
            logger.info("Audio backend: wpctl (PipeWire/WirePlumber)")
            return WirePlumberBackend()

    if shutil.which("amixer"):
        control = await AlsaBackend.discover_control()
        if control:
            logger.info("Audio backend: amixer (ALSA, control '%s')", control)
            return AlsaBackend(control)

    logger.warning(
        "No controllable audio stack found (pactl, wpctl and amixer all absent "
        "or unresponsive); audio settings will be rejected"
    )
    return NullAudioBackend()
