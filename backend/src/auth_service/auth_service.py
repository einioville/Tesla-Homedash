'''
Who may use the backend: the password login, the displays that have logged
in, and the TLS certificate they pin (issue #64).

The Server hands every new connection to authenticate() before anything else
happens on it, so no service ever sees a client that has not logged in.  A
display logs in once with the password (scram.py); the backend then issues it
a random token, keeps only the token's hash, and the display sends the token on
every later connect.  The Ylläpito › Näytöt card lists the displays and can
revoke one.

State lives in paired_displays.json beside config.json (0600): the password's
SCRAM verifier and the displays.  The password itself is TESLA_HOMEDASH_PASSWORD
in .env; at start the verifier is checked against it, and a changed — or
removed — password forgets every display.
'''
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time

from ..utils import protocol
from ..utils.atomic_write import write_atomic
from . import scram, tls

logger = logging.getLogger("auth_service")

STORE_FILE = "paired_displays.json"
TLS_DIR = "tls"

# Wrong passwords from one address before it has to wait, then the wait doubles
# from 2 s up to 5 min.  A few free tries cover typos on a touch keyboard.
_FREE_FAILURES = 3
_MAX_LOCKOUT_S = 300

_NAME_MAX = 64
_DAY_MS = 86_400_000


def _now_ms() -> int:
    '''Wall-clock epoch milliseconds, the unit every stored time uses.'''
    return int(time.time() * 1000)


