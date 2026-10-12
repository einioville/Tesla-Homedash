'''
SCRAM-SHA-256 (RFC 5802 / RFC 7677), the server's half.

The login a display makes once: it proves it knows the password without
sending it, and the backend proves it knows the password's verifier, which is
what lets the display trust a certificate it has never seen.  With channel
binding (`tls-server-end-point`, RFC 5929) the proof also covers the hash of
the certificate the display saw, so a man in the middle presenting its own
certificate cannot complete the exchange.

Pure functions and one small state object; no I/O.  The frontend's half is
ServerClient in frontend_v2/core/serverclient.cpp — keep the two in step.
'''
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import unicodedata
from typing import NamedTuple

from ..utils import protocol

# What a display sends as its gs2 header: channel binding required, the
# tls-server-end-point type, no authorization identity.
GS2_HEADER = "p=tls-server-end-point,,"

# PBKDF2 rounds for a new verifier.  The display derives the same key with Qt's
# PBKDF2, which runs about ten times slower than OpenSSL's: 200 000 rounds is a
# third of a second on a desktop and a few seconds on a Raspberry Pi 4, paid once
# per login.  The rounds only slow an attacker who captured a login exchange; the
# plaintext password sits in the backend's .env anyway.
ITERATIONS = 200_000


class ScramError(Exception):
    '''
    A failed exchange.  `reason` is a protocol.AUTH_REASON_* value.
    Arguments:
        reason (str): AUTH_REASON_PASSWORD, _BINDING or _PROTOCOL.
    '''

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class Verifier(NamedTuple):
    '''What the backend keeps instead of the password (RFC 5802 §5.1).'''
    salt: bytes
    iterations: int
    stored_key: bytes
    server_key: bytes


def normalize(password: str) -> bytes:
    '''
    The password as SCRAM hashes it.  NFKC, the core of SASLprep, so a display
    typing a composed "ä" and a .env holding a decomposed one agree; the frontend
    applies the same form.
    Arguments:
        password (str): The password as typed or as written in .env.
    '''
    return unicodedata.normalize("NFKC", password).encode("utf-8")


def derive(password: str, salt: bytes, iterations: int) -> Verifier:
    '''
    Derives the verifier for a password.
    Arguments:
        password (str): The plaintext password.
        salt (bytes): The verifier's salt.
        iterations (int): PBKDF2 rounds.
    '''
    salted = hashlib.pbkdf2_hmac("sha256", normalize(password), salt, iterations)
    client_key = hmac.digest(salted, b"Client Key", "sha256")
    return Verifier(
        salt=salt,
        iterations=iterations,
        stored_key=hashlib.sha256(client_key).digest(),
        server_key=hmac.digest(salted, b"Server Key", "sha256"),
    )


def new_verifier(password: str) -> Verifier:
    '''
    A verifier with a fresh random salt and the current round count.
    Arguments:
        password (str): The plaintext password.
    '''
    return derive(password, secrets.token_bytes(16), ITERATIONS)


def _attributes(text: str) -> list[tuple[str, str]]:
    '''
    Splits "a=1,b=2" into [("a", "1"), ("b", "2")].  Raises ScramError for a
    part that is not a one-letter attribute.
    Arguments:
        text (str): A comma-separated SCRAM attribute list.
    '''
    pairs = []
    for part in text.split(","):
        if len(part) < 2 or part[1] != "=" or not part[0].isalpha():
            raise ScramError(protocol.AUTH_REASON_PROTOCOL)
        pairs.append((part[0], part[2:]))
    return pairs


def _b64decode(text: str) -> bytes:
    '''
    Strict base64.  Raises ScramError rather than binascii.Error.
    Arguments:
        text (str): Base64 text.
    '''
    try:
        return base64.b64decode(text, validate=True)
    except ValueError as e:
        raise ScramError(protocol.AUTH_REASON_PROTOCOL) from e


