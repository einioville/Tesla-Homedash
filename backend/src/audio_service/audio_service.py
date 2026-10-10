'''
Host audio for the dashboard: the system volume and which output it plays out of.

Owned by the backend rather than the UI because these are system calls, and
because the audio hardware belongs to the machine the backend runs on — the same
machine that runs libVLC for the radio and, usually, spotifyd.

Both values are ordinary `config.json` keys applied through the Options view's
existing hook machinery, so the whole feature costs no protocol code and no
frontend change.  Persisting them is also what makes the dashboard come back at
the volume it was left at after a power cut.

The equalizer (equalizer.py) sits in the same service because it changes what
both of those mean while it runs: the default output becomes its own virtual
sink, the chosen output becomes where IT plays, and the volume has to be set on
that real output by name rather than on "the default".
'''

import asyncio
import logging

from .audio_backend import AudioBackend, AudioDevice, NullAudioBackend, detect_backend
from .equalizer import GAIN_KEYS, SINK_NAME, PipeWireEqualizer, is_flat

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
        self.__eq_gains = {key: audio.get(key) or 0 for key in GAIN_KEYS}
        # None until run() has found PipeWire; stays None on a host without it.
        self.__equalizer: PipeWireEqualizer | None = None
        # What the Options view's equalizer is told (equalizer_runtime):
        # detecting -> unavailable | off | on, and failed when a start did not
        # come up.  Only a start retries a failed one; the timer does not.
        self.__eq_state = "detecting"
        # The apply paths — a hook, the startup push, the timer's health check —
        # all await subprocesses, so without this two of them could interleave
        # a start with a stop.
        self.__lock = asyncio.Lock()
        # Set by attach_config_service().  ConfigService is built after this
        # service, because it takes this service's hook, options and guard.
        self.__config_service = None

    def attach_config_service(self, config_service) -> None:
        '''
        Gives the service the write path it uses to store the host's volume on
        first start.  Called from start_services once ConfigService exists.
        Arguments:
            config_service (ConfigService): Performs the audio.volumePercent write
                with the same validation, atomic save and schema broadcast a
                CONFIG_SET gets.
        '''
        self.__config_service = config_service

    # ── Lifecycle ─────────────────────────────────────────────────

    async def run(self) -> None:
        '''
        Detects the host's audio stack once, pushes the configured settings so a
        reboot restores them, then refreshes the device list on a timer.  Runs
        forever, so gathering it unconditionally is safe.
        '''
        self.__backend = await detect_backend()
        await self.__refresh_devices()
        # The chain is switched in by making it the default output, which only a
        # stack that can switch outputs at runtime can do.
        if self.__backend.supports_device_selection and await PipeWireEqualizer.detect():
            self.__equalizer = PipeWireEqualizer()
        else:
            logger.info("No PipeWire server; the equalizer is unavailable")
        async with self.__lock:
            self.__eq_state = "unavailable" if self.__equalizer is None else "off"
            await self.__restore_stale_default()
            # Before the device and volume, which both depend on whether the
            # chain runs.
            await self.__sync_equalizer()
            # force: nothing has been pushed at the host yet this boot, so even an
            # "unchanged" device has to be applied to make the stored value true.
            if self.__volume_is_stored():
                await self.__apply(self.__output_device, self.__volume_percent, force=True)
            else:
                await self.__apply(self.__output_device, None, force=True)
        if not self.__volume_is_stored():
            await self.__adopt_host_volume()
        # A view opened before detection finished was told "detecting".
        if self.__config_service is not None:
            await self.__config_service.broadcast_schema()

        while True:
            await asyncio.sleep(_DEVICE_REFRESH_SECONDS)
            await self.__refresh_devices()
            await self.__check_equalizer()

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
        async with self.__lock:
            await self.__apply(audio.get("outputDevice") or "", audio.get("volumePercent"))

    async def apply_equalizer(self) -> None:
        '''
        Re-snapshots the equalizer gains and applies them: retunes a running
        chain in place, starts it when the curve leaves flat, stops it when the
        curve returns to flat.  The "equalizer" hook.
        '''
        audio = self.__config.audio_config
        async with self.__lock:
            self.__eq_gains = {key: audio.get(key) or 0 for key in GAIN_KEYS}
            await self.__sync_equalizer()

    def equalizer_runtime(self) -> dict:
        '''
        The equalizer's state for the Options view, merged into its entries as
        "runtime": whether this host can run it at all, and whether it runs.
        '''
        return {"state": self.__eq_state}

    def health(self) -> dict:
        '''The host audio stack and what it is set to, for the Järjestelmän tila card.'''
        names = {"pulse": "PulseAudio / PipeWire (pactl)", "wireplumber": "PipeWire (wpctl)",
                 "alsa": "ALSA (amixer)"}
        if self.__backend.name == "none":
            return {"state": "off", "detail": "Äänijärjestelmää ei löytynyt"}
        label = next((d.label for d in self.__devices if d.identifier == self.__output_device), "")
        volume = self.__volume_percent
        equalizer = {"on": "Päällä", "off": "Pois (tasainen)", "failed": "Ei käynnistynyt",
                     "unavailable": "Ei saatavilla (vaatii PipeWiren)"}
        config = [
            ["Järjestelmä", names.get(self.__backend.name, self.__backend.name)],
            ["Ulostulo", label or self.__output_device or "Järjestelmän oletus"],
            ["Äänenvoimakkuus", f"{volume} %" if volume is not None else "—"],
            ["Taajuuskorjain", equalizer.get(self.__eq_state, "—")],
        ]
        if self.__eq_state == "failed":
            return {"state": "warn", "detail": "Taajuuskorjain ei käynnistynyt", "config": config}
        return {"state": "ok", "detail": "Käytössä", "config": config}

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
        return [{"value": "", "label": "Oletuslaite"}] + [
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

    def guard_equalizer(self, key: str, value) -> None:
        '''
        Rejects an equalizer write on a host that cannot run the chain — once
        detection has said so; a write in the first moments after start-up is
        let through and applied when detection finishes.
        Arguments:
            key (str): Dotted config key being written.
            value: Already-coerced candidate value.
        '''
        if self.__eq_state == "unavailable":
            raise ValueError("Taajuuskorjain vaatii PipeWire-äänijärjestelmän")

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
        changed = force or device != self.__output_device
        self.__output_device = device
        equalizer = self.__equalizer
        if equalizer is not None and equalizer.running:
            # The chain is the default output and stays so; the choice moves
            # where the chain plays instead.
            if changed:
                await equalizer.set_target(self.__equalizer_target())
        elif device and changed:
            await self.__backend.set_default_device(device)
            await self.__refresh_devices()

        if volume is not None:
            self.__volume_percent = volume
            await self.__apply_volume()

    async def __apply_volume(self) -> None:
        '''
        Sets the stored volume on the output actually playing: the default one,
        or — while the equalizer runs, and so IS the default — the real output
        behind it.  The chain's own sink stays at 100 %, so the dashboard's
        volume means the same thing with the equalizer on or off, and a chain
        that dies leaves the real output at the user's level, not at full.
        '''
        if self.__volume_percent is None:
            return
        clamped = max(0, min(100, int(self.__volume_percent)))
        device = self.__equalizer_target() if self.__eq_running() else None
        await self.__backend.set_volume(clamped, device or None)

    # ── Equalizer ─────────────────────────────────────────────────

    def __eq_running(self) -> bool:
        '''Whether the equalizer chain is up.'''
        return self.__equalizer is not None and self.__equalizer.running

    def __equalizer_target(self) -> str:
        '''
        Where the chain plays: the chosen output, else the host's own default
        from before the chain took the default over.  Never left to
        WirePlumber, which would pick by priority — moving the sound from the
        HDMI output the user chose on the desktop to the headphone jack, say.
        '''
        return self.__output_device or self.__host_default() or ""

    def __host_default(self) -> str | None:
        '''The host default remembered while the chain runs (see __remember_host_default).'''
        return self.__config.audio_config.get("hostDefaultDevice") or None

    async def __remember_host_default(self) -> None:
        '''
        Stores the host's default output before the chain replaces it, as
        audio.hostDefaultDevice — state, not a setting, written straight through
        Config like the radio's last station.  It has to survive a restart: once
        the chain has run, WirePlumber remembers IT as the default, so after a
        power cut the host's own choice can no longer be read back.  An existing
        value is kept for that reason.
        '''
        if self.__host_default():
            return
        current = await self.__backend.get_default_device()
        if not current or current == SINK_NAME:
            return
        self.__store_host_default(current)

    def __store_host_default(self, value: str | None) -> None:
        '''
        Writes audio.hostDefaultDevice and saves.  A failed save is logged; the
        value still holds in memory for this run.
        Arguments:
            value (str | None): The host default's node name, or None to clear.
        '''
        if self.__config.audio_config.get("hostDefaultDevice") == value:
            return
        self.__config.set("audio.hostDefaultDevice", value)
        try:
            self.__config.save()
        except OSError as e:
            logger.warning("Could not save the host's default output: %s", e)

    async def __restore_default(self) -> None:
        '''
        Hands the default output back from the chain: to the chosen output, else
        to the host default it replaced, then forgets that.  Called BEFORE the
        chain stops, so its streams move straight to the right output instead of
        via whichever sink WirePlumber would fall back to.
        '''
        restore = self.__output_device or self.__host_default()
        if restore:
            await self.__backend.set_default_device(restore)
        self.__store_host_default(None)

    async def __restore_stale_default(self) -> None:
        '''
        At start-up with a flat curve: a remembered host default means the last
        run had the chain up and never handed the default back (a power cut, a
        crash).  WirePlumber still names the chain as the default and will fall
        back by priority, so the remembered output is put back now.
        '''
        if self.__equalizer is None or not is_flat(self.__eq_gains) or not self.__host_default():
            return
        logger.info("Restoring the default output the equalizer replaced last run")
        await self.__restore_default()

    async def __sync_equalizer(self) -> None:
        '''
        Brings the chain in line with the gains: started when the curve is not
        flat, retuned while it runs, stopped when the curve is flat again.  A
        flat curve runs no chain at all, so a host where nobody touches the
        equalizer keeps exactly the audio path it had.  Call under the lock.
        '''
        if self.__equalizer is None:
            return
        flat = is_flat(self.__eq_gains)
        if not flat and not self.__equalizer.running:
            await self.__remember_host_default()
            if await self.__equalizer.start(self.__eq_gains, self.__equalizer_target()):
                await self.__backend.set_default_device(SINK_NAME)
                await self.__apply_volume()
                self.__eq_state = "on"
            else:
                # Also covers a chain left as WirePlumber's default by the last
                # run: the default goes back to a real output either way.
                await self.__restore_default()
                self.__eq_state = "failed"
        elif not flat:
            await self.__equalizer.set_gains(self.__eq_gains)
        elif self.__equalizer.running:
            await self.__restore_default()
            await self.__equalizer.stop()
            await self.__apply_volume()
            self.__eq_state = "off"
        else:
            self.__eq_state = "off"

    async def __check_equalizer(self) -> None:
        '''
        The timer's health check: a chain that should run but has died or left
        the graph (a PipeWire restart) is started again, once per loss.  A start
        that failed is not retried here — the next equalizer write retries it —
        so a host where it cannot work does not log a failure every 15 s.
        '''
        if self.__equalizer is None or self.__eq_state != "on":
            return
        async with self.__lock:
            if self.__eq_state != "on" or await self.__equalizer.check():
                return
            logger.warning("The equalizer stopped unexpectedly; starting it again")
            await self.__equalizer.stop()
            await self.__sync_equalizer()
        if self.__config_service is not None:
            await self.__config_service.broadcast_schema()

    def __volume_is_stored(self) -> bool:
        '''
        Whether config.json holds a volume of its own, as opposed to the
        _AUDIO_DEFAULTS value that audio_config merges in when it does not.
        '''
        block = self.__config.get("audio")
        return isinstance(block, dict) and block.get("volumePercent") is not None

    async def __adopt_host_volume(self) -> None:
        '''
        First start with no stored volume: takes the host's current volume as
        the setting instead of pushing the schema default over a level the user
        chose on this device.  Stored through ConfigService, so the Options view
        shows the real level and a reboot restores it; from then on the value is
        the user's and the startup force-apply is right.  An unreadable volume is
        left exactly as it is.
        '''
        # The real output's level: a running chain is the default, and its own
        # sink is always at 100 %.
        device = self.__equalizer_target() if self.__eq_running() else None
        volume = await self.__backend.get_volume(device or None)
        if volume is None:
            logger.info("No stored volume and the host's cannot be read; leaving it as it is")
            return
        # pactl and wpctl report overdrive above 100 %; the setting cannot hold it.
        volume = max(0, min(100, volume))
        self.__volume_percent = volume
        if self.__config_service is None:
            return
        result = await self.__config_service.apply_write("audio.volumePercent", volume)
        if result["ok"] and result["applied"] == "unchanged":
            # Equal to the default, so there is nothing to persist; the next start
            # adopts the host's level again, which is still the right behaviour.
            logger.info("Host volume (%d%%) already matches the setting", volume)
        elif result["ok"]:
            logger.info("Adopted the host's current volume (%d%%) as the stored setting", volume)
        else:
            logger.warning("Could not store the host's volume (%d%%): %s",
                           volume, result["message"])

    async def __refresh_devices(self) -> None:
        '''
        Re-reads the selectable outputs, so hotplugged devices appear.  The
        equalizer's own sink is never one: choosing it would point the chain at
        itself.
        '''
        self.__devices = [device for device in await self.__backend.list_devices()
                          if device.identifier != SINK_NAME]