def _token_hash(token: str) -> str:
    '''
    What the store keeps of a token.  A plain SHA-256 is enough: a token is 256
    random bits, not something a dictionary could guess.
    Arguments:
        token (str): The token as the display sent it.
    '''
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AuthService:
    '''
    The login gate the Server runs on each connection, the paired-display list
    and its protocol codes (AUTH_GET_DISPLAYS, AUTH_REVOKE).
    Arguments:
        config (Config): Shared configuration; its directory holds the store and
            the certificate, and auth_config the login lifetime.
        password (str | None): TESLA_HOMEDASH_PASSWORD, or None/"" when unset.
    '''

    def __init__(self, config, password: str | None):
        self.__config = config
        directory = os.path.dirname(config.path)
        self.__store_path = os.path.join(directory, STORE_FILE)
        self.__ssl_context, self.__binding = tls.load_or_create(os.path.join(directory, TLS_DIR))
        self.__lifetime_days = config.auth_config["tokenLifetimeDays"]
        self.__server = None
        self.__verifier: scram.Verifier | None = None
        # id -> {id, name, tokenHash, created, lastSeen, address}
        self.__displays: dict[str, dict] = {}
        # id -> how many of its connections are open right now
        self.__connections: dict[str, int] = {}
        # address -> (wrong passwords in a row, monotonic time of the last one)
        self.__failures: dict[str, tuple[int, float]] = {}
        self.__load(password or "")

    @property
    def ssl_context(self):
        '''The TLS 1.3 server context for the Server's listening socket.'''
        return self.__ssl_context

    def attach_server(self, server) -> None:
        '''
        Wired after the Server exists, which itself needs this service's TLS
        context: broadcasts the display list and closes revoked connections.
        Arguments:
            server (Server): The TLS server.
        '''
        self.__server = server

    # ── The store ─────────────────────────────────────────────────────

    def __load(self, password: str) -> None:
        '''
        Reads the store and reconciles it with the password from .env: the same
        password keeps every display, another one (or none) forgets them all.
        Arguments:
            password (str): The plaintext password, "" when unset.
        '''
        stored = {}
        try:
            with open(self.__store_path, encoding="utf-8") as fh:
                stored = json.load(fh)
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as e:
            logger.error("Could not read %s, every display must log in again: %s: %s",
                         self.__store_path, type(e).__name__, e)
        displays = stored.get("displays") if isinstance(stored, dict) else None
        if isinstance(displays, list):
            self.__displays = {d["id"]: d for d in displays
                               if isinstance(d, dict) and isinstance(d.get("id"), str)}

        previous = self.__stored_verifier(stored.get("scram") if isinstance(stored, dict) else None)
        if not password:
            self.__verifier = None
            if self.__displays:
                logger.warning("TESLA_HOMEDASH_PASSWORD is not set: %d display login(s) forgotten",
                               len(self.__displays))
            if self.__displays or previous:
                self.__displays = {}
                self.__save()
            logger.error("TESLA_HOMEDASH_PASSWORD is not set in .env: no display can log in")
            return

        same = previous is not None and hmac.compare_digest(
            scram.derive(password, previous.salt, previous.iterations).stored_key,
            previous.stored_key)
        if same and previous.iterations == scram.ITERATIONS:
            self.__verifier = previous
            return
        self.__verifier = scram.new_verifier(password)
        if not same and self.__displays:
            logger.warning("The password has changed: %d display login(s) forgotten",
                           len(self.__displays))
            self.__displays = {}
        self.__save()

    @staticmethod
    def __stored_verifier(block) -> scram.Verifier | None:
        '''
        The verifier the store holds, or None for a missing or damaged one.
        Arguments:
            block: The store's "scram" value.
        '''
        if not isinstance(block, dict):
            return None
        try:
            return scram.Verifier(
                salt=base64.b64decode(block["salt"]),
                iterations=int(block["iterations"]),
                stored_key=base64.b64decode(block["storedKey"]),
                server_key=base64.b64decode(block["serverKey"]),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def __save(self) -> None:
        '''Writes the store atomically, 0600: it holds the password's verifier.'''
        document = {"version": 1, "displays": list(self.__displays.values())}
        if self.__verifier is not None:
            document["scram"] = {
                "salt": base64.b64encode(self.__verifier.salt).decode("ascii"),
                "iterations": self.__verifier.iterations,
                "storedKey": base64.b64encode(self.__verifier.stored_key).decode("ascii"),
                "serverKey": base64.b64encode(self.__verifier.server_key).decode("ascii"),
            }
        try:
            write_atomic(self.__store_path, json.dumps(document, ensure_ascii=False, indent=2),
                         mode=0o600)
        except OSError as e:
            logger.error("Could not write %s: %s: %s", self.__store_path, type(e).__name__, e)

    def __expired(self, display: dict, now_ms: int) -> bool:
        '''
        True when a display's login has lapsed: a lifetime is set, the display
        is not connected, and it last was longer ago than the lifetime.
        Arguments:
            display (dict): The stored display.
            now_ms (int): Now, epoch ms.
        '''
        if self.__lifetime_days <= 0 or self.__connections.get(display["id"], 0) > 0:
            return False
        return now_ms - int(display.get("lastSeen", 0)) > self.__lifetime_days * _DAY_MS

    def __prune(self) -> bool:
        '''Forgets every lapsed login; True when one was.'''
        now = _now_ms()
        lapsed = [d for d in self.__displays.values() if self.__expired(d, now)]
        for display in lapsed:
            logger.info("Display login expired: %s (%s)", display.get("name"), display["id"])
            del self.__displays[display["id"]]
        if lapsed:
            self.__save()
        return bool(lapsed)

    # ── The login gate (called by the Server) ─────────────────────────

    async def authenticate(self, connection) -> dict | None:
        '''
        Runs the login on a new connection: AUTH_HELLO, then a token or a SCRAM
        exchange.  Returns the display's identity {"id", "name"} when it may
        stay, or None after telling it why not (the Server then closes it).
        The Server bounds the whole call with a deadline.
        Arguments:
            connection: The Server's handshake channel — recv() -> (type,
                payload), send(packet), address.
        '''
        await connection.send(protocol.json_frame(
            protocol.AUTH_HELLO, protocol.CONFIG_STATUS_OK,
            {"passwordSet": self.__verifier is not None}))
        msg_type, payload = await connection.recv()
        try:
            request = protocol.parse_json_body(payload)
        except ValueError:
            return await self.__refuse(connection, protocol.AUTH_REASON_PROTOCOL)
        if self.__verifier is None:
            return await self.__refuse(connection, protocol.AUTH_REASON_NO_PASSWORD)
        if msg_type == protocol.AUTH_TOKEN:
            return await self.__token_login(connection, request)
        if msg_type == protocol.AUTH_SCRAM_START:
            return await self.__password_login(connection, request)
        return await self.__refuse(connection, protocol.AUTH_REASON_PROTOCOL)

    async def disconnected(self, identity: dict) -> None:
        '''
        A logged-in connection closed: the login's lifetime counts from now.
        Arguments:
            identity (dict): What authenticate() returned for it.
        '''
        display_id = identity["id"]
        remaining = self.__connections.get(display_id, 1) - 1
        if remaining > 0:
            self.__connections[display_id] = remaining
        else:
            self.__connections.pop(display_id, None)
        display = self.__displays.get(display_id)
        if display is not None:
            display["lastSeen"] = _now_ms()
            self.__save()
            await self.__broadcast_displays()

    async def __token_login(self, connection, request: dict) -> dict | None:
        '''
        Checks a remembered login.
        Arguments:
            connection: The handshake channel.
            request (dict): {"deviceId", "token"}.
        '''
        display = self.__displays.get(request.get("deviceId"))
        token = request.get("token")
        if (display is None or not isinstance(token, str)
                or not hmac.compare_digest(_token_hash(token), display["tokenHash"])):
            return await self.__refuse(connection, protocol.AUTH_REASON_TOKEN)
        if self.__expired(display, _now_ms()):
            self.__prune()
            await self.__broadcast_displays()
            return await self.__refuse(connection, protocol.AUTH_REASON_TOKEN,
                                       "Kirjautuminen on vanhentunut")
        return await self.__admit(connection, display, {})

    async def __password_login(self, connection, request: dict) -> dict | None:
        '''
        The SCRAM exchange; on success a new display with a new token.
        Arguments:
            connection: The handshake channel.
            request (dict): {"message": client-first-message}.
        '''
        wait = self.__lockout_remaining(connection.address)
        if wait > 0:
            return await self.__refuse(connection, protocol.AUTH_REASON_THROTTLED,
                                       retry_after=wait)
        exchange = scram.ServerExchange(self.__verifier, binding=self.__binding)
        try:
            challenge = exchange.first(str(request.get("message", "")))
        except scram.ScramError as e:
            return await self.__refuse(connection, e.reason)
        await connection.send(protocol.json_frame(
            protocol.AUTH_SCRAM_CHALLENGE, protocol.CONFIG_STATUS_OK, {"message": challenge}))

        msg_type, payload = await connection.recv()
        try:
            proof = protocol.parse_json_body(payload)
        except ValueError:
            proof = None
        if msg_type != protocol.AUTH_SCRAM_PROOF or proof is None:
            return await self.__refuse(connection, protocol.AUTH_REASON_PROTOCOL)
        try:
            server_final = exchange.final(str(proof.get("message", "")))
        except scram.ScramError as e:
            if e.reason == protocol.AUTH_REASON_PASSWORD:
                self.__record_failure(connection.address)
            elif e.reason == protocol.AUTH_REASON_BINDING:
                # The display saw another certificate than this backend's: a
                # proxy, or someone in the middle.
                logger.warning("Login from %s saw a different TLS certificate", connection.address)
            return await self.__refuse(connection, e.reason)

        self.__failures.pop(connection.address, None)
        name = str(proof.get("name") or "").strip()[:_NAME_MAX] or "Näyttö"
        token = secrets.token_urlsafe(32)
        now = _now_ms()
        display = {"id": secrets.token_hex(8), "name": name, "tokenHash": _token_hash(token),
                   "created": now, "lastSeen": now, "address": connection.address}
        self.__displays[display["id"]] = display
        logger.info("Display logged in with the password: %s (%s) from %s",
                    name, display["id"], connection.address)
        return await self.__admit(connection, display,
                                  {"serverFinal": server_final, "token": token})

    async def __admit(self, connection, display: dict, extra: dict) -> dict:
        '''
        Lets a display in: counts the connection, stamps it and says so.
        Arguments:
            connection: The handshake channel.
            display (dict): The stored display.
            extra (dict): Fields the result carries beside ok (a new login's
                serverFinal and token).
        '''
        self.__connections[display["id"]] = self.__connections.get(display["id"], 0) + 1
        display["lastSeen"] = _now_ms()
        display["address"] = connection.address
        self.__save()
        await connection.send(protocol.json_frame(
            protocol.AUTH_RESULT, protocol.CONFIG_STATUS_OK,
            {"ok": True, "deviceId": display["id"], "name": display["name"], **extra}))
        await self.__broadcast_displays()
        return {"id": display["id"], "name": display["name"]}

    async def __refuse(self, connection, reason: str, message: str = "",
                       retry_after: float = 0) -> None:
        '''
        Tells a display why it may not in, and returns None for authenticate().
        Arguments:
            connection: The handshake channel.
            reason (str): An AUTH_REASON_* value.
            message (str): Finnish text for the login dialog; a default per reason.
            retry_after (float): Seconds a throttled address must wait.
        '''
        document = {"ok": False, "reason": reason,
                    "message": message or _REFUSALS.get(reason, "Kirjautuminen epäonnistui")}
        if retry_after > 0:
            document["retryAfter"] = int(retry_after + 0.999)
        if reason != protocol.AUTH_REASON_TOKEN:
            logger.info("Login refused for %s: %s", connection.address, reason)
        await connection.send(protocol.json_frame(
            protocol.AUTH_RESULT, protocol.CONFIG_STATUS_ERROR, document))
        return None

    def __lockout_remaining(self, address: str) -> float:
        '''
        Seconds before this address may try a password again (0 = now).
        Arguments:
            address (str): The client's IP address.
        '''
        count, last = self.__failures.get(address, (0, 0.0))
        if count < _FREE_FAILURES:
            return 0.0
        delay = min(2 ** (count - _FREE_FAILURES + 1), _MAX_LOCKOUT_S)
        return max(0.0, last + delay - time.monotonic())

    def __record_failure(self, address: str) -> None:
        '''
        Counts a wrong password from an address, forgetting addresses that have
        been quiet for longer than the longest lockout.
        Arguments:
            address (str): The client's IP address.
        '''
        now = time.monotonic()
        self.__failures = {a: f for a, f in self.__failures.items()
                           if now - f[1] < _MAX_LOCKOUT_S}
        count = self.__failures.get(address, (0, 0.0))[0] + 1
        self.__failures[address] = (count, now)
        logger.warning("Wrong password from %s (%d in a row)", address, count)

    # ── Ylläpito › Näytöt ─────────────────────────────────────────────

    def __displays_frame(self) -> bytes:
        '''The AUTH_DISPLAYS frame: every remembered display, oldest first.'''
        self.__prune()
        displays = [{
            "id": d["id"],
            "name": d.get("name", ""),
            "address": d.get("address", ""),
            "created": d.get("created", 0),
            "lastSeen": d.get("lastSeen", 0),
            "connected": self.__connections.get(d["id"], 0) > 0,
        } for d in sorted(self.__displays.values(), key=lambda d: d.get("created", 0))]
        return protocol.json_frame(protocol.AUTH_DISPLAYS, protocol.CONFIG_STATUS_OK,
                                   {"displays": displays})

    async def __broadcast_displays(self) -> None:
        '''Sends the display list to every logged-in client.'''
        if self.__server is not None:
            await self.__server.broadcast(self.__displays_frame())

    async def handle_get_displays(self, _payload: bytes, writer) -> None:
        '''
        AUTH_GET_DISPLAYS handler: the list, to the requester.
        Arguments:
            _payload (bytes): Empty.
            writer (StreamWriter): The requesting client.
        '''
        await self.__server.send_to(writer, self.__displays_frame())

    async def handle_revoke(self, payload: bytes, writer) -> None:
        '''
        AUTH_REVOKE handler: forgets a display's login and closes its
        connections — which may be the requester's own.  The list goes to
        everyone either way, so an unknown id just refreshes the requester.
        Arguments:
            payload (bytes): len(4B) + JSON {"id"}.
            writer (StreamWriter): The requesting client.
        '''
        try:
            display_id = protocol.parse_json_body(payload).get("id")
        except ValueError:
            display_id = None
        display = self.__displays.pop(display_id, None) if isinstance(display_id, str) else None
        if display is None:
            await self.__server.send_to(writer, self.__displays_frame())
            return
        logger.info("Display login revoked: %s (%s)", display.get("name"), display_id)
        self.__save()
        await self.__broadcast_displays()
        await self.__server.disconnect(display_id)

    def apply_config(self) -> None:
        '''Hook "auth": takes the new login lifetime and forgets what it ends.'''
        self.__lifetime_days = self.__config.auth_config["tokenLifetimeDays"]
        self.__prune()

    def health(self) -> dict:
        '''The login's standing, for the Järjestelmän tila card.'''
        lifetime = ("Ei vanhene" if self.__lifetime_days <= 0
                    else f"{self.__lifetime_days} pv käyttämättä")
        config = [["Kirjautuneita näyttöjä", str(len(self.__displays))],
                  ["Kirjautuminen vanhenee", lifetime],
                  ["Varmenne", self.__binding.hex(":")[:23].upper() + "…"]]
        if self.__verifier is None:
            return {"state": "error", "detail": "Salasanaa ei ole asetettu (.env)",
                    "config": config}
        return {"state": "ok", "detail": "Salattu yhteys, salasana käytössä", "config": config}


# The login dialog's line per refusal.
_REFUSALS = {
    protocol.AUTH_REASON_TOKEN: "Kirjautuminen ei ole enää voimassa",
    protocol.AUTH_REASON_PASSWORD: "Väärä salasana",
    protocol.AUTH_REASON_NO_PASSWORD: "Palvelimelle ei ole asetettu salasanaa",
    protocol.AUTH_REASON_THROTTLED: "Liian monta väärää salasanaa",
    protocol.AUTH_REASON_BINDING: "Palvelimen varmenne ei täsmää — yhteys ei ole turvallinen",
    protocol.AUTH_REASON_PROTOCOL: "Kirjautuminen epäonnistui",
}
