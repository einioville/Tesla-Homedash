# `server/server.py` — the TLS server

`Server` owns the active-connection map and a `msg_type → handler` registry. It listens with TLS 1.3
(the `ssl_context` it is built with, `auth_service`'s self-signed certificate) on `host` — `0.0.0.0`,
or `127.0.0.1` when `server.reachability` is `local` (`Config.listen_host`) — and hands every new
connection to its **authenticator** before anything else happens on it. Handlers are invoked
as `handler(payload, writer)` — the writer lets request/response handlers reply to just the
requesting client via `send_to`; passing it keeps the server protocol-agnostic (it still only moves
bytes + the connection). `broadcast` sends a pre-framed packet to all clients in parallel (one task
per client, gathered with `return_exceptions=True`); `send_to` targets one client.
`clients()` lists the connected peers (`{address, port, since_ms, id, name}`, kept in `__peers`
beside the connection map) for the status view's server card; `disconnect(identity_id)` closes
every connection logged in as one display (a revoked login). `__handle_connection` runs the login,
then the on-connect **snapshot** (each registered service's `stream_everything(writer)`), then the
read loop. **Communicates with:** every service, but only as a dumb byte pipe — it never calls a
concrete service method, and the only protocol facts it knows are `MSG_TERMINATE` (ends the
connection) and the `MAX_MSG_SIZE` / `MAX_PREAUTH_MSG_SIZE` caps.

**The login gate.** The authenticator is duck-typed (`AuthService`, `../auth_service/CLAUDE.md`):
`authenticate(handshake)` returns an identity `{id, name}` or `None`, and `disconnected(identity)` is
called when an admitted connection ends. `_Handshake` is the channel it talks over — framed
`recv()` / `send()` with inbound messages capped at `MAX_PREAUTH_MSG_SIZE` (4 KB) — so the server
still frames everything and the authenticator never touches a stream. A connection enters
`__active_connections` / `__peers` only once admitted, which is what keeps broadcasts and handlers
away from a client that has not logged in. A failed TLS handshake (a plaintext client, the
frontend's reachability `Probe`) never reaches `__handle_connection`, and asyncio logs it only in
debug mode.

> **Load-bearing invariants — do not break:**
> - **No recv/inactivity timeout once logged in.** The frontend only sends on user interaction;
>   idle is normal. Never wrap the read loop's `_recv_message()` in `asyncio.wait_for`. Dead peers
>   surface as `IncompleteReadError`/`ConnectionError`; use TCP keepalive if you must detect them.
>   The login is the exception: `_LOGIN_TIMEOUT_S` (30 s, room for a Pi deriving its SCRAM key)
>   bounds it, and `_TLS_HANDSHAKE_TIMEOUT_S` (15 s) the handshake before it.
> - **Broadcast never blocks on one slow client** — keep the per-client task fan-out.
> - **A write to a closed connection is skipped, not attempted.** asyncio's TLS transport raises
>   `AttributeError` on a write once it has been closed twice, not an `OSError`, so `__safe_write`
>   checks `is_closing()` first. The spectrum's 30 frames a second hit this whenever a display left
>   mid-frame.
> - **Snapshot `__active_connections` keys before iterating** (`list(...)`) — concurrent
>   disconnects pop entries.
> - **Enforce `MAX_MSG_SIZE`** (1 MB) in the read loop and `MAX_PREAUTH_MSG_SIZE` before login.
> - **Server stays protocol-agnostic** — route via `register_handler`, snapshot via
>   `register_service`, login via the authenticator. `MSG_TERMINATE` is the one code it handles
>   itself; add no other `if msg_type == ...`.