class ServerExchange:
    '''
    One login attempt, server side: first() answers the client-first-message,
    final() checks the client-final-message.  Raises ScramError on any failure;
    an exchange is not reusable after one.
    Arguments:
        verifier (Verifier): The password's verifier.
        gs2_header (str): The gs2 header the client must have sent, GS2_HEADER
            in production ("n,," reproduces the RFC's test vector).
        binding (bytes): The channel binding data — the SHA-256 of this server's
            certificate (DER); empty for "n,,".
        server_nonce (str | None): Fixed only by tests.
    '''

    def __init__(self, verifier: Verifier, gs2_header: str = GS2_HEADER,
                 binding: bytes = b"", server_nonce: str | None = None):
        self.__verifier = verifier
        self.__gs2_header = gs2_header
        self.__binding = binding
        self.__server_nonce = server_nonce or base64.b64encode(
            secrets.token_bytes(18)).decode("ascii")
        self.__client_first_bare = ""
        self.__server_first = ""
        self.__nonce = ""

    def first(self, client_first: str) -> str:
        '''
        Checks the client-first-message and returns the server-first-message.
        Arguments:
            client_first (str): e.g. "p=tls-server-end-point,,n=homedash,r=<nonce>".
        '''
        parts = client_first.split(",", 2)
        if len(parts) != 3:
            raise ScramError(protocol.AUTH_REASON_PROTOCOL)
        # A client that offers no binding ("n" / "y") would let a man in the
        # middle relay the exchange, so only the header we expect is accepted.
        if parts[0] + "," + parts[1] + "," != self.__gs2_header:
            raise ScramError(protocol.AUTH_REASON_BINDING)
        bare = parts[2]
        attributes = _attributes(bare)
        if len(attributes) < 2 or attributes[0][0] != "n" or attributes[1][0] != "r":
            raise ScramError(protocol.AUTH_REASON_PROTOCOL)
        # An "m" attribute or anything after the nonce is an extension this
        # server does not know, and RFC 5802 says to refuse it.
        if len(attributes) != 2 or not attributes[1][1]:
            raise ScramError(protocol.AUTH_REASON_PROTOCOL)
        client_nonce = attributes[1][1]
        if not all(0x21 <= ord(ch) <= 0x7E and ch != "," for ch in client_nonce):
            raise ScramError(protocol.AUTH_REASON_PROTOCOL)
        self.__client_first_bare = bare
        self.__nonce = client_nonce + self.__server_nonce
        salt = base64.b64encode(self.__verifier.salt).decode("ascii")
        self.__server_first = f"r={self.__nonce},s={salt},i={self.__verifier.iterations}"
        return self.__server_first

    def final(self, client_final: str) -> str:
        '''
        Checks the client-final-message and returns the server-final-message
        ("v=<ServerSignature>").
        Arguments:
            client_final (str): e.g. "c=<binding>,r=<nonce>,p=<proof>".
        '''
        if not self.__server_first:
            raise ScramError(protocol.AUTH_REASON_PROTOCOL)
        cut = client_final.rfind(",p=")
        if cut < 0:
            raise ScramError(protocol.AUTH_REASON_PROTOCOL)
        without_proof = client_final[:cut]
        proof = _b64decode(client_final[cut + 3:])
        attributes = _attributes(without_proof)
        if len(attributes) != 2 or attributes[0][0] != "c" or attributes[1][0] != "r":
            raise ScramError(protocol.AUTH_REASON_PROTOCOL)
        if attributes[1][1] != self.__nonce:
            raise ScramError(protocol.AUTH_REASON_PROTOCOL)
        expected_binding = self.__gs2_header.encode("ascii") + self.__binding
        if not hmac.compare_digest(_b64decode(attributes[0][1]), expected_binding):
            raise ScramError(protocol.AUTH_REASON_BINDING)

        auth_message = ",".join(
            (self.__client_first_bare, self.__server_first, without_proof)).encode("utf-8")
        client_signature = hmac.digest(self.__verifier.stored_key, auth_message, "sha256")
        if len(proof) != len(client_signature):
            raise ScramError(protocol.AUTH_REASON_PASSWORD)
        client_key = bytes(a ^ b for a, b in zip(proof, client_signature))
        if not hmac.compare_digest(hashlib.sha256(client_key).digest(),
                                   self.__verifier.stored_key):
            raise ScramError(protocol.AUTH_REASON_PASSWORD)
        server_signature = hmac.digest(self.__verifier.server_key, auth_message, "sha256")
        return "v=" + base64.b64encode(server_signature).decode("ascii")
