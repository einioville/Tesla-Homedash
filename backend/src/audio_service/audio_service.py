'''
Host audio for the dashboard: the system volume and which output it plays out of.

Owned by the backend rather than the UI because these are system calls, and
because the audio hardware belongs to the machine the backend runs on — the same
machine that runs libVLC for the radio and, usually, spotifyd.

Both values are ordinary `config.json` keys applied through the Options view's
existing hook machinery, so the whole feature costs no protocol code and no
frontend change.  Persisting them is also what makes the dashboard come back at
the volume it was left at after a power cut.
'''

import asyncio
import logging

from .audio_backend import AudioBackend, AudioDevice, NullAudioBackend, detect_backend

logger = logging.getLogger("audio_service.audio_service")

# Outputs come and go (HDMI hotplug, a Bluetooth speaker connecting), so the list
# offered by the Options view is refreshed rather than read once at startup.
_DEVICE_REFRESH_SECONDS = 15.0


class AudioService:
    '''
    Applies the configured system volume and output device, and supplies the
    Options view's device list.

    Always constructed: detection is two cheap subprocess probes and needs no
    credentials, and a deployment with no controllable audio stack must be able
    to SAY so rather than silently accept writes that do nothing.
    Arguments:
        config (Config): Shared configuration.  The audio block is snapshotted
            here and re-read only in apply_config(), like every other service.
    '''

    def __init__(self, config):
        self.__config = config
        self.__backend: AudioBackend = NullAudioBackend()
        self.__devices: list[AudioDevice] = []
        audio = config.audio_config
        self.__volume_percent = audio.get("volumePercent")
        self.__output_device = audio.get("outputDevice") or ""

    # ── Lifecycle ─────────────────────────────────────────────────

    async def run(self) -> None:
        '''
        Detects the host's audio stack once, pushes the configured settings so a
        reboot restores them, then refreshes the device list on a timer.  Runs
        forever, so gathering it unconditionally is safe.
        '''
        self.__backend = await detect_backend()
        await self.__refresh_devices()
        # force: nothing has been pushed at the host yet this boot, so even an
        # "unchanged" device has to be applied to make the stored value true.
        await self.__apply(self.__output_device, self.__volume_percent, force=True)

        while True:
            await asyncio.sleep(_DEVICE_REFRESH_SECONDS)
            await self.__refresh_devices()

    def get_run_task(self):
        '''Returns the run task for start_services to gather.'''
        return asyncio.create_task(self.run())

    # ── Config ────────────────────────────────────────────────────

    async def apply_config(self) -> None:
        '''
        Re-snapshots the audio block and pushes it at the host.  Async on
        purpose: ConfigService awaits a hook's result, so the CONFIG_SET_RESULT
        the user sees reflects a real apply rather than a scheduled one.
        '''
        audio = self.__config.audio_config
        await self.__apply(audio.get("outputDevice") or "", audio.get("volumePercent"))

    def device_options(self) -> list[dict]:
        '''
        Enum choices for `audio.outputDevice`, read from the cached device list.
        Synchronous because ConfigService.build_schema() is.

        Empty when the stack cannot switch outputs at runtime (ALSA, or no stack
        at all), which makes ConfigService's existing membership check reject any
        write to that key for free.
        '''
        if not self.__backend.supports_device_selection:
            return []
        # "" is the way back to "leave the host's own default alone".
        # SettingSelect has no clear button — only the numeric editors do — so a
        # sentinel option is the only route back, which is why this key is a
        # plain enum rather than nullable.
        return [{"value": "", "label": "Järjestelmän oletus"}] + [
            {"value": device.identifier, "label": device.label} for device in self.__devices
        ]

    def guard_write(self, key: str, value) -> None:
        '''
        Rejects a write that could not possibly take effect on this host.

        Distinct from a hook: a hook runs after the value is already on disk and
        its failure is swallowed, so a guard is the only place an honest "this
        cannot work here" reaches the user.
        Arguments:
            key (str): Dotted config key being written.
            value: Already-coerced candidate value.
        '''
        if self.__backend.name == "none":
            raise ValueError(
                "Ääntä ei voi ohjata: tuettua äänijärjestelmää ei löytynyt "
                "(pactl, wpctl ja amixer puuttuvat)"
            )
        if key == "audio.outputDevice" and not self.__backend.supports_device_selection:
            raise ValueError("Toistolaitetta ei voi vaihtaa ALSA-järjestelmässä ajon aikana")

    # ── Internals ─────────────────────────────────────────────────

    async def __apply(self, device: str, volume, force: bool = False) -> None:
        '''
        Pushes device then volume at the host.

        ORDER MATTERS: a sink carries its OWN volume, so switching the output and
        not re-applying the volume makes the user's setting silently stop
        holding.  Device first, volume second, always — which also closes the one
        real drift path between config.json and the live system.
        Arguments:
            device (str): Target output identifier; "" leaves the host default.
            volume: Target volume percent, or None to leave it alone.
            force (bool): Apply the device even when it has not changed.  Only
                the startup push does; a volume-only edit must not spawn a
                needless sink switch.
        '''
        if device and (force or device != self.__output_device):
            await self.__backend.set_default_device(device)
            await self.__refresh_devices()
        self.__output_device = device

        if volume is not None:
            clamped = max(0, min(100, int(volume)))
            await self.__backend.set_volume(clamped)
            self.__volume_percent = volume

    async def __refresh_devices(self) -> None:
        '''Re-reads the selectable outputs, so hotplugged devices appear.'''
        self.__devices = await self.__backend.list_devices()
