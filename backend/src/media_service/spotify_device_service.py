'''
Spotify Connect device detection driven from the Options view.

`spotifyDeviceId` decides which Connect device this backend claims playback
from.  Get it wrong and nothing announces the mistake: the Spotify player simply
never claims control, so every transport button on the dashboard does nothing at
all and the radio keeps playing.  Until now the only fix was SSHing to the Pi and
running `media_service/setup/spotify_setup.py` — which is not an interface the
deployment actually has, since the panel is fullscreen and keyboard-less.

So this serves the same discovery over the protocol.  The user starts playing on
the device they want, the backend polls Spotify for what is playing ANYWHERE (not
just on the configured device — that is the value being fixed), and streams the
device and the track back so the choice can be *confirmed* before it is written.
Showing the track matters: several Connect devices in one household routinely
carry the same name, and the song playing is what tells them apart.

Two invariants keep the scan honest when more than one panel is on the Options
view (this backend fans out to several frontends).  A scan is owned by the
socket that started it, so a stop or a select from any other client is refused
rather than silently ending someone else's scan; and every packet carries the
frontend-generated `scanId` epoch, so a state or result still in flight from a
cancelled scan cannot repopulate the dialog of the one that replaced it.

Two boundaries are deliberate.  Every Spotify API call goes through the player
via MediaManager, which owns the client, the auth latch and the executor pattern
(the same route SpotifyAuthService takes through `spotify_auth_error()`).  And
the write goes through `ConfigService.apply_write()` rather than touching
config.json here, so the id lands on disk through the one validated path — schema
coercion, atomic save with its .bak snapshot, rollback on failure, apply hooks and
the schema re-broadcast that keeps a second dashboard honest.
'''

import asyncio
import json
import logging
import struct
import time

from ..utils import protocol

logger = logging.getLogger("media_service.spotify_device")

# How often the scan asks Spotify what is playing. Matches the player's own
# active-poll cadence: the user is waiting in front of the dialog, and Spotify's
# rate limit is nowhere near this.
_POLL_SECONDS = 2

# A scan that nobody stopped gives up after this long. A forgotten dialog — the
# user walked away, the frontend crashed, the socket wedged — must never poll
# Spotify forever on a screen no one is looking at.
_SCAN_TTL_SECONDS = 300

# An unchanged state is re-sent this often anyway, so the frontend can tell "the
# scan is alive and nothing is playing" from "the scan died silently".
_HEARTBEAT_SECONDS = 10


