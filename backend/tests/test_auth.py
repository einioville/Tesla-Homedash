'''
Tests for the login (issue #64): SCRAM-SHA-256 against RFC 7677's test vector,
then whole logins over real TLS against a Server on a spare port — a password
login, a token reconnect, a wrong password, a revoke, a changed and a missing
password, and an expired login.

Runs under pytest, or standalone: `python backend/tests/test_auth.py`.
'''
import asyncio
import base64
import hashlib
import hmac
import json
import os
import shutil
import socket
import ssl
import struct
import sys
import tempfile
import time
import unicodedata

# Make `src` importable whether run via pytest or directly.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.auth_service import scram  # noqa: E402
from src.auth_service.auth_service import STORE_FILE, AuthService  # noqa: E402
from src.server.server import Server  # noqa: E402
from src.utils import protocol  # noqa: E402
from src.utils.config_parser import Config  # noqa: E402

TEMPLATE = os.path.join(os.path.dirname(__file__), "..", "..", "config_template.json")
SNAPSHOT_TYPE = 0x04


# ── SCRAM ────────────────────────────────────────────────────────────────

def test_scram_rfc7677_vector():
    # RFC 7677 §3: user "user", password "pencil", no channel binding.
    verifier = scram.derive("pencil", base64.b64decode("W22ZaJ0SNY7soEsUEjb6gQ=="), 4096)
    exchange = scram.ServerExchange(verifier, gs2_header="n,,",
                                    server_nonce="%hvYDpWUa2RaTCAfuxFIlj)hNlF$k0")
    assert exchange.first("n,,n=user,r=rOprNGfwEbeRWgbNEkqO") == (
        "r=rOprNGfwEbeRWgbNEkqO%hvYDpWUa2RaTCAfuxFIlj)hNlF$k0,s=W22ZaJ0SNY7soEsUEjb6gQ==,i=4096")
    assert exchange.final(
        "c=biws,r=rOprNGfwEbeRWgbNEkqO%hvYDpWUa2RaTCAfuxFIlj)hNlF$k0,"
        "p=dHzbZapWIk4jUhN+Ute9ytag9zjfMHgsqmmiz7AndVQ=") == (
        "v=6rriTRBi23WpRR/wtup+mMhUZUn/dB5nLTJRsjl95G4=")


def _client_exchange(password, server_first, binding, client_first_bare):
    '''The client's half of SCRAM, as the frontend computes it.'''
    attrs = dict(part.split("=", 1) for part in server_first.split(","))
    salted = hashlib.pbkdf2_hmac(
        "sha256", unicodedata.normalize("NFKC", password).encode(),
        base64.b64decode(attrs["s"]), int(attrs["i"]))
    client_key = hmac.digest(salted, b"Client Key", "sha256")
    stored_key = hashlib.sha256(client_key).digest()
    cbind = base64.b64encode(scram.GS2_HEADER.encode() + binding).decode()
    without_proof = f"c={cbind},r={attrs['r']}"
    auth_message = f"{client_first_bare},{server_first},{without_proof}".encode()
    signature = hmac.digest(stored_key, auth_message, "sha256")
    proof = bytes(a ^ b for a, b in zip(client_key, signature))
    server_key = hmac.digest(salted, b"Server Key", "sha256")
    expected = "v=" + base64.b64encode(
        hmac.digest(server_key, auth_message, "sha256")).decode()
    return f"{without_proof},p={base64.b64encode(proof).decode()}", expected


def test_scram_refuses_wrong_password_and_binding():
    verifier = scram.derive("oikea", b"0123456789abcdef", 1000)
    binding = hashlib.sha256(b"cert").digest()
    for password, seen, reason in (("väärä", binding, protocol.AUTH_REASON_PASSWORD),
                                   ("oikea", hashlib.sha256(b"other").digest(),
                                    protocol.AUTH_REASON_BINDING)):
        exchange = scram.ServerExchange(verifier, binding=binding)
        bare = "n=homedash,r=abcdef"
        server_first = exchange.first(scram.GS2_HEADER + bare)
        final, _ = _client_exchange(password, server_first, seen, bare)
        try:
            exchange.final(final)
        except scram.ScramError as e:
            assert e.reason == reason, (e.reason, reason)
        else:
            raise AssertionError(f"accepted {password!r}")


def test_scram_requires_channel_binding():
    exchange = scram.ServerExchange(scram.derive("x", b"s" * 16, 1000), binding=b"b")
    try:
        exchange.first("n,,n=homedash,r=abc")
    except scram.ScramError as e:
        assert e.reason == protocol.AUTH_REASON_BINDING
    else:
        raise AssertionError("a client without channel binding was accepted")


# ── Whole logins over TLS ────────────────────────────────────────────────

