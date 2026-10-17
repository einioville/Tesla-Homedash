'''
The Media view's spectrum: what the host is playing, as the level of BANDS
log-spaced frequency bands, FRAME_HZ times a second, to the displays watching
(MEDIA_SPECTRUM_WATCH / MEDIA_SPECTRUM).

The sound is recorded from the default output's monitor with pw-record, so it
is whatever reaches the speakers — the radio and Spotify alike. The recording
runs only while some display watches.
'''
import asyncio
import logging
import shutil

import numpy as np

from ..utils import protocol

logger = logging.getLogger("audio_service.spectrum")

RATE = 48000
FRAME_HZ = 30
HOP = RATE // FRAME_HZ
# 85 ms of sound per analysis: fine enough at the low end (11.7 Hz per bin)
# for the bass bands to move separately, short enough to follow a beat.
WINDOW = 4096
BANDS = 40
LOW_HZ = 40.0
HIGH_HZ = 16000.0

# Levels map a RANGE_DB window under a ceiling that follows the loudest band:
# up at once, down by CEILING_FALL_DB a second, so quiet and loud recordings
# both fill the height. It never falls below MIN_CEILING_DB, or near-silence
# would be stretched into a full-height line.
RANGE_DB = 32.0
CEILING_FALL_DB = 3.0
MIN_CEILING_DB = -40.0

# With nothing playing a passive recording receives nothing; after this long
# without sound the watchers get one flat frame and then nothing until it returns.
QUIET_S = 0.25
RESTART_DELAY_S = 5.0


