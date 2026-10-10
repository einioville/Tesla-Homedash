'''
The audio equalizer: a PipeWire filter-chain sink that every playback stream
passes through on its way to the real output.

The radio (libVLC, in this process) and Spotify (spotifyd, a separate process)
are two unrelated clients, so the only place one equalizer can reach both is the
host's audio server.  PipeWire's filter-chain module builds a virtual sink out of
its built-in biquad filters; it ships with the stock `pipewire` package on
Raspberry Pi OS (Bookworm and Trixie), so nothing extra is installed.

The chain runs in a `pipewire -c <file>` client process this service owns, not as
a drop-in in the user's own PipeWire configuration: nothing outside this app's
runtime directory is written, and stopping the process removes the sink without
restarting the audio server.  Band gains change in place with `pw-cli set-param`
on the sink's Props, which is measured to retune the running filters with no
gap: a 250 Hz tone came out at exactly +12.0 / -12.0 dB.

Like audio_backend, nothing here raises for an ordinary runtime failure — the
callers are config hooks whose value is already on disk.
'''

import asyncio
import logging
import os
import shutil
import signal
import tempfile
from pathlib import Path

from .audio_backend import parse_pw_dump, run_command

logger = logging.getLogger("audio_service.equalizer")

# The two PipeWire nodes the chain creates: the sink streams play into, and the
# stream that carries the filtered audio on to the real output.
SINK_NAME = "tesla_homedash_eq"
OUTPUT_NAME = "tesla_homedash_eq.output"

# The five graphic-equalizer bands: config key (under "audio") and centre
# frequency.  Roughly two octaves apart, so a Q of 0.8 (about 1.75 octaves wide)
# lets neighbouring bands meet without one band's boost doubling up on the next.
# The Options view labels its columns with these frequencies — keep the schema's
# band labels in config_service.SETTINGS_SCHEMA in step with them.
BANDS = (
    ("eqBand1", 60.0),
    ("eqBand2", 250.0),
    ("eqBand3", 1000.0),
    ("eqBand4", 4000.0),
    ("eqBand5", 12000.0),
)
_BAND_Q = 0.8
# The separate bass slider: a low shelf, so it lifts everything below the corner
# evenly instead of adding a hump at one frequency the way the 60 Hz band does.
BASS_KEY = "bassBoost"
_BASS_FREQ = 90.0
_BASS_Q = 0.7

# Config keys of every gain the chain applies, bass included.
GAIN_KEYS = tuple(key for key, _ in BANDS) + (BASS_KEY,)

# How long a freshly started chain gets to show its nodes in the graph.
_START_TIMEOUT_SECONDS = 4.0
_START_POLL_SECONDS = 0.2
_STOP_TIMEOUT_SECONDS = 2.0


def filter_name(key: str) -> str:
    '''
    The filter-graph node name for one gain key, as used in "<name>:Gain".
    Arguments:
        key (str): One of GAIN_KEYS.
    '''
    return "bass" if key == BASS_KEY else key


def is_flat(gains: dict) -> bool:
    '''
    Whether a set of gains leaves the sound untouched, in which case the chain
    is not run at all.
    Arguments:
        gains (dict): Gain key -> dB.
    '''
    return all(float(gains.get(key) or 0) == 0 for key in GAIN_KEYS)


