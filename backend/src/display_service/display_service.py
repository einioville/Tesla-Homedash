'''
Display power control for the panel the dashboard runs on.

The split is deliberate and is the whole reason this lives in the backend:

  - The FRONTEND decides WHEN.  It installs an application-wide event filter and
    is the only side that sees touch input, so it owns the inactivity countdown.
  - The BACKEND does the SWITCHING.  Talking to the system is the backend's job;
    the UI process should not be spawning host commands.

The panel is driven through wlopm, the wlr-output-power-management client used by
the Raspberry Pi's Wayland session.  Power management is an OUTPUT concern only,
so the touchscreen keeps delivering input while the panel is dark — which is what
lets a tap wake it.  An output the compositor drops after a long blank (#43) is
brought back with modesets through wlr-randr, which wlopm cannot do.

Deployment note: both clients need the Wayland socket.  The backend runs as a
`systemd --user` unit under the same user as the compositor, so XDG_RUNTIME_DIR
is already in its environment; WAYLAND_DISPLAY may not be, and the unit should
set it (see README).  With no wlopm on PATH the service reports itself
unavailable and every request is a no-op, so a headless or X11 host degrades
quietly instead of failing every timeout.  With no wlr-randr a dropped output is
reported and not recovered.
'''

import asyncio
import json
import logging
import shutil
import time
from dataclasses import dataclass

from ..utils import process, protocol

logger = logging.getLogger("display_service")

# The wlr-output-power-management client. Looked up on PATH so a non-standard
# install location still works.
_COMMAND = "wlopm"

# The wlr-output-management client: reads the outputs' modes and sets them.
_RANDR = "wlr-randr"

# wlopm's "every output" selector. Passed as a plain argv entry — there is no
# shell involved, so there is nothing to glob-expand it.
_ALL_OUTPUTS = "*"

# A wlopm or wlr-randr run is milliseconds of work; anything beyond this means
# the compositor is not answering, and waiting longer only holds the lock
# against the next power request.
_RUN_TIMEOUT_SECONDS = 5.0

# The wait after each modeset of a recovery, before the next one or the check.
# The reference Pi's panel shows the outcome within it.
_SETTLE_SECONDS = 2.0

# What `wlopm --json` says about the outputs, read after a power-on or a refused
# change.
_LIT = "lit"
_MISSING = "missing"    # gone from the compositor: the labwc 0.20 wedge (#43)
_DARK = "dark"          # present but still reporting off
_UNKNOWN = "unknown"    # no usable answer; never reported as a fault


@dataclass(frozen=True)
class _Output:
    '''
    An output as it was while lit, which is what a recovery restores.
    Arguments:
        name (str): The compositor's name for it, e.g. "HDMI-A-1".
        native (str): Its mode then, as wlr-randr takes it ("1280x800@60.023998").
        kick (str | None): Another mode it lists, for the modeset that revives a
            dropped output; None when it lists only one.
    '''
    name: str
    native: str
    kick: str | None


def _mode_text(mode: dict) -> str:
    '''
    A `wlr-randr --json` mode as `--mode` takes it, in the form wlr-randr prints,
    so the refresh matches the listed mode exactly.
    Arguments:
        mode (dict): {"width": int, "height": int, "refresh": float, ...}.
    '''
    return f"{int(mode['width'])}x{int(mode['height'])}@{float(mode['refresh']):.6f}"


def _resolution(mode: str) -> str:
    '''
    "1280x800@60.023998" → "1280×800", for the status card.
    Arguments:
        mode (str): A mode from _mode_text().
    '''
    return mode.split("@", 1)[0].replace("x", "×")


def _outputs_from(entries) -> list:
    '''
    The enabled outputs in a `wlr-randr --json` answer, each with its current
    mode and a kick mode.  The kick is another resolution where one is listed:
    1920x1080 is what revives the reference Pi's 1280x800 panel, and a modeset
    to another refresh at the same size was never tried.  Entries in a shape
    this does not recognise are skipped.
    Arguments:
        entries: The parsed answer; anything but a list gives no outputs.
    '''
    outputs = []
    if not isinstance(entries, list):
        return outputs
    for entry in entries:
        try:
            if not entry.get("enabled"):
                continue
            modes = entry["modes"]
            current = next((m for m in modes if m.get("current")), None)
            if current is None:
                continue
            size = (current["width"], current["height"])
            others = [m for m in modes if m is not current]
            kick = next((m for m in others if (m["width"], m["height"]) != size),
                        others[0] if others else None)
            outputs.append(_Output(str(entry["name"]), _mode_text(current),
                                   _mode_text(kick) if kick else None))
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
    return outputs


