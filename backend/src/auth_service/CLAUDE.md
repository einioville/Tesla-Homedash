# `auth_service/` — encryption and the display login (issue #64)

Who may use the backend. `tls.py` keeps the certificate, `scram.py` is the password exchange, and
`AuthService` (`auth_service.py`) is the login gate `Server` runs on every connection
(`../server/CLAUDE.md`), the list of displays that have logged in, and their protocol codes.

## The certificate — `tls.py`

ECDSA P-256, self-signed, created on first start in `<config dir>/tls/` (`cert.pem`, `key.pem`
0600, the directory 0700) and recreated when missing or unusable. TLS 1.3 only. **No CA and no host
name are involved on purpose**: a display trusts the certificate because the backend proved it
knows the password over a connection bound to it, and from then on compares its SHA-256 (the pin).
So validity dates and the subject do not matter, and a new certificate makes every display log in
again. `end_point_hash()` is that SHA-256 — both the pin and SCRAM's channel binding
(`tls-server-end-point`, RFC 5929: the hash of the certificate with its signature's hash).

## The exchange

```
backend → AUTH_HELLO {passwordSet}
display → AUTH_TOKEN {deviceId, token}                       a remembered login
          or AUTH_SCRAM_START {message: "p=tls-server-end-point,,n=homedash,r=<nonce>"}
backend → AUTH_SCRAM_CHALLENGE {message: "r=…,s=<salt>,i=<rounds>"}
display → AUTH_SCRAM_PROOF {message: "c=<binding>,r=…,p=<proof>", name}
backend → AUTH_RESULT {ok, reason, message, retryAfter?, serverFinal?, deviceId?, token?, name?}
          then, when ok, the snapshot and the ordinary protocol
```

- **SCRAM-SHA-256-PLUS** (RFC 5802 / 7677) — the password never crosses the wire, and the backend
  proves it knows the verifier (`serverFinal`), which is what lets a display pin a certificate it
  has never seen. The binding is inside the proof, so a man in the middle with its own certificate
  cannot complete it (`binding` refusal). A client without channel binding (`n,,` / `y,,`) is
  refused. `scram.py` reproduces RFC 7677's test vector (`backend/tests/test_auth.py`); the
  frontend's half is `frontend_v2/core/scram.cpp` — **change both together**.
- **Rounds: `scram.ITERATIONS` = 200 000**, because Qt's PBKDF2 runs ~10× slower than OpenSSL's (a
  few seconds on a Pi 4, paid once per login). The display refuses fewer than 100 000, so a
  man in the middle cannot ask for a cheap key. The rounds only slow an attacker who captured an
  exchange — the plaintext is in `.env` on this host anyway.
- **Password normalisation is NFKC** on both sides (the core of SASLprep).
- **Tokens** are 256 random bits (`secrets.token_urlsafe(32)`); the store keeps only their SHA-256.
  A token login needs no SCRAM: the pinned certificate already authenticates the backend.

## The store — `paired_displays.json`

Beside `config.json`, 0600, written with `write_atomic`: `{version, scram: {salt, iterations,
storedKey, serverKey}, displays: [{id, name, tokenHash, created, lastSeen, address}]}`. **The
password is `TESLA_HOMEDASH_PASSWORD` in `.env`**, never a setting. At start the stored verifier is
re-derived from it with the stored salt: the same password keeps every display (a new round count
re-derives silently), a different one — or none — **forgets every display**. With no password the
backend runs, `AUTH_HELLO` says `passwordSet: false`, and every login is refused `noPassword`.

## Rules worth knowing

- **Lifetime counts from last use**: `auth.tokenLifetimeDays` (0 = never; `Config.auth_config`,
  the Ylläpito › Näytöt card's dropdown, hook `auth`). A display that is connected never expires;
  `lastSeen` is stamped when it connects and when it leaves. Expired logins are forgotten when one
  tries to log in, when the list is built and when the setting changes — there is no timer.
- **Wrong passwords are throttled per address**: three are free (typos on a touch keyboard), then
  the wait doubles from 2 s to 5 min (`throttled` with `retryAfter`). Token failures are not
  counted — 256 random bits are not guessable.
- **The list (`AUTH_DISPLAYS`) is broadcast on every change** — a login, a revoke, a display
  connecting or leaving. A just-admitted display is not in the server's map yet when its own login
  is broadcast, so it asks (`AUTH_GET_DISPLAYS`) when its card is built.
- **`AUTH_REVOKE` closes the display's connections** (`Server.disconnect`), the requester's own
  included; the display then reconnects, its token is refused, and it asks for the password.
- `health()` is the *Kirjautuminen* card in Järjestelmän tila: `error` with no password, otherwise
  the number of displays, the lifetime and the certificate's fingerprint.

Tests: `uv run python tests/test_auth.py` (from `backend/`) — the RFC vector, and whole logins over
TLS against a `Server` on a spare port: password, token, wrong password, binding, revoke, throttle,
a changed and a missing password, expiry.