class PipeWireEqualizer:
    '''
    Owns the filter-chain process: starts it with the current gains and output,
    retunes it in place, points it at another output, and stops it.
    '''

    def __init__(self):
        self.__process: asyncio.subprocess.Process | None = None
        self.__stderr_task: asyncio.Task | None = None
        self.__sink_id: int | None = None
        self.__output_id: int | None = None
        self.__dir = _runtime_dir()
        self.__conf_path = self.__dir / "equalizer.conf"
        self.__pid_path = self.__dir / "equalizer.pid"

    @staticmethod
    async def detect() -> bool:
        '''
        Whether this host can run the chain: the PipeWire tools are installed and
        a PipeWire server answers.  A PulseAudio-only or bare-ALSA host cannot.
        '''
        if not all(shutil.which(tool) for tool in ("pipewire", "pw-cli", "pw-dump", "pw-metadata")):
            return False
        rc, _ = await run_command(["pw-cli", "info", "0"])
        return rc == 0

    @property
    def running(self) -> bool:
        '''Whether the chain process is alive and its nodes were found.'''
        return (self.__process is not None and self.__process.returncode is None
                and self.__sink_id is not None)

    # ── Lifecycle ─────────────────────────────────────────────────

    async def start(self, gains: dict, target: str) -> bool:
        '''
        Starts the chain and waits for its nodes to appear.
        Arguments:
            gains (dict): Gain key -> dB, written into the chain as its starting
                values, so the first sound out of it is already right.
            target (str): node.name of the output it plays into; "" lets
                WirePlumber pick, which never links the chain back into itself
                (the two nodes share a link group).
        '''
        await self.stop()
        await self.__stop_stale()
        try:
            self.__dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            self.__conf_path.write_text(_chain_config(gains), encoding="utf-8")
        except OSError as e:
            logger.warning("Could not write the equalizer configuration: %s", e)
            return False

        argv = ["pipewire", "-c", str(self.__conf_path)]
        # The chain must not outlive this process: a backend that dies without
        # stopping it (a crash, or os._exit on an in-app restart outside systemd)
        # would leave an orphan, and the next start a second sink of the same
        # name.  setpriv sets the parent-death signal and execs pipewire, which
        # keeps it; systemd's cgroup clean-up covers the deployment anyway.
        if shutil.which("setpriv"):
            argv = ["setpriv", "--pdeathsig", "TERM", "--"] + argv
        try:
            self.__process = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as e:
            logger.warning("Could not start the equalizer: %s", e)
            self.__process = None
            return False
        self.__stderr_task = asyncio.create_task(self.__log_stderr(self.__process))
        try:
            self.__pid_path.write_text(str(self.__process.pid), encoding="utf-8")
        except OSError as e:
            logger.debug("Could not write the equalizer pid file: %s", e)

        loop = asyncio.get_running_loop()
        deadline = loop.time() + _START_TIMEOUT_SECONDS
        while loop.time() < deadline and self.__process.returncode is None:
            ids = await self.__find_nodes()
            if ids:
                self.__sink_id, self.__output_id = ids
                break
            await asyncio.sleep(_START_POLL_SECONDS)

        if not self.running:
            logger.warning("The equalizer did not come up within %.0f s (exit code %s)",
                           _START_TIMEOUT_SECONDS, self.__process.returncode)
            await self.stop()
            return False

        await self.set_target(target)
        logger.info("Equalizer started (sink %s, output %s → %s)",
                    self.__sink_id, self.__output_id, target or "WirePlumber's choice")
        return True

    async def stop(self) -> None:
        '''Stops the chain if it runs.  Streams in it fall back to another sink.'''
        process, self.__process = self.__process, None
        self.__sink_id = self.__output_id = None
        if process is not None and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=_STOP_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
            logger.info("Equalizer stopped")
        if self.__stderr_task is not None:
            await self.__stderr_task
            self.__stderr_task = None
        self.__pid_path.unlink(missing_ok=True)

    async def check(self) -> bool:
        '''
        Whether the running chain is still alive AND still in the graph.  A
        PipeWire restart drops the sink while the client process may linger, and
        node ids are not stable across one, so both are re-read.
        '''
        if self.__process is None or self.__process.returncode is not None:
            return False
        ids = await self.__find_nodes()
        if ids is None:
            # Could not look: not the same as gone, and a restart for nothing
            # would put a gap in the music.
            return True
        if not ids:
            return False
        self.__sink_id, self.__output_id = ids
        return True

    # ── Live changes ──────────────────────────────────────────────

    async def set_gains(self, gains: dict) -> bool:
        '''
        Retunes the running chain in place — no restart, no gap in the audio.
        Arguments:
            gains (dict): Gain key -> dB.
        '''
        if not self.running:
            return False
        params = " ".join(f'"{filter_name(key)}:Gain" {float(gains.get(key) or 0):.1f}'
                          for key in GAIN_KEYS)
        rc, _ = await run_command(
            ["pw-cli", "set-param", str(self.__sink_id), "Props", f"{{ params = [ {params} ] }}"]
        )
        if rc != 0:
            logger.warning("pw-cli could not retune the equalizer")
            return False
        try:
            # A respawn starts from the file, so it must not bring old gains back.
            self.__conf_path.write_text(_chain_config(gains), encoding="utf-8")
        except OSError as e:
            logger.debug("Could not update the equalizer configuration: %s", e)
        return True

    async def set_target(self, target: str) -> bool:
        '''
        Points the chain's output at another sink, live.  The `target.object`
        metadata is what WirePlumber follows (measured on 0.4.17); when that sink
        goes away the chain falls back to the next one rather than going silent.
        Arguments:
            target (str): node.name of the output; "" clears the choice.
        '''
        if self.__output_id is None:
            return False
        if target:
            argv = ["pw-metadata", str(self.__output_id), "target.object", target]
        else:
            argv = ["pw-metadata", "-d", str(self.__output_id), "target.object"]
        rc, _ = await run_command(argv)
        if rc != 0:
            logger.warning("pw-metadata could not point the equalizer at %s", target or "the default")
            return False
        return True

    # ── Internals ─────────────────────────────────────────────────

    async def __find_nodes(self) -> tuple[int, int] | tuple[()] | None:
        '''
        The live ids of the chain's sink and output; () while either is missing
        from the graph; None when the graph could not be read at all.
        '''
        rc, out = await run_command(["pw-dump"])
        objects = parse_pw_dump(out) if rc == 0 else None
        if objects is None:
            return None
        found = {}
        for obj in objects:
            if obj.get("type") != "PipeWire:Interface:Node":
                continue
            name = ((obj.get("info") or {}).get("props") or {}).get("node.name")
            if name in (SINK_NAME, OUTPUT_NAME):
                found[name] = obj.get("id")
        if SINK_NAME in found and OUTPUT_NAME in found:
            return found[SINK_NAME], found[OUTPUT_NAME]
        return ()

    async def __stop_stale(self) -> None:
        '''
        Ends a chain an earlier run left behind (one started without setpriv,
        whose backend died), recognised by the pid file AND its command line, so
        a recycled pid belonging to anything else is never signalled.
        '''
        try:
            pid = int(self.__pid_path.read_text(encoding="utf-8").strip())
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes()
        except (OSError, ValueError):
            return
        if str(self.__conf_path).encode() not in cmdline:
            return
        logger.info("Stopping an equalizer left by an earlier run (pid %d)", pid)
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return
        for _ in range(10):
            await asyncio.sleep(0.1)
            if not Path(f"/proc/{pid}").exists():
                return

    @staticmethod
    async def __log_stderr(process: asyncio.subprocess.Process) -> None:
        '''
        Forwards what the chain prints (errors only, by its log level) to this
        log, where the Järjestelmän tila card counts it.  Read continuously, so
        a full pipe can never stall the chain.
        Arguments:
            process (Process): The chain process.
        '''
        stream = process.stderr
        if stream is None:
            return
        while True:
            line = await stream.readline()
            if not line:
                return
            text = line.decode("utf-8", "replace").rstrip()
            if text:
                logger.warning("pipewire: %s", text)