class DisplayService:
    '''
    Serves DISPLAY_SET_POWER and snapshots DISPLAY_POWER_STATE to new clients.

    Arguments:
        server (Server): TLS server used to reply to and broadcast at clients.
    '''

    def __init__(self, server):
        self.__server = server
        # Resolved once: a host either has the clients or it does not, and
        # re-probing on every request would just add a stat() per timeout.
        self.__available = shutil.which(_COMMAND) is not None
        self.__can_recover = shutil.which(_RANDR) is not None
        # Assumed on at startup. A fresh backend implies a fresh session, and the
        # first thing run() does is make that true rather than merely assume it.
        self.__on = True
        # Why the panel is not doing what was last asked (protocol.DISPLAY_FAULT_*).
        # OUTPUT_LOST is sticky until a recovery works: see set_power().
        self.__fault = protocol.DISPLAY_FAULT_NONE
        # Serialises runs: an off->on flip arriving mid-run must not race the
        # process it is reversing.
        self.__lock = asyncio.Lock()
        # The state the run holding the lock is heading for, None between runs.
        # A recovery takes seconds, and the frontend asks for a wake every 2 s
        # while it is touched; without this the wakes would queue up behind it.
        self.__switching = None
        # The outputs as last seen lit (_Output), what a recovery restores.
        self.__outputs = []
        self.__recoveries = 0
        self.__last_recovery_ms = None
        self.__last_recovery_how = None

        if not self.__available:
            logger.warning(
                "%s not found; display power control disabled (the dashboard's "
                "screen-off setting will have no effect)", _COMMAND
            )
        elif self.__can_recover:
            logger.info("Display power control available via %s (output=%s), recovery of a "
                        "dropped output via %s", _COMMAND, _ALL_OUTPUTS, _RANDR)
        else:
            logger.warning("Display power control available via %s (output=%s), but %s is "
                           "not installed: an output dropped after a blank (#43) cannot be "
                           "recovered", _COMMAND, _ALL_OUTPUTS, _RANDR)

    async def handle_set_power(self, payload: bytes, writer) -> None:
        '''
        Applies a power request from the frontend and replies with the resulting
        state.  A short payload is dropped rather than guessed at.
        Arguments:
            payload (bytes): on(1B) — 1 wakes the panel, 0 powers it down.
            writer (StreamWriter): Requesting client, which gets the state reply.
        '''
        if len(payload) < 1:
            logger.warning("DISPLAY_SET_POWER: payload too short (%d bytes)", len(payload))
            return
        await self.set_power(bool(payload[0]))
        await self.__server.send_to(writer, self.__state_frame())

    async def stream_everything(self, writer) -> None:
        '''
        Snapshots the current power state to a newly connected client, so the
        dashboard learns immediately whether this host can switch the panel at
        all and does not arm a timeout that could never do anything.
        Arguments:
            writer (StreamWriter): The newly connected client.
        '''
        await self.__server.send_to(writer, self.__state_frame())

    async def set_power(self, on: bool) -> None:
        '''
        Powers the panel on or off, if this host can.  Idempotent: a request for
        the state we are already in, or are already switching to, does not
        spawn a process.
        Arguments:
            on (bool): True wakes the panel, False powers it down.
        '''
        if not self.__available or on == self.__on or on == self.__switching:
            return
        if not on and self.__fault == protocol.DISPLAY_FAULT_OUTPUT_LOST:
            # This host has lost its output after a blank and could not bring it
            # back, and on a keyboard-less panel every further power-off risks a
            # black screen that only SSH can undo.  A recovery that works, or a
            # backend restart, allows it again.
            logger.info("Display power-off skipped: the output was lost after an "
                        "earlier wake and not recovered; restart the backend to allow it again")
            return
        before = self.__state_frame()
        was_on = self.__on
        async with self.__lock:
            # A request that waited on the lock may have been met meanwhile.
            if on == self.__on:
                return
            self.__switching = on
            try:
                await self.__switch(on)
            finally:
                self.__switching = None
        if self.__on != was_on:
            logger.info("Display %s", "on" if self.__on else "off")
        if self.__state_frame() != before:
            await self.__server.broadcast(self.__state_frame())

    async def run(self) -> None:
        '''
        Startup task: makes the assumed-on state true.  Without this a backend
        restarting while the panel is dark would leave it dark, with the frontend
        believing it is lit — and the panel only wakes on a touch nobody knows to
        make.  A lit panel's outputs are learned on the way, for a later recovery.

        Records the outcome rather than the intent.  If the power-on fails, the
        panel is whatever `wlopm --json` reports, and OFF when that cannot be
        read: set_power() skips a request for the state it believes the panel
        is already in, so a wrongly assumed "on" would drop every later wake
        silently, while a wrongly assumed "off" only costs one redundant
        wlopm --on.  Clients already connected are told either way.
        '''
        if not self.__available:
            return
        before = self.__state_frame()
        async with self.__lock:
            # Off until the switch proves otherwise.
            self.__on = False
            await self.__switch(True)
        if self.__fault == protocol.DISPLAY_FAULT_REFUSED and self.__available:
            if self.__on:
                logger.warning("Startup display power-on was refused but the panel reports "
                               "lit; %s cannot switch it (a VNC server holding the output "
                               "does this), so screen-off will not work", _COMMAND)
            else:
                logger.warning("Startup display power-on failed; treating the panel as "
                               "off so the next wake request runs %s again", _COMMAND)
        if self.__state_frame() != before:
            await self.__server.broadcast(self.__state_frame())

    def health(self) -> dict:
        '''Panel power control's standing, for the Järjestelmän tila card.'''
        shown = ", ".join(f"{o.name} · {_resolution(o.native)}" for o in self.__outputs)
        config = [["Ohjaus", _COMMAND], ["Näyttö", shown or "Kaikki"],
                  ["Tila", "Päällä" if self.__on else "Sammutettu"]]
        if not self.__available:
            return {"state": "off", "detail": f"{_COMMAND} puuttuu, näytön sammutus ei toimi",
                    "config": config[1:]}
        if not self.__can_recover:
            config.append(["Palautus", f"{_RANDR} puuttuu"])
        else:
            config.append(["Palautuksia", str(self.__recoveries)])
            if self.__last_recovery_ms is not None:
                config.append(["Viimeisin palautus", {"time": self.__last_recovery_ms}])
                config.append(["Palautuskeino", self.__last_recovery_how])
        if self.__fault == protocol.DISPLAY_FAULT_OUTPUT_LOST:
            return {"state": "error", "detail": "Näyttö katosi herätyksen jälkeen eikä palautunut",
                    "config": config}
        if self.__fault == protocol.DISPLAY_FAULT_REFUSED:
            return {"state": "warn", "detail": f"{_COMMAND} kieltäytyi muutoksesta", "config": config}
        return {"state": "ok", "detail": "Käytössä", "config": config}

    def get_run_task(self):
        '''Returns the startup task for start_services to gather.'''
        return asyncio.create_task(self.run())

    async def __switch(self, on: bool) -> None:
        '''
        One power change with its outcome recorded: `__on` follows what actually
        happened and `__fault` says why it did not.  The caller holds the lock.

        A refused change (wlopm exiting non-zero — a VNC server holding the
        output does exactly that, in both directions, #46) leaves the state as
        it was.  A power-on is then CHECKED, because on labwc 0.20 / wlroots
        0.20 a long blank can drop the output from the compositor entirely and
        `wlopm --on *` succeeds against nothing (#43); such an output is
        recovered where it can be.
        Arguments:
            on (bool): True for power-on, False for power-off.
        '''
        if not await self.__run(on):
            if self.__fault != protocol.DISPLAY_FAULT_OUTPUT_LOST:
                self.__fault = protocol.DISPLAY_FAULT_REFUSED
            # A refusal says nothing about the panel, so ask — a VNC server
            # blocks changes, not reads.  Without this a refused startup
            # power-on marks a LIT panel dark, and the dashboard then retries a
            # wake on every touch for as long as the server runs.
            verdict = await self.__check_lit()
            if verdict == _LIT:
                self.__on = True
            elif verdict in (_DARK, _MISSING):
                self.__on = False
            return
        verdict = await self.__check_lit() if on else _UNKNOWN
        if verdict == _MISSING:
            if await self.__recover():
                self.__on = True
                self.__fault = protocol.DISPLAY_FAULT_NONE
                return
            # Lit at the kick mode counts as on: the panel shows a picture.
            self.__on = await self.__check_lit() == _LIT
            self.__fault = protocol.DISPLAY_FAULT_OUTPUT_LOST
            logger.error(
                "Display output %s did not come back %s after a power-on. Known on labwc "
                "0.20 / wlroots 0.20 after a long blank. Recover with `sudo systemctl restart "
                "lightdm`; screen-off is suspended until a recovery works or the backend "
                "restarts", self.__output_names(),
                "on its native mode (it is lit at another)" if self.__on
                else "(the panel stays dark)")
            return
        if verdict == _DARK:
            self.__on = False
            if self.__fault != protocol.DISPLAY_FAULT_OUTPUT_LOST:
                self.__fault = protocol.DISPLAY_FAULT_REFUSED
            logger.warning("%s --on succeeded but the output still reports off", _COMMAND)
            return
        self.__on = on
        if self.__fault == protocol.DISPLAY_FAULT_REFUSED:
            self.__fault = protocol.DISPLAY_FAULT_NONE
        if on:
            await self.__learn_outputs()

    async def __recover(self) -> bool:
        '''
        Brings back an output the compositor dropped after a blank (#43), the way
        the reference Pi's journal shows works, checking after each step: the
        native mode applied again, then a modeset through another listed mode and
        back to the native one.  `wlopm --on` and a native modeset both fail on a
        wedged output (`failed to apply configuration`); the second step revived
        all seven wedges logged there in three days, about 7 s after the wake.
        The caller holds the lock.

        Returns True once every learned output is lit at its native mode.  With
        no wlr-randr, or no output seen lit since the backend started, there is
        nothing to restore: a dropped output is listed disabled, with no current
        mode to read.
        '''
        logger.warning("Display output %s is gone from the compositor after a power-on "
                       "(the labwc 0.20 wedge, #43); recovering", self.__output_names())
        if not self.__can_recover:
            logger.warning("Cannot recover the output: %s is not installed", _RANDR)
            return False
        if not self.__outputs:
            logger.warning("Cannot recover the output: none has been seen lit since the "
                           "backend started, so the mode to restore is unknown")
            return False
        kicks = [o.kick for o in self.__outputs if o.kick]
        steps = [("the native mode re-applied", "Näyttötila uudelleen", False)]
        if kicks:
            steps.append((f"a modeset through {', '.join(kicks)}",
                          f"Tilanvaihto ({', '.join(_resolution(k) for k in kicks)})", True))
        for how, label, kick in steps:
            errors = []
            for output in self.__outputs:
                if kick and output.kick is None:
                    continue
                for mode in (output.kick, output.native) if kick else (output.native,):
                    error = await self.__set_mode(output.name, mode)
                    if error:
                        errors.append(f"{output.name} {mode}: {error}")
            if await self.__at_native():
                self.__recoveries += 1
                self.__last_recovery_ms = int(time.time() * 1000)
                self.__last_recovery_how = label
                logger.info("Display output back after %s", how)
                return True
            logger.warning("Display output still dark after %s%s", how,
                           f" ({'; '.join(errors)})" if errors else "")
        return False

    async def __set_mode(self, name: str, mode: str) -> str:
        '''
        One modeset, then the settle time.  Returns wlr-randr's complaint, ""
        when it accepted the mode.
        Arguments:
            name (str): The output, e.g. "HDMI-A-1".
            mode (str): The mode, as _mode_text() writes it.
        '''
        try:
            returncode, _, stderr = await process.run(
                (_RANDR, "--output", name, "--on", "--mode", mode), _RUN_TIMEOUT_SECONDS)
            error = (stderr.strip() or f"exit {returncode}") if returncode != 0 else ""
        except asyncio.TimeoutError:
            error = f"timed out after {_RUN_TIMEOUT_SECONDS:.0f} s"
        except OSError as e:
            error = str(e)
        await asyncio.sleep(_SETTLE_SECONDS)
        return error

    async def __at_native(self) -> bool:
        '''
        Whether a recovery is done: the outputs lit in wlopm and each learned one
        on its native mode.  A wlr-randr answer that cannot be read leaves "lit"
        as the answer.
        '''
        if await self.__check_lit() != _LIT:
            return False
        entries = await self.__read_randr()
        if entries is None:
            return True
        current = {o.name: o.native for o in _outputs_from(entries)}
        return all(current.get(o.name) == o.native for o in self.__outputs)

    async def __learn_outputs(self) -> None:
        '''
        Remembers the outputs as they are now, lit, because a dropped output's
        mode can no longer be read.  Runs after every power-on that worked, so a
        mode changed since startup is the one restored.  Kept as it was when
        wlr-randr gives no usable answer.
        '''
        if not self.__can_recover:
            return
        outputs = _outputs_from(await self.__read_randr())
        if outputs and outputs != self.__outputs:
            self.__outputs = outputs
            logger.info("Display output for recovery: %s", "; ".join(
                f"{o.name} at {o.native}" + (f", kick through {o.kick}" if o.kick else
                                             ", no other mode to kick through")
                for o in outputs))

    async def __read_randr(self):
        '''`wlr-randr --json` parsed, or None when it gives no usable answer.'''
        try:
            returncode, stdout, _ = await process.run((_RANDR, "--json"), _RUN_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            return None
        except OSError as e:
            logger.debug("Could not run %s --json: %s", _RANDR, e)
            return None
        if returncode != 0:
            return None
        try:
            return json.loads(stdout)
        except ValueError:
            return None

    def __output_names(self) -> str:
        '''The learned outputs' names for a log line, the selector before any is learned.'''
        return ", ".join(o.name for o in self.__outputs) or _ALL_OUTPUTS

    async def __check_lit(self) -> str:
        '''
        Reads `wlopm --json` and says whether the driven output(s) are present
        and lit.  Only an output that is MISSING is ever treated as the #43
        wedge; anything unreadable — an older wlopm without --json, output in a
        shape this does not recognise — is _UNKNOWN, so a wake that cannot be
        verified is never reported as a fault.
        '''
        try:
            returncode, stdout, _ = await process.run((_COMMAND, "--json"), _RUN_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            return _UNKNOWN
        except OSError as e:
            logger.debug("Could not run %s --json: %s", _COMMAND, e)
            return _UNKNOWN
        if returncode != 0:
            return _UNKNOWN
        try:
            entries = json.loads(stdout)
        except ValueError:
            return _UNKNOWN
        if not isinstance(entries, list):
            return _UNKNOWN

        # [{"output": "HDMI-A-1", "power-mode": "on"}, ...]
        modes = {
            entry["output"]: entry.get("power-mode")
            for entry in entries
            if isinstance(entry, dict) and "output" in entry
        }
        if not modes:
            return _MISSING
        return _DARK if any(mode == "off" for mode in modes.values()) else _LIT

    async def __run(self, on: bool) -> bool:
        '''
        Runs one wlopm invocation.  Returns True when it exited cleanly; a
        failure is logged and swallowed, because a display that will not switch
        must not take the dashboard down with it.
        Arguments:
            on (bool): True for --on, False for --off.
        '''
        args = ("--on" if on else "--off", _ALL_OUTPUTS)
        try:
            returncode, _, stderr = await process.run((_COMMAND, *args), _RUN_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            logger.warning("%s %s timed out after %.0f s", _COMMAND, " ".join(args),
                           _RUN_TIMEOUT_SECONDS)
            return False
        except OSError as e:
            # Vanished between the which() probe and now, or is not executable.
            logger.warning("Could not run %s: %s", _COMMAND, e)
            self.__available = False
            return False

        if returncode != 0:
            logger.warning("%s %s exited with %s: %s", _COMMAND, " ".join(args),
                           returncode, stderr.strip())
            return False
        return True

    def __state_frame(self) -> bytes:
        '''Builds a DISPLAY_POWER_STATE packet from the current state.'''
        return protocol.frame(
            protocol.DISPLAY_POWER_STATE,
            bytes((1 if self.__available else 0, 1 if self.__on else 0, self.__fault)),
        )