class SpotifyDeviceService:
    '''
    Serves the SPOTIFY_DEVICE_* codes: runs one device scan at a time for the
    requesting client, and writes the chosen device id to config.json through
    ConfigService.

    Also answers SPOTIFY_DEVICE_GET_STATUS: which device is configured, and
    whether Spotify can see it right now.

    Not registered with Server.register_service and given no run task: a scan is
    user-initiated and short-lived, and the device status costs a Spotify request,
    so both are served on request rather than snapshotted to every new client.
    Arguments:
        config (Config): Shared configuration; read for the stored device name.
        server (Server): TCP server used for send_to.
        media_manager (MediaManager): Route to the Spotify player's API calls and
            to stopping whatever else is playing.
        config_service (ConfigService): Performs the spotifyDeviceId (and
            spotifyDeviceName) writes through the same validated path a
            CONFIG_SET takes.
    '''

    def __init__(self, config, server, media_manager, config_service):
        self.__config = config
        self.__server = server
        self.__media_manager = media_manager
        self.__config_service = config_service
        # One scan at a time: a new start replaces whatever was running, exactly
        # like SpotifyAuthService's pending flow.
        self.__scan: dict | None = None
        # device id -> name, accumulated from everything the scan has seen. Lets
        # a selection be reported by name without spending another API call on a
        # device we have already looked at.
        self.__device_names: dict[str, str] = {}

    # ── Handlers ──────────────────────────────────────────────────

    async def handle_scan_start(self, payload: bytes, writer) -> None:
        '''
        SPOTIFY_DEVICE_SCAN_START handler: silences other playback and starts
        polling Spotify for the device the user is about to start playing on.
        Arguments:
            payload (bytes): len(4B) + UTF-8 JSON {"scanId": <uint>}.  A missing
                or malformed body is read as scan id 0 rather than refused — the
                epoch is a fence, not a credential.
            writer (StreamWriter): The requesting client; every state goes to it
                alone, never a broadcast.  It also becomes the scan's OWNER: no
                other client may stop it or select from it.
        '''
        scan_id = self.__parse_scan_id(payload)

        # Replace whatever was running first, but do NOT resume its silenced
        # playback yet: this scan is about to want the same silence, and the
        # obligation to bring the radio back is carried over below instead.
        previous = await self.__cancel_scan(resume_playback=False)
        if previous is not None and previous["writer"] is not writer:
            # Another panel owned that scan. Nothing else would ever tell it the
            # scan is gone, so its dialog would sit on the guide text forever.
            await self.__send_state(
                previous["writer"],
                self.__build_state(False, "Tunnistus siirtyi toiselle näytölle",
                                   None, previous, previous["scan_id"]),
            )

        # A dead grant cannot answer a single poll, so say so once instead of
        # standing up a loop that can only fail every two seconds.
        auth_error = self.__media_manager.spotify_auth_error()
        if auth_error is not None:
            logger.info("Spotify device scan refused: %s", auth_error)
            if previous is not None:
                # No scan will run, so the replaced one's silence has no owner.
                await self.__resume_playback(previous)
            await self.__send_state(
                writer, self.__build_state(False, auth_error, None, None, scan_id)
            )
            return

        # The whole point of the scan is that the user can hear which device they
        # started, which is hopeless over the radio.
        stopped_playback = False
        try:
            stopped_playback = await self.__media_manager.stop_other_playback()
        except Exception as e:  # noqa: BLE001 - a stubborn player must not block the scan
            logger.warning("Could not stop the active player for the scan: %s", e)

        scan = {
            "writer": writer,
            "scan_id": scan_id,
            "task": None,
            "started": time.monotonic(),
            "current_name": "",
            # True while this scan owes the user a radio it silenced. Inherited
            # from a scan this one replaced: that radio is still silent, and the
            # obligation to restart it moves to whoever is scanning now.
            "stopped_playback": stopped_playback or bool(
                previous and previous.get("stopped_playback")
            ),
            # The newest probe, kept so a selection can tell whether the chosen
            # device was actually playing.
            "playback": None,
        }
        self.__scan = scan
        if previous is not None:
            # Handed over, so the replaced scan can no longer resume anything —
            # its poll task may still reach an exit path before cancellation
            # lands, and that must not un-silence the radio this scan needs.
            previous["stopped_playback"] = False

        # Resolved once, before the loop: the configured device's name almost
        # never changes mid-scan, and re-reading the device list every two
        # seconds would double the scan's API cost for nothing.
        scan["current_name"] = await self.__resolve_current_name()
        if self.__scan is not scan:
            # Superseded while that call was in flight. The replacing scan has
            # already inherited this one's playback obligation.
            return

        logger.info("Spotify device scan started (scan %d)", scan_id)
        scan["task"] = asyncio.create_task(self.__poll(scan))

    async def handle_scan_stop(self, _payload: bytes, writer) -> None:
        '''
        SPOTIFY_DEVICE_SCAN_STOP handler: ends the scan and restores the
        playback it silenced.  Nothing is replied — the frontend closed its
        dialog and has already stopped listening.

        Acts only for the client that OWNS the scan.  Several panels can be on
        the Options view at once, and a Peruuta on one of them must not cancel a
        live scan on another, which would hang that dialog on the guide text
        with nothing ever arriving to close it.
        Arguments:
            _payload (bytes): Unused; the command carries no body.
            writer (StreamWriter): The requesting client.
        '''
        scan = self.__scan
        if scan is None:
            return
        if scan["writer"] is not writer:
            logger.debug("Ignoring a scan stop from a client that does not own the scan")
            return
        logger.info("Spotify device scan stopped by the client")
        await self.__cancel_scan()

    async def handle_select(self, payload: bytes, writer) -> None:
        '''
        SPOTIFY_DEVICE_SELECT handler: writes the chosen device id to
        spotifyDeviceId and reports the outcome.

        Honoured only for the client that owns the live scan, and only when the
        request's scanId is that scan's.  A select carrying a stale epoch is a
        tap on a dialog repopulated by a packet from an abandoned scan — exactly
        the way a wrong device id gets written — so it is refused, not applied.
        Arguments:
            payload (bytes): len(4B) + UTF-8 JSON
                {"deviceId": "<id>", "scanId": <uint>}.
            writer (StreamWriter): The requesting client.
        '''
        try:
            request = self.__parse_json_payload(payload)
        except ValueError as e:
            logger.warning("Malformed SPOTIFY_DEVICE_SELECT: %s", e)
            # The epoch is unreadable in a broken frame, so 0 is all that can be
            # echoed; the frontend drops it, which is the right outcome for a
            # request it cannot have sent in this shape.
            await self.__reply_result(writer, False, str(e), "", "", 0)
            return

        scan_id = self.__scan_id_of(request)
        try:
            device_id = self.__device_id_of(request)
        except ValueError as e:
            logger.warning("Malformed SPOTIFY_DEVICE_SELECT: %s", e)
            await self.__reply_result(writer, False, str(e), "", "", scan_id)
            return

        name = self.__device_names.get(device_id, "")

        scan = self.__scan
        if scan is None or scan["writer"] is not writer or scan["scan_id"] != scan_id:
            logger.debug(
                "Refusing a device selection for scan %d (live scan: %s)",
                scan_id, scan["scan_id"] if scan else "none",
            )
            await self.__reply_result(
                writer, False, "Haku on vanhentunut — aloita tunnistus uudelleen",
                device_id, name, scan_id,
            )
            return

        result = await self.__config_service.apply_write("spotifyDeviceId", device_id)

        if not result.get("ok"):
            message = result.get("message") or "Laitteen tallennus epäonnistui"
            logger.warning("Could not save spotifyDeviceId: %s", message)
            # The scan deliberately stays LIVE, and the radio stays silent with
            # it.  A failed save does not close the dialog: it keeps the device
            # on screen with "Valitse laite" still armed, because the realistic
            # failure here is transient (the atomic save meeting a full or
            # read-only filesystem) and retrying is the whole point of leaving
            # that button reachable.  Ending the scan would answer every retry
            # with "Haku on vanhentunut", turning the button into a dead control
            # — and would resume the radio underneath a dialog that is still
            # asking for silence.  The silence is released the ordinary way
            # instead: Peruuta, the TTL, or the client going away.
            await self.__reply_result(writer, False, message, device_id, name, scan_id)
            return

        applied = result.get("applied", "")
        if applied == "unchanged":
            message = "Laite oli jo valittuna"
        elif applied == "restart":
            message = "Laite tallennettiin — käynnistä taustapalvelu uudelleen"
        else:
            message = "Laite tallennettiin"

        logger.info("Spotify device selected: %s (%s)", device_id, name or "?")

        # Kept beside the id so the Options view can name the configured device
        # even while it is switched off (Spotify lists only devices that are up).
        # Cosmetic, so a failure is logged and nothing else: the id is what
        # decides claiming, and it is already saved.
        if name:
            name_result = await self.__config_service.apply_write("spotifyDeviceName", name)
            if not name_result.get("ok"):
                logger.warning("Could not save spotifyDeviceName: %s",
                               name_result.get("message"))

        # Resume the radio only when the chosen device was NOT playing at the
        # moment it was picked. When it WAS playing, SpotifyPlayer claims control
        # within one poll and claim_media_control stops the radio again — so
        # restarting it here would buy one second of radio audio and a stream of
        # state packets for nothing.
        playback = scan.get("playback") or {}
        chosen_is_playing = bool(
            (playback.get("device") or {}).get("id") == device_id
            and (playback.get("track") or {}).get("isPlaying")
        )
        # The choice has been made; there is nothing left to watch for.  The
        # reply goes out before any resume, which refetches the radio stream.
        await self.__cancel_scan(resume_playback=False)
        await self.__reply_result(writer, True, message, device_id, name, scan_id)
        # To every client: a second panel on the Options view is showing the
        # device this just replaced.
        await self.__server.broadcast(self.__status_frame(await self.build_status()))
        if not chosen_is_playing:
            await self.__resume_playback(scan)

    async def handle_get_status(self, _payload: bytes, writer) -> None:
        '''
        SPOTIFY_DEVICE_GET_STATUS handler: replies with the configured device and
        whether Spotify can see it, for the Options view's "Tunnista laite" row.
        Arguments:
            _payload (bytes): Unused; the request carries no body.
            writer (StreamWriter): The requesting client.
        '''
        await self.__server.send_to(writer, self.__status_frame(await self.build_status()))

    # ── Device status ─────────────────────────────────────────────

    async def build_status(self) -> dict:
        '''
        Builds one SPOTIFY_DEVICE_STATUS document.  "detected" is tri-state:
        True / False once Spotify's device list was read, None when it could not
        be (no device configured, no working grant, the call failed) — "not in
        the list" and "could not look" must not render the same.

        Spotify lists only devices that are up and signed in, so a configured
        device that is missing is either switched off or a wrong id; the two
        cannot be told apart from here, and the row says so.
        '''
        # The PLAYER's target, not Config's: it is what claiming actually uses.
        configured = self.__media_manager.spotify_target_device_id() or ""
        stored_name = str(self.__config.get("spotifyDeviceName") or "")
        status = {
            "configured": bool(configured),
            "id": configured,
            "name": stored_name,
            "type": "",
            "detected": None,
            "isRestricted": False,
            "reason": "",
        }
        if not configured:
            status["reason"] = "Laitetta ei ole valittu"
            return status

        auth_error = self.__media_manager.spotify_auth_error()
        if auth_error is not None:
            status["reason"] = auth_error
            return status

        devices = await self.__media_manager.list_spotify_devices()
        if devices is None:
            status["reason"] = "Spotify ei vastannut"
            return status

        for device in devices:
            device_id = device.get("id")
            if device_id:
                self.__device_names[device_id] = device.get("name") or ""
            if device_id == configured:
                # The live name wins: the device may have been renamed since it
                # was chosen.
                status["name"] = device.get("name") or stored_name
                status["type"] = device.get("type") or ""
                status["isRestricted"] = bool(device.get("is_restricted"))
                status["detected"] = True
                return status

        status["detected"] = False
        status["reason"] = "Laite ei näy Spotifyssa"
        return status

    # ── Scanning ──────────────────────────────────────────────────

    async def __poll(self, scan: dict) -> None:
        '''
        Polls Spotify until the scan is stopped, superseded or expires, sending
        SPOTIFY_DEVICE_STATE to the scanning client.

        Sends the first state immediately and then only when the document has
        actually changed (or every _HEARTBEAT_SECONDS), so a scan that sits idle
        while the user walks to a speaker is quiet on the wire.  A failed probe is
        not fatal: Spotify returns nothing at all between tracks, and treating
        that as an error would end the scan exactly when the user is switching
        device.  Nothing may escape this coroutine either — an exception in a
        bare task dies silently, leaving a dialog that waits forever.

        A closing writer ends the scan.  Server.__safe_write CATCHES the
        connection error, drops the client and returns normally, so a send to a
        dead peer never raises and this loop would otherwise never learn — and
        the task is not one Server tracks, so nothing cancels it either.  Without
        the check a killed or reconnected dashboard leaves ~150 pointless
        current_playback calls running for the rest of the TTL.
        Arguments:
            scan (dict): The scan this loop belongs to.
        '''
        last_state = None
        last_sent = 0.0
        try:
            while True:
                if self.__scan is not scan:
                    return

                if scan["writer"].is_closing():
                    logger.info("Spotify device scan ended: the client is gone")
                    self.__scan = None
                    await self.__resume_playback(scan)
                    return

                if time.monotonic() - scan["started"] >= _SCAN_TTL_SECONDS:
                    logger.info("Spotify device scan expired after %ds", _SCAN_TTL_SECONDS)
                    # Clear the slot directly rather than through __cancel_scan():
                    # that would cancel this very task mid-send.
                    self.__scan = None
                    await self.__send_state(
                        scan["writer"],
                        self.__build_state(False, "Haku päättyi aikakatkaisuun",
                                           None, scan, scan["scan_id"]),
                    )
                    await self.__resume_playback(scan)
                    return

                # The grant can die mid-scan (the refresh token's 6-month expiry
                # is a scheduled certainty). Report it rather than polling a dead
                # grant for the rest of the TTL.
                auth_error = self.__media_manager.spotify_auth_error()
                if auth_error is not None:
                    logger.info("Spotify device scan ended: %s", auth_error)
                    self.__scan = None
                    await self.__send_state(
                        scan["writer"],
                        self.__build_state(False, auth_error, None, scan, scan["scan_id"]),
                    )
                    await self.__resume_playback(scan)
                    return

                playback = None
                try:
                    playback = await self.__media_manager.probe_spotify_playback()
                except Exception as e:  # noqa: BLE001 - one bad poll must not end the scan
                    logger.debug("Spotify playback probe failed: %s: %s",
                                 type(e).__name__, e)

                self.__remember_device(playback)
                # Kept so a selection can tell whether the chosen device was
                # already playing, which decides if the radio comes back.
                scan["playback"] = playback
                state = self.__build_state(True, "", playback, scan, scan["scan_id"])
                now = time.monotonic()
                if state != last_state or now - last_sent >= _HEARTBEAT_SECONDS:
                    await self.__send_state(scan["writer"], state)
                    last_state = state
                    last_sent = now

                await asyncio.sleep(_POLL_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - never let the task die unexplained
            logger.error("Spotify device scan stopped unexpectedly: %s: %s",
                         type(e).__name__, e)
            if self.__scan is scan:
                self.__scan = None
            await self.__resume_playback(scan)

    async def __cancel_scan(self, resume_playback: bool = True) -> dict | None:
        '''
        Ends the running scan, if any, and returns it so the caller can inspect
        who owned it.

        Does NOT await the cancelled task.  Cancellation takes effect at the
        task's next await point, which is all a replacement scan needs, and
        awaiting would deadlock if this were ever reached from inside the poll
        loop itself — the same reasoning SpotifyAuthService.__cancel_pending
        records for its listener.  For that same reason the poll loop's own exit
        paths clear self.__scan directly instead of calling this.
        Arguments:
            resume_playback (bool): Whether to restart the playback the scan
                silenced.  False when the caller is about to want that silence
                itself and carries the obligation over instead.
        '''
        scan = self.__scan
        self.__scan = None
        if scan is None:
            return None
        task = scan.get("task")
        if task is not None and not task.done():
            scan["task"] = None
            task.cancel()
        if resume_playback:
            await self.__resume_playback(scan)
        return scan

    async def __resume_playback(self, scan: dict) -> None:
        '''
        Restores the playback this scan silenced, on every way a scan ENDS
        without a successful selection: cancel, timeout, a dead client, a
        mid-scan auth failure or a superseded scan.  The dialog tells the user
        playback is paused "tunnistuksen ajaksi" — for the duration of the
        identification — and nothing else in the stack keeps that promise.

        A failed WRITE is deliberately not on that list: it leaves the scan
        running so the save can be retried, so the silence still has an owner
        and is released by whichever of the above ends that scan.

        A no-op when the scan never stopped anything that was actually playing;
        the flag is cleared first so no path can resume twice.
        Arguments:
            scan (dict): The scan that is ending.
        '''
        if not scan.get("stopped_playback"):
            return
        scan["stopped_playback"] = False
        try:
            await self.__media_manager.resume_default_playback()
        except Exception as e:  # noqa: BLE001 - a failed resume must not break the reply
            logger.warning("Could not resume playback after the device scan: %s", e)

    async def __resolve_current_name(self) -> str:
        '''
        Looks up the display name of the currently configured device, so the scan
        can say what is selected today rather than showing a bare id.  Returns ""
        when nothing is configured, the device is offline, or the call failed —
        none of which is worth failing a scan over.
        '''
        configured = self.__media_manager.spotify_target_device_id()
        if not configured:
            return ""
        devices = await self.__media_manager.list_spotify_devices()
        if not devices:
            return ""
        for device in devices:
            device_id = device.get("id")
            name = device.get("name") or ""
            if device_id:
                self.__device_names[device_id] = name
            if device_id == configured:
                return name
        return ""

    def __remember_device(self, playback: dict | None) -> None:
        '''
        Records the id -> name of a device the scan has just seen, so a later
        selection can be reported by name with no extra API call.
        Arguments:
            playback (dict | None): A probe_playback result, or None.
        '''
        device = (playback or {}).get("device") or {}
        device_id = device.get("id")
        if device_id:
            self.__device_names[device_id] = device.get("name") or ""

    def __build_state(self, scanning: bool, message: str,
                      playback: dict | None, scan: dict | None,
                      scan_id: int) -> dict:
        '''
        Builds one SPOTIFY_DEVICE_STATE document.
        Arguments:
            scanning (bool): False once the scan has stopped or expired.
            message (str): Finnish reason the scan is blocked; "" while healthy.
            playback (dict | None): A probe_playback result, or None when nothing
                is playing anywhere.
            scan (dict | None): The scan being reported, for the resolved name of
                the configured device.
            scan_id (int): The epoch this document belongs to — the scan's own,
                or the requesting frontend's when no scan was started.  The
                frontend drops anything that is not its current epoch, so a
                refusal must echo the REQUEST's id, not the live scan's.
        '''
        device = (playback or {}).get("device")
        track = (playback or {}).get("track")
        # Read from the PLAYER, not from Config: the player's target is what
        # actually decides claiming, and it is what a stale value would break.
        # (They agree — the spotify hook re-snapshots it on every write.)
        configured = self.__media_manager.spotify_target_device_id() or ""
        return {
            "scanId": scan_id,
            "scanning": scanning,
            "message": message,
            "device": device,
            "track": track,
            "current": {
                "id": configured,
                "name": (scan or {}).get("current_name", ""),
                "isSame": bool(
                    configured and device and device.get("id") == configured
                ),
            },
        }

    # ── Internals ─────────────────────────────────────────────────

    @staticmethod
    def __parse_json_payload(payload: bytes) -> dict:
        '''
        Unpacks the len(4B) + UTF-8 JSON body shared by SCAN_START and SELECT.
        Raises ValueError with a Finnish message shown to the user verbatim.
        Arguments:
            payload (bytes): The raw payload after the message-type byte.
        '''
        if len(payload) < 4:
            raise ValueError("Vaillinainen pyyntö")
        (length,) = struct.unpack("!I", payload[:4])
        body = payload[4:4 + length]
        if len(body) != length:
            raise ValueError("Vaillinainen pyyntö")
        try:
            request = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ValueError("Virheellinen JSON") from e
        if not isinstance(request, dict):
            raise ValueError("Virheellinen pyyntö")
        return request

    @staticmethod
    def __scan_id_of(request: dict) -> int:
        '''
        Reads the frontend's scan epoch out of a request.  Anything missing or
        malformed reads as 0 — the epoch is a fence against late packets, not a
        credential, and a frame that cannot carry one must not crash a handler.
        (bool is a subclass of int in Python, so it is rejected explicitly.)
        Arguments:
            request (dict): The parsed request document.
        '''
        value = request.get("scanId")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return 0
        return value

    @classmethod
    def __parse_scan_id(cls, payload: bytes) -> int:
        '''
        Reads the scan epoch out of a SPOTIFY_DEVICE_SCAN_START body.  Tolerant
        by design: an unreadable body starts a scan at epoch 0 rather than
        refusing one, so an older frontend that still sends an empty packet
        keeps working.
        Arguments:
            payload (bytes): The raw payload after the message-type byte.
        '''
        try:
            request = cls.__parse_json_payload(payload)
        except ValueError as e:
            logger.debug("Scan start without a readable scanId: %s", e)
            return 0
        return cls.__scan_id_of(request)

    @staticmethod
    def __device_id_of(request: dict) -> str:
        '''
        Reads the chosen device id out of a SPOTIFY_DEVICE_SELECT request.
        Raises ValueError with a Finnish message shown to the user verbatim.
        Arguments:
            request (dict): The parsed request document.
        '''
        device_id = request.get("deviceId")
        # A restricted device reports no id at all, and an empty id would silence
        # every transport control — the exact failure this feature exists to fix.
        if not isinstance(device_id, str) or not device_id.strip():
            raise ValueError("Laitetta ei voi valita (ei tunnusta)")
        return device_id.strip()

    @staticmethod
    def __json_frame(msg_type: int, status: int, body: bytes) -> bytes:
        '''
        Frames a status-prefixed JSON body, the shape the CONFIG_* and
        SPOTIFY_AUTH_* codes use.
        Arguments:
            msg_type (int): Message-type byte.
            status (int): protocol.SPOTIFY_AUTH_OK or _ERROR.
            body (bytes): UTF-8 JSON payload.
        '''
        return protocol.frame(
            msg_type, bytes((status,)) + struct.pack("!I", len(body)) + body
        )

    def __status_frame(self, status: dict) -> bytes:
        '''
        Frames a SPOTIFY_DEVICE_STATUS packet.  The status byte is always OK: the
        document itself says what could and could not be established.
        Arguments:
            status (dict): The document built by build_status.
        '''
        body = json.dumps(status, ensure_ascii=False).encode("utf-8")
        return self.__json_frame(protocol.SPOTIFY_DEVICE_STATUS, protocol.SPOTIFY_AUTH_OK, body)

    async def __send_state(self, writer, state: dict) -> None:
        '''
        Sends one SPOTIFY_DEVICE_STATE to the scanning client only.  The status
        byte reports whether the scan is healthy, so a frontend can react without
        parsing the message field.
        Arguments:
            writer (StreamWriter): The scanning client.
            state (dict): The document built by __build_state.
        '''
        # A write to a dead peer never raises (Server logs it and drops the
        # client), so a closing writer is the only warning there is.
        if writer.is_closing():
            logger.debug("Skipping a device state for a closing client")
            return
        body = json.dumps(state, ensure_ascii=False).encode("utf-8")
        status = (protocol.SPOTIFY_AUTH_ERROR if state["message"]
                  else protocol.SPOTIFY_AUTH_OK)
        await self.__server.send_to(
            writer, self.__json_frame(protocol.SPOTIFY_DEVICE_STATE, status, body)
        )

    async def __reply_result(self, writer, ok: bool, message: str,
                             device_id: str, device_name: str,
                             scan_id: int) -> None:
        '''
        Replies to a SPOTIFY_DEVICE_SELECT.
        Arguments:
            writer (StreamWriter): The requesting client.
            ok (bool): Whether the id was written.
            message (str): Finnish message shown to the user verbatim.
            device_id (str): The id the request targeted, echoed back.
            device_name (str): Its display name when known, else "".
            scan_id (int): The REQUEST's epoch, echoed so the frontend accepts
                the reply — a refusal stamped with the live scan's id instead
                would be dropped by the very fence it is answering.
        '''
        body = json.dumps(
            {"scanId": scan_id, "ok": ok, "message": message,
             "deviceId": device_id, "deviceName": device_name},
            ensure_ascii=False,
        ).encode("utf-8")
        await self.__server.send_to(
            writer,
            self.__json_frame(
                protocol.SPOTIFY_DEVICE_RESULT,
                protocol.SPOTIFY_AUTH_OK if ok else protocol.SPOTIFY_AUTH_ERROR,
                body,
            ),
        )
