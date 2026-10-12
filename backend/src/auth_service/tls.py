'''
The backend's TLS certificate: created on first start, kept beside config.json,
and pinned by every display that logs in.

Self-signed on purpose.  No certificate authority vouches for a dashboard on a
home network; a display trusts this certificate because the backend proved it
knows the password over a connection bound to it (scram.py), and from then on
compares it byte for byte.  For the same reason the validity period and the
host name in it do not matter — nothing checks them.
'''
from __future__ import annotations

import datetime
import hashlib
import logging
import os
import socket
import ssl

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from ..utils.atomic_write import write_atomic

logger = logging.getLogger("auth_service.tls")

CERT_FILE = "cert.pem"
KEY_FILE = "key.pem"

_VALID_YEARS = 30


def _create(cert_path: str, key_path: str) -> None:
    '''
    Writes a new ECDSA P-256 key and a self-signed certificate for it.
    Arguments:
        cert_path (str): Where the certificate goes.
        key_path (str): Where the private key goes (0600).
    '''
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,
                                         f"Tesla-Homedash {socket.gethostname()}"[:64])])
    now = datetime.datetime.now(datetime.timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=365 * _VALID_YEARS))
        .sign(key, hashes.SHA256())
    )
    write_atomic(key_path, key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii"), mode=0o600)
    write_atomic(cert_path, certificate.public_bytes(serialization.Encoding.PEM).decode("ascii"),
                 mode=0o644)


def load_or_create(directory: str) -> tuple[ssl.SSLContext, bytes]:
    '''
    The server's TLS context and the channel binding data for its certificate,
    creating the key and certificate when they are missing or unusable.  A new
    certificate makes every display log in again: its pin no longer matches.
    Arguments:
        directory (str): Where cert.pem and key.pem live (created 0700).
    '''
    os.makedirs(directory, mode=0o700, exist_ok=True)
    cert_path = os.path.join(directory, CERT_FILE)
    key_path = os.path.join(directory, KEY_FILE)
    try:
        return _load(cert_path, key_path)
    except FileNotFoundError:
        logger.info("Creating a TLS certificate in %s", directory)
    except (OSError, ValueError) as e:
        logger.error("The TLS certificate in %s is unusable, creating a new one: %s: %s",
                     directory, type(e).__name__, e)
    _create(cert_path, key_path)
    return _load(cert_path, key_path)


def _load(cert_path: str, key_path: str) -> tuple[ssl.SSLContext, bytes]:
    '''
    Builds the TLS 1.3 server context from the key and certificate files.
    Raises OSError (ssl.SSLError is one) or ValueError when they are unusable.
    Arguments:
        cert_path (str): The certificate, PEM.
        key_path (str): Its private key, PEM.
    '''
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.load_cert_chain(cert_path, key_path)
    with open(cert_path, encoding="ascii") as fh:
        der = ssl.PEM_cert_to_DER_cert(fh.read())
    return context, end_point_hash(der)


def end_point_hash(der: bytes) -> bytes:
    '''
    The tls-server-end-point channel binding data (RFC 5929 §4.1): the hash of
    the certificate with its signature's hash function, SHA-256 here.  Also the
    certificate's fingerprint, which is what a display pins.
    Arguments:
        der (bytes): The certificate, DER-encoded.
    '''
    return hashlib.sha256(der).digest()
