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
lets a tap wake it.

Deployment note: wlopm needs the Wayland socket.  The backend runs as a
`systemd --user` unit under the same user as the compositor, so XDG_RUNTIME_DIR
is already in its environment; WAYLAND_DISPLAY may not be, and the unit should
set it (see README).  With no wlopm on PATH the service reports itself
unavailable and every request is a no-op, so a headless or X11 host degrades
quietly instead of failing every timeout.
'''

import asyncio
import logging
import shutil

from ..utils import protocol

logger = logging.getLogger("display_service")

# The wlr-output-power-management client. Looked up on PATH so a non-standard
# install location still works.
_COMMAND = "wlopm"

# wlopm's "every output" selector. Passed as a plain argv entry — there is no
# shell involved, so there is nothing to glob-expand it.
_ALL_OUTPUTS = "*"

# A wlopm run is milliseconds of work; anything beyond this means the compositor
# is not answering and waiting longer only blocks the event loop's next tick.
_RUN_TIMEOUT_SECONDS = 5.0


class DisplayService:
    '''
    Serves DISPLAY_SET_POWER and snapshots DISPLAY_POWER_STATE to new clients.

    Arguments:
        server (Server): TCP server used to reply to and broadcast at clients.
        output (str): wlopm output name; "*" targets every output.
    '''

    def __init__(self, server, output: str = _ALL_OUTPUTS):
        self.__server = server
        self.__output = output or _ALL_OUTPUTS
        # Resolved once: a host either has wlopm or it does not, and re-probing
        # on every request would just add a stat() per timeout.
        self.__available = shutil.which(_COMMAND) is not None
        # Assumed on at startup. A fresh backend implies a fresh session, and the
        # first thing run() does is make that true rather than merely assume it.
        self.__on = True
        # Serialises runs: an off->on flip arriving mid-run must not race the
        # process it is reversing.
        self.__lock = asyncio.Lock()

        if self.__available:
            logger.info("Display power control available via %s (output=%s)",
                        _COMMAND, self.__output)
        else:
            logger.warning(
                "%s not found; display power control disabled (the dashboard's "
                "screen-off setting will have no effect)", _COMMAND
            )

    # ── Protocol handlers ─────────────────────────────────────────

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

    # ── Control ───────────────────────────────────────────────────

    async def set_power(self, on: bool) -> None:
        '''
        Powers the panel on or off, if this host can.  Idempotent: a request for
        the state we are already in does not spawn a process.
        Arguments:
            on (bool): True wakes the panel, False powers it down.
        '''
        if not self.__available or on == self.__on:
            return
        async with self.__lock:
            if not await self.__run(on):
                return
            self.__on = on
        logger.info("Display %s", "on" if on else "off")
        await self.__server.broadcast(self.__state_frame())

    async def run(self) -> None:
        '''
        Startup task: makes the assumed-on state true.  Without this a backend
        restarting while the panel is dark would leave it dark, with the frontend
        believing it is lit — and the panel only wakes on a touch nobody knows to
        make.
        '''
        if not self.__available:
            return
        async with self.__lock:
            await self.__run(True)
            self.__on = True

    def get_run_task(self):
        '''Returns the startup task for start_services to gather.'''
        return asyncio.create_task(self.run())

    async def shutdown(self) -> None:
        '''
        Leaves the panel lit on the way out.  A backend restart must never come
        back to a screen that looks dead until it is touched.
        '''
        if self.__available and not self.__on:
            await self.__run(True)
            self.__on = True

    # ── Internals ─────────────────────────────────────────────────

    async def __run(self, on: bool) -> bool:
        '''
        Runs one wlopm invocation.  Returns True when it exited cleanly; a
        failure is logged and swallowed, because a display that will not switch
        must not take the dashboard down with it.
        Arguments:
            on (bool): True for --on, False for --off.
        '''
        args = ("--on" if on else "--off", self.__output)
        try:
            process = await asyncio.create_subprocess_exec(
                _COMMAND, *args,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(
                process.communicate(), timeout=_RUN_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            logger.warning("%s %s timed out after %.0f s", _COMMAND, " ".join(args),
                           _RUN_TIMEOUT_SECONDS)
            return False
        except OSError as e:
            # Vanished between the which() probe and now, or is not executable.
            logger.warning("Could not run %s: %s", _COMMAND, e)
            self.__available = False
            return False

        if process.returncode != 0:
            logger.warning("%s %s exited with %s: %s", _COMMAND, " ".join(args),
                           process.returncode, stderr.decode("utf-8", "replace").strip())
            return False
        return True

    def __state_frame(self) -> bytes:
        '''Builds a DISPLAY_POWER_STATE packet from the current state.'''
        return protocol.frame(
            protocol.DISPLAY_POWER_STATE,
            bytes((1 if self.__available else 0, 1 if self.__on else 0)),
        )
