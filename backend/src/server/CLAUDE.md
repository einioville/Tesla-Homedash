# `server/server.py` — the TCP server

`Server` owns the active-connection map and a `msg_type → handler` registry. Handlers are invoked
as `handler(payload, writer)` — the writer lets request/response handlers reply to just the
requesting client via `send_to`; passing it keeps the server protocol-agnostic (it still only moves
bytes + the connection). `broadcast` sends a pre-framed packet to all clients in parallel (one task
per client, gathered with `return_exceptions=True`); `send_to` targets one client.
`clients()` lists the connected peers (`{address, port, since_ms}`, kept in `__peers` beside the
connection map) for the status view's server card. `__handle_connection` runs the on-connect
**snapshot** (each registered service's `stream_everything(writer)`), then the read loop. **Communicates with:** every service, but only as
a dumb byte pipe — it never calls a concrete service method, and the only protocol facts it knows are
`MSG_TERMINATE` (ends the connection) and the `MAX_MSG_SIZE` cap.

> **Load-bearing invariants — do not break:**
> - **No recv/inactivity timeout.** The frontend only sends on user interaction; idle is
>   normal. Never wrap `__recv_message()` in `asyncio.wait_for`. Dead peers surface as
>   `IncompleteReadError`/`ConnectionError`; use TCP keepalive if you must detect them.
> - **Broadcast never blocks on one slow client** — keep the per-client task fan-out.
> - **Snapshot `__active_connections` keys before iterating** (`list(...)`) — concurrent
>   disconnects pop entries.
> - **Enforce `MAX_MSG_SIZE`** (1 MB) in `__recv_message()`.
> - **Server stays protocol-agnostic** — route via `register_handler`, snapshot via
>   `register_service` (duck-typed `stream_everything`). `MSG_TERMINATE` is the one code it handles
>   itself; add no other `if msg_type == ...`.