def _runtime_dir() -> Path:
    '''The per-user directory for the chain's configuration and pid file.'''
    base = os.environ.get("XDG_RUNTIME_DIR")
    if base:
        return Path(base) / "tesla-homedash"
    return Path(tempfile.gettempdir()) / f"tesla-homedash-{os.getuid()}"


def _chain_config(gains: dict) -> str:
    '''
    The `pipewire -c` configuration: a bare client context (the same modules as
    the stock filter-chain.conf) plus one filter-chain — the bass shelf, then the
    five peaking bands, in series.  audio.channels = 2 makes PipeWire run the
    one-channel graph once per channel.
    Arguments:
        gains (dict): Gain key -> dB, the filters' starting values.
    '''
    def node(name: str, label: str, freq: float, q: float, gain: float) -> str:
        '''
        One built-in biquad filter of the graph.
        Arguments:
            name (str): Filter name, the prefix of its "<name>:Gain" control.
            label (str): Built-in filter type, e.g. "bq_peaking".
            freq (float): Centre or corner frequency in Hz.
            q (float): Filter Q.
            gain (float): Starting gain in dB.
        '''
        return (f'{{ type = builtin name = {name} label = {label} '
                f'control = {{ "Freq" = {freq:.1f} "Q" = {q:.2f} "Gain" = {gain:.1f} }} }}')

    def gain(key: str) -> float:
        '''
        One gain from the dict, 0 when absent.
        Arguments:
            key (str): One of GAIN_KEYS.
        '''
        return float(gains.get(key) or 0)

    nodes = [node("bass", "bq_lowshelf", _BASS_FREQ, _BASS_Q, gain(BASS_KEY))]
    nodes += [node(key, "bq_peaking", freq, _BAND_Q, gain(key)) for key, freq in BANDS]
    names = ["bass"] + [key for key, _ in BANDS]
    links = [f'{{ output = "{a}:Out" input = "{b}:In" }}' for a, b in zip(names, names[1:])]
    nl = "\n                    "
    return f'''# Written by Tesla-Homedash's audio service on every start; edits are lost.
context.properties = {{
    log.level = 1
}}
context.spa-libs = {{
    audio.convert.* = audioconvert/libspa-audioconvert
    support.*       = support/libspa-support
}}
context.modules = [
    {{ name = libpipewire-module-rt args = {{ }} flags = [ ifexists nofail ] }}
    {{ name = libpipewire-module-protocol-native }}
    {{ name = libpipewire-module-client-node }}
    {{ name = libpipewire-module-adapter }}
    {{ name = libpipewire-module-filter-chain
        args = {{
            node.description = "Tesla-Homedash EQ"
            media.name       = "Tesla-Homedash EQ"
            filter.graph = {{
                nodes = [
                    {nl.join(nodes)}
                ]
                links = [
                    {nl.join(links)}
                ]
            }}
            audio.channels = 2
            audio.position = [ FL FR ]
            capture.props = {{
                node.name   = "{SINK_NAME}"
                media.class = Audio/Sink
            }}
            playback.props = {{
                node.name    = "{OUTPUT_NAME}"
                node.passive = true
            }}
        }}
    }}
]
'''