class _Snapshot:
    '''A registered service whose snapshot is one recognisable frame.'''

    async def stream_everything(self, writer):
        writer.write(protocol.frame(SNAPSHOT_TYPE, b"snapshot"))
        await writer.drain()


class _Client:
    '''A display: TLS without verification, then the login, like ServerClient.'''

    def __init__(self, port):
        self.port = port
        self.reader = None
        self.writer = None
        self.binding = b""

    async def open(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        self.reader, self.writer = await asyncio.open_connection(
            "127.0.0.1", self.port, ssl=context)
        der = self.writer.get_extra_info("ssl_object").getpeercert(binary_form=True)
        self.binding = hashlib.sha256(der).digest()
        msg_type, document = await self.recv()
        assert msg_type == protocol.AUTH_HELLO
        return document

    async def recv(self):
        (length,) = struct.unpack("!I", await self.reader.readexactly(4))
        body = await self.reader.readexactly(length)
        payload = body[1:]
        if body[0] == SNAPSHOT_TYPE:
            return body[0], payload
        (size,) = struct.unpack("!I", payload[1:5])
        return body[0], json.loads(payload[5:5 + size])

    def send(self, msg_type, document):
        body = json.dumps(document).encode()
        self.writer.write(protocol.frame(msg_type, struct.pack("!I", len(body)) + body))

    async def password_login(self, password, binding=None):
        bare = "n=homedash,r=" + base64.b64encode(os.urandom(18)).decode()
        self.send(protocol.AUTH_SCRAM_START, {"message": scram.GS2_HEADER + bare})
        msg_type, document = await self.recv()
        if msg_type == protocol.AUTH_RESULT:
            return document
        assert msg_type == protocol.AUTH_SCRAM_CHALLENGE
        final, expected = _client_exchange(password, document["message"],
                                           binding or self.binding, bare)
        self.send(protocol.AUTH_SCRAM_PROOF, {"message": final, "name": "testinäyttö"})
        msg_type, result = await self.recv()
        assert msg_type == protocol.AUTH_RESULT
        if result["ok"]:
            assert result["serverFinal"] == expected, "the server's signature does not verify"
        return result

    async def token_login(self, device_id, token):
        self.send(protocol.AUTH_TOKEN, {"deviceId": device_id, "token": token})
        msg_type, result = await self.recv()
        assert msg_type == protocol.AUTH_RESULT
        return result

    async def closed(self):
        '''True once the server has closed this connection.'''
        try:
            while True:
                await asyncio.wait_for(self.recv(), 2)
        except (asyncio.IncompleteReadError, ConnectionError):
            return True
        except asyncio.TimeoutError:
            return False

    async def close(self):
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except (ConnectionError, ssl.SSLError):
            pass


def _free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class _Backend:
    '''A Server + AuthService on a temporary config directory and a spare port.'''

    def __init__(self, directory, password, lifetime_days=0):
        config_path = os.path.join(directory, "backend_config.json")
        if not os.path.exists(config_path):
            shutil.copy(TEMPLATE, config_path)
        with open(config_path, encoding="utf-8") as fh:
            data = json.load(fh)
        data["auth"] = {"tokenLifetimeDays": lifetime_days}
        with open(config_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        self.config = Config(config_path)
        self.auth = AuthService(self.config, password)
        self.server = Server(ssl_context=self.auth.ssl_context, authenticator=self.auth,
                             host="127.0.0.1")
        self.server.PORT = _free_port()
        self.auth.attach_server(self.server)
        self.server.register_service(_Snapshot())
        self.server.register_handler(protocol.AUTH_GET_DISPLAYS, self.auth.handle_get_displays)
        self.server.register_handler(protocol.AUTH_REVOKE, self.auth.handle_revoke)
        self.task = None

    async def __aenter__(self):
        self.task = asyncio.create_task(self.server.start())
        await asyncio.sleep(0.2)
        return self

    async def __aexit__(self, *exc):
        self.task.cancel()
        try:
            await self.task
        except asyncio.CancelledError:
            pass

    def client(self):
        return _Client(self.server.PORT)


async def _login_flow(directory):
    async with _Backend(directory, "salasana") as backend:
        client = backend.client()
        assert (await client.open()) == {"passwordSet": True}
        result = await client.password_login("salasana")
        assert result["ok"] and result["name"] == "testinäyttö", result
        # The snapshot follows at once: the display list is broadcast before the
        # new connection is in the server's map, so it asks for that itself.
        assert (await client.recv()) == (SNAPSHOT_TYPE, b"snapshot")
        client.send(protocol.AUTH_GET_DISPLAYS, {})
        msg_type, document = await client.recv()
        assert msg_type == protocol.AUTH_DISPLAYS and document["displays"][0]["connected"]
        assert backend.server.clients()[0]["name"] == "testinäyttö"
        device_id, token = result["deviceId"], result["token"]
        await client.close()
        await asyncio.sleep(0.1)

        with open(os.path.join(directory, STORE_FILE), encoding="utf-8") as fh:
            store = json.load(fh)
        assert token not in json.dumps(store), "the token itself was stored"
        assert oct(os.stat(os.path.join(directory, STORE_FILE)).st_mode & 0o777) == "0o600"

        client = backend.client()
        await client.open()
        assert (await client.token_login(device_id, token))["ok"]
        await client.close()

        client = backend.client()
        await client.open()
        result = await client.token_login(device_id, "arvaus")
        assert not result["ok"] and result["reason"] == protocol.AUTH_REASON_TOKEN
        assert await client.closed()

        client = backend.client()
        await client.open()
        result = await client.password_login("väärä")
        assert not result["ok"] and result["reason"] == protocol.AUTH_REASON_PASSWORD

        client = backend.client()
        await client.open()
        result = await client.password_login("salasana", binding=b"\0" * 32)
        assert not result["ok"] and result["reason"] == protocol.AUTH_REASON_BINDING

        # Revoking a display closes its connection and its token stops working.
        victim = backend.client()
        await victim.open()
        assert (await victim.token_login(device_id, token))["ok"]
        admin = backend.client()
        await admin.open()
        assert (await admin.password_login("salasana"))["ok"]
        admin.send(protocol.AUTH_REVOKE, {"id": device_id})
        assert await victim.closed(), "the revoked display stayed connected"
        await admin.close()
        client = backend.client()
        await client.open()
        assert (await client.token_login(device_id, token))["reason"] == protocol.AUTH_REASON_TOKEN
    return token


async def _throttle_flow(directory):
    async with _Backend(directory, "salasana") as backend:
        # Three wrong passwords are free; the fourth try has to wait, even with
        # the right password.
        for attempt in range(3):
            client = backend.client()
            await client.open()
            result = await client.password_login("väärä")
            assert result["reason"] == protocol.AUTH_REASON_PASSWORD
        client = backend.client()
        await client.open()
        result = await client.password_login("salasana")
        assert result["reason"] == protocol.AUTH_REASON_THROTTLED and result["retryAfter"] >= 1


async def _password_change_flow(directory):
    async with _Backend(directory, "vanha") as backend:
        client = backend.client()
        await client.open()
        result = await client.password_login("vanha")
        assert result["ok"]
        await client.close()
    device_id, token = result["deviceId"], result["token"]

    # The same password keeps the login across a restart.
    async with _Backend(directory, "vanha") as backend:
        client = backend.client()
        await client.open()
        assert (await client.token_login(device_id, token))["ok"]
        await client.close()

    # Another password forgets it.
    async with _Backend(directory, "uusi") as backend:
        client = backend.client()
        await client.open()
        assert (await client.token_login(device_id, token))["reason"] == protocol.AUTH_REASON_TOKEN

    # No password: the backend runs, says so, and lets nobody in.
    async with _Backend(directory, None) as backend:
        client = backend.client()
        assert (await client.open()) == {"passwordSet": False}
        result = await client.password_login("uusi")
        assert result["reason"] == protocol.AUTH_REASON_NO_PASSWORD


async def _expiry_flow(directory):
    async with _Backend(directory, "salasana", lifetime_days=7) as backend:
        client = backend.client()
        await client.open()
        result = await client.password_login("salasana")
        await client.close()
        await asyncio.sleep(0.1)
        # Last seen eight days ago.
        store_path = os.path.join(directory, STORE_FILE)
        with open(store_path, encoding="utf-8") as fh:
            store = json.load(fh)
        store["displays"][0]["lastSeen"] = int(time.time() * 1000) - 8 * 86_400_000
        with open(store_path, "w", encoding="utf-8") as fh:
            json.dump(store, fh)
    async with _Backend(directory, "salasana", lifetime_days=7) as backend:
        client = backend.client()
        await client.open()
        result = await client.token_login(result["deviceId"], result["token"])
        assert result["reason"] == protocol.AUTH_REASON_TOKEN, result


def _run(flow):
    directory = tempfile.mkdtemp()
    try:
        return asyncio.run(flow(directory))
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def test_password_login_token_revoke():
    _run(_login_flow)


def test_wrong_passwords_are_throttled():
    _run(_throttle_flow)


def test_password_change_and_no_password():
    _run(_password_change_flow)


def test_login_expires_after_lifetime():
    _run(_expiry_flow)


if __name__ == "__main__":
    # Standalone runner so the suite works without pytest installed.
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS  {test.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL  {test.__name__}: {e}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(1 if failures else 0)