def _band_weights() -> np.ndarray:
    '''
    A BANDS × bins matrix that sums the FFT's power into log-spaced bands from
    LOW_HZ to HIGH_HZ, each bin weighted by how much of the band it covers.  A band
    narrower than a bin (the lowest ones) reads the power at its centre,
    interpolated between the two nearest bins, so neighbours there still differ.
    '''
    edges = np.geomspace(LOW_HZ, HIGH_HZ, BANDS + 1)
    hz_per_bin = RATE / WINDOW
    weights = np.zeros((BANDS, WINDOW // 2 + 1))
    for band, (low, high) in enumerate(zip(edges[:-1], edges[1:])):
        width = (high - low) / hz_per_bin
        if width < 1.0:
            centre = np.sqrt(low * high) / hz_per_bin
            below = int(centre)
            frac = centre - below
            weights[band, below] = (1.0 - frac) * width
            weights[band, below + 1] = frac * width
            continue
        for k in range(int(low / hz_per_bin), int(high / hz_per_bin) + 2):
            overlap = min(high, (k + 0.5) * hz_per_bin) - max(low, (k - 0.5) * hz_per_bin)
            if overlap > 0:
                weights[band, k] = overlap / hz_per_bin
    return weights


class SpectrumAnalyser:
    '''
    Turns blocks of mono samples into band levels (0-1).  Kept apart from the
    recording so it can be fed from a file.
    '''

    def __init__(self):
        self.__samples = np.zeros(WINDOW, dtype=np.float32)
        self.__window = np.hanning(WINDOW).astype(np.float32)
        self.__weights = _band_weights()
        # A full-scale sine through the Hann window peaks at WINDOW/4 in the FFT,
        # so this scale reads it as 0 dB.
        self.__scale = (4.0 / WINDOW) ** 2
        self.__ceiling = MIN_CEILING_DB

    def reset(self) -> None:
        '''Forgets the sound so far, for a recording that starts over.'''
        self.__samples[:] = 0
        self.__ceiling = MIN_CEILING_DB

    def feed(self, block: np.ndarray) -> np.ndarray:
        '''
        Adds a block of samples and returns the band levels over the last WINDOW.
        Arguments:
            block (ndarray): float32 mono samples, -1..1, at RATE.
        '''
        n = min(len(block), WINDOW)
        self.__samples = np.roll(self.__samples, -n)
        self.__samples[-n:] = block[-n:]
        power = np.abs(np.fft.rfft(self.__samples * self.__window)) ** 2 * self.__scale
        # Summed, not averaged: the bands widen with frequency as music's energy
        # thins out, so a roughly pink spectrum comes out roughly level.
        bands = self.__weights @ power
        db = 10.0 * np.log10(bands + 1e-12)
        dt = n / RATE
        self.__ceiling = max(float(db.max()), self.__ceiling - CEILING_FALL_DB * dt, MIN_CEILING_DB)
        return np.clip((db - (self.__ceiling - RANGE_DB)) / RANGE_DB, 0.0, 1.0)


def spectrum_frame(levels: np.ndarray) -> bytes:
    '''
    MEDIA_SPECTRUM: count(1B) + count × level(1B, 0-255).
    Arguments:
        levels (ndarray): Band levels, 0-1.
    '''
    body = bytes([len(levels)]) + bytes(np.round(levels * 255).astype(np.uint8))
    return protocol.frame(protocol.MEDIA_SPECTRUM, body)


class AudioSpectrum:
    '''
    Serves MEDIA_SPECTRUM_WATCH: records the default output's monitor while at
    least one display watches and sends each one MEDIA_SPECTRUM frames.
    Arguments:
        server (Server): Delivers the frames to the watchers.
    '''

    def __init__(self, server):
        self.__server = server
        self.__watchers: set = set()
        self.__task: asyncio.Task | None = None
        self.__analyser = SpectrumAnalyser()
        self.__missing_logged = False

    async def handle_watch(self, payload: bytes, writer) -> None:
        '''
        MEDIA_SPECTRUM_WATCH: on(1B) — 1 while the display shows the spectrum, 0
        when it stops.  The display sends it again after a reconnect.
        Arguments:
            payload (bytes): The on byte.
            writer (StreamWriter): The display.
        '''
        if payload[:1] == b"\x01":
            self.__watchers.add(writer)
        else:
            self.__watchers.discard(writer)
        self.__update()

    def __update(self) -> None:
        '''Starts the recording for the first watcher; it ends by itself after the last.'''
        if self.__watchers and (self.__task is None or self.__task.done()):
            self.__task = asyncio.create_task(self.__run())

    def __prune(self) -> None:
        '''
        Drops watchers whose connection has gone: the server swallows a write to a
        dead display, so nothing else would ever tell.
        '''
        self.__watchers = {w for w in self.__watchers if not w.is_closing()}

    async def __run(self) -> None:
        '''Records and analyses until nobody watches, restarting a recording that dies.'''
        if not shutil.which("pw-record"):
            if not self.__missing_logged:
                logger.warning("No pw-record on this host: the spectrum stays flat")
                self.__missing_logged = True
            return
        while True:
            self.__prune()
            if not self.__watchers:
                return
            await self.__record()
            self.__prune()
            if not self.__watchers:
                return
            await asyncio.sleep(RESTART_DELAY_S)

    async def __record(self) -> None:
        '''One pw-record process, read until it ends or nobody watches.'''
        # Passive: the recording never keeps an idle output awake.  Mono, so
        # PipeWire mixes the channels down.
        argv = ["pw-record", "-P",
                "{ stream.capture.sink = true node.passive = true "
                "node.name = tesla_homedash_spectrum }",
                "--format", "f32", "--rate", str(RATE), "--channels", "1",
                "--latency", f"{1000 // FRAME_HZ}ms", "-"]
        # As the equalizer's chain: never outlive the backend.
        if shutil.which("setpriv"):
            argv = ["setpriv", "--pdeathsig", "TERM", "--"] + argv
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except OSError as e:
            logger.warning("Could not start the spectrum recording: %s", e)
            return
        logger.info("Spectrum recording started")
        self.__analyser.reset()
        quiet = True
        try:
            while True:
                self.__prune()
                if not self.__watchers:
                    break
                try:
                    data = await asyncio.wait_for(
                        process.stdout.readexactly(HOP * 4), timeout=QUIET_S)
                except asyncio.TimeoutError:
                    if not quiet:
                        quiet = True
                        await self.__send(spectrum_frame(np.zeros(BANDS)))
                    continue
                except asyncio.IncompleteReadError:
                    logger.warning("The spectrum recording ended (exit code %s)",
                                   process.returncode)
                    break
                levels = self.__analyser.feed(np.frombuffer(data, dtype="<f4"))
                if levels.any() or not quiet:
                    quiet = not levels.any()
                    await self.__send(spectrum_frame(levels))
        finally:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
            logger.info("Spectrum recording stopped")

    async def __send(self, packet: bytes) -> None:
        '''
        Sends one frame to every watcher.
        Arguments:
            packet (bytes): A framed MEDIA_SPECTRUM.
        '''
        await asyncio.gather(*(self.__server.send_to(w, packet) for w in list(self.__watchers)))
