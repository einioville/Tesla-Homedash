'''
TLS server that fans dashboard data out to all connected frontends and
routes incoming command bytes to registered service handlers.

The server is intentionally protocol-agnostic: it knows about message
length framing and a single integer message-type byte, but never about
the meaning of any specific code.  Services register handlers keyed by
those integers (see backend/src/utils/protocol.py for the authoritative
list of codes) and snapshot their state into newly connected clients via
register_service().  Before any of that a connection must log in: the
authenticator runs the exchange over a handshake channel the server
frames for it, and a connection it refuses is closed unseen.

All wiring (register_handler / register_service) must complete before
start() is called.
'''
from __future__ import annotations

import asyncio
import logging
import struct
import time
from typing import Awaitable, Callable

from ..utils import protocol

logger = logging.getLogger("server.server")

Handler = Callable[[bytes, asyncio.StreamWriter], Awaitable[None]]

# How long a new connection has to finish the TLS handshake, and then to log in.
# Generous for the login: a Raspberry Pi display derives its SCRAM key in a few
# seconds.  Once logged in there is no timeout at all (see __read_loop).
_TLS_HANDSHAKE_TIMEOUT_S = 15
_LOGIN_TIMEOUT_S = 30


class _Handshake:
    '''
    The channel an authenticator talks over before a connection is admitted:
    framed messages both ways, capped at MAX_PREAUTH_MSG_SIZE inbound.
    Arguments:
        server (Server): For its framing and safe writes.
        reader (StreamReader): The connection's reader.
        writer (StreamWriter): The connection's writer.
        address (str): The client's IP address, for logs and throttling.
    '''

    def __init__(self, server, reader, writer, address: str):
        self.__server = server
        self.__reader = reader
        self.__writer = writer
        self.address = address

    async def recv(self) -> tuple[int, bytes]:
        '''The next message as (type, payload).'''
        return await self.__server._recv_message(self.__reader, protocol.MAX_PREAUTH_MSG_SIZE)

    async def send(self, packet: bytes) -> None:
        '''
        Writes framed packets and waits until they are flushed.
        Arguments:
            packet (bytes): Built with protocol.frame / json_frame.
        '''
        self.__writer.write(packet)
        await self.__writer.drain()


class Server:
    '''
    asyncio TLS server on port 6969.  Owns the active-connections map
    and the message-type handler registry.  Services build framed packets
    (via protocol.frame) and call broadcast()/send_to() to deliver them.
    Arguments:
        ssl_context (SSLContext): The TLS context every connection uses.
        authenticator: Duck-typed login gate — async authenticate(handshake)
            returning an identity dict {"id", "name"} or None, and async
            disconnected(identity).  AuthService is the one.
        host (str): The address to listen on — 0.0.0.0 for the local network,
            127.0.0.1 for this host only (Config.listen_host).
    '''

    PORT = 6969

    def __init__(self, ssl_context, authenticator, host: str) -> None:
        self.host = host
        self.__ssl_context = ssl_context
        self.__authenticator = authenticator
        # Each writer maps to the set of in-flight handler tasks spawned by
        # incoming commands from that client.  Tasks are tracked so they can
        # be cancelled if the client disconnects mid-handler.
        self.__active_connections: dict[asyncio.StreamWriter, set[asyncio.Task]] = {}
        self.__handlers: dict[int, Handler] = {}
        self.__services: list = []  # duck-typed: any object with async stream_everything(client)
        self.__server: asyncio.Server | None = None
        # Who each connection is: address, port, since_ms and the identity's id
        # and name — the status view's client list, and how disconnect() finds one.
        self.__peers: dict[asyncio.StreamWriter, dict] = {}

    def register_handler(self, msg_type: int, handler: Handler) -> None:
        '''
        Registers a coroutine to invoke when a message with the given type
        byte arrives from a client.  Handlers receive the raw payload bytes
        (without the length prefix or type byte) and the requesting client's
        writer, and should return None.  The writer lets request/response
        handlers reply to just that client via send_to(); fire-and-forget
        handlers simply ignore it.  Passing the writer keeps the server
        protocol-agnostic — it still only moves bytes and the connection,
        never interpreting them.
        Arguments:
            msg_type (int): Single-byte message-type code from protocol.py.
            handler (Handler): async callable taking (payload, writer).
        '''
        if msg_type in self.__handlers:
            logger.warning("Replacing existing handler for msg_type %#x", msg_type)
        self.__handlers[msg_type] = handler

    def register_service(self, service) -> None:
        '''
        Registers a service whose stream_everything(client) coroutine will
        be invoked once for each new client connection so the frontend's UI
        can populate immediately.  Order matters only for log ordering;
        each service writes its own framed packets to the new client.
        '''
        self.__services.append(service)

    @property
    def client_count(self) -> int:
        '''Number of currently connected frontends (the status view reports it).'''
        return len(self.__active_connections)

    def clients(self) -> list[dict]:
        '''
        The connected frontends as {"address", "port", "since_ms", "id",
        "name"}, oldest first, for the status view.
        '''
        return sorted(self.__peers.values(), key=lambda peer: peer["since_ms"])

    async def disconnect(self, identity_id: str) -> None:
        '''
        Closes every connection logged in as this identity (a revoked login).
        Their read loops then end and clean up as for any disconnect.
        Arguments:
            identity_id (str): The "id" the authenticator returned.
        '''
        for writer, peer in list(self.__peers.items()):
            if peer.get("id") == identity_id:
                logger.info("Closing the connection of %s (%s)", peer.get("name"), identity_id)
                writer.close()

    async def broadcast(self, packet: bytes) -> None:
        '''
        Sends a pre-framed packet (or a concatenation of framed packets) to
        every connected client in parallel.  A slow or broken client cannot
        block the rest — each write runs in its own task and gather()
        collects results without short-circuiting.
        Arguments:
            packet (bytes): One or more length-prefixed messages already
                built by the calling service via protocol.frame().
        '''
        # A copy: __safe_write pops a client that fails mid-broadcast.
        clients = list(self.__active_connections.keys())
        if not clients:
            return
        await asyncio.gather(
            *(self.__safe_write(writer, packet) for writer in clients),
            return_exceptions=True,
        )

    async def send_to(self, writer: asyncio.StreamWriter, packet: bytes) -> None:
        '''
        Sends a pre-framed packet to a single client: a new connection's
        snapshot, or the reply to that client's request.
        Arguments:
            writer (StreamWriter): The connection to write to.
            packet (bytes): One or more length-prefixed messages.
        '''
        await self.__safe_write(writer, packet)

    async def start(self) -> None:
        '''
        Binds the TLS server and serves forever.  All handlers and services
        must already be registered before this is awaited.  A failed TLS
        handshake (a plaintext client, a bare reachability probe) never reaches
        __handle_connection, and asyncio logs it only in debug mode.
        '''
        logger.info("TLS server starting on %s:%d", self.host, self.PORT)
        self.__server = await asyncio.start_server(
            self.__handle_connection, host=self.host, port=self.PORT,
            ssl=self.__ssl_context, ssl_handshake_timeout=_TLS_HANDSHAKE_TIMEOUT_S,
        )
        async with self.__server:
            await self.__server.serve_forever()

    async def __handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = writer.get_extra_info("peername")
        # peername is (host, port) for IPv4 and (host, port, flow, scope) for IPv6.
        address, port = (peer[0], peer[1]) if isinstance(peer, tuple) and len(peer) >= 2 \
            else (str(peer), 0)

        # The login, before the connection is in any map: nothing is broadcast
        # to it and no handler can be reached until it has passed.
        identity = await self.__login(reader, writer, address)
        if identity is None:
            await self.__close(writer)
            return

        self.__active_connections[writer] = set()
        self.__peers[writer] = {"address": address, "port": port,
                                "since_ms": int(time.time() * 1000),
                                "id": identity["id"], "name": identity["name"]}
        logger.info("Client connected: %s (%s)", peer, identity["name"])

        # Snapshot pass: deliver every service's full state to the new
        # client only.  Services are awaited sequentially so concurrent
        # writes to the same writer cannot interleave.
        for service in self.__services:
            try:
                await service.stream_everything(writer)
            except Exception as e:
                logger.error(
                    "stream_everything failed for %s: %s: %s",
                    type(service).__name__, type(e).__name__, e,
                )

        try:
            await self.__read_loop(reader, writer)
        finally:
            await self.__cleanup_client(writer)
            logger.info("Client disconnected: %s (%s)", peer, identity["name"])
            try:
                await self.__authenticator.disconnected(identity)
            except Exception as e:
                logger.error("Login bookkeeping failed for %s: %s: %s",
                             identity["name"], type(e).__name__, e)

    async def __login(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, address: str
    ) -> dict | None:
        '''
        Runs the authenticator on a new connection within _LOGIN_TIMEOUT_S.
        Returns the identity, or None for a connection that must be closed.
        '''
        try:
            return await asyncio.wait_for(
                self.__authenticator.authenticate(_Handshake(self, reader, writer, address)),
                _LOGIN_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            logger.info("Login timed out: %s", address)
        except (asyncio.IncompleteReadError, ConnectionError, OSError) as e:
            logger.debug("Connection ended during login: %s: %s: %s",
                         address, type(e).__name__, e)
        except ValueError as e:
            logger.warning("Protocol error during login from %s, closing: %s", address, e)
        except Exception as e:
            logger.error("Login failed for %s: %s: %s", address, type(e).__name__, e)
        return None

    async def __read_loop(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        # No inactivity timeout: clients are display-only and may idle
        # indefinitely.  Disconnects surface as IncompleteReadError /
        # ConnectionError from readexactly().
        while True:
            try:
                msg_type, payload = await self._recv_message(reader, protocol.MAX_MSG_SIZE)
            except (asyncio.IncompleteReadError, ConnectionError, OSError) as e:
                logger.info("Client read ended: %s: %s", type(e).__name__, e)
                return
            except ValueError as e:
                # Oversized or malformed length prefix — drop the client.
                logger.warning("Protocol error from client, closing: %s", e)
                return

            if msg_type == protocol.MSG_TERMINATE:
                logger.info("Client termination message received")
                return

            handler = self.__handlers.get(msg_type)
            if handler is None:
                logger.warning("No handler registered for msg_type %#x", msg_type)
                continue

            # Visibility for inbound commands: a user-initiated control packet is
            # infrequent, so logging each arrival at INFO is cheap and makes it
            # obvious whether a frontend's command actually reached the backend.
            logger.info("Command received: msg_type %#x (payload %d bytes)", msg_type, len(payload))

            task = asyncio.create_task(self.__safe_invoke(handler, payload, writer))
            pending = self.__active_connections.get(writer)
            if pending is not None:
                pending.add(task)
                task.add_done_callback(pending.discard)

    async def _recv_message(
        self, reader: asyncio.StreamReader, max_size: int
    ) -> tuple[int, bytes]:
        '''
        Reads one framed message as (type, payload).  Raises ValueError for a
        length of 0 or over max_size.  Not private to the class: _Handshake
        reads with it too.
        Arguments:
            reader (StreamReader): The connection's reader.
            max_size (int): The largest message accepted.
        '''
        msg_len = struct.unpack("!I", await reader.readexactly(4))[0]
        # A malformed or hostile length prefix must not allocate without bound.
        if msg_len == 0 or msg_len > max_size:
            raise ValueError(f"Invalid message size: {msg_len}")

        body = await reader.readexactly(msg_len)
        msg_type = body[0]
        payload = body[1:] if msg_len > 1 else b""
        return msg_type, payload

    async def __safe_write(
        self, writer: asyncio.StreamWriter, packet: bytes
    ) -> None:
        # A closed TLS writer raises AttributeError on write, not an OSError
        # (asyncio's sslproto drops its protocol on the second close), so a
        # service that writes to a display that has just gone would crash.
        # Nothing awaits between this check and the write.
        if writer.is_closing():
            return
        try:
            writer.write(packet)
            await writer.drain()
        except (BrokenPipeError, ConnectionError, OSError) as e:
            logger.warning("Send failed, dropping client: %s: %s", type(e).__name__, e)
            self.__active_connections.pop(writer, None)

    async def __safe_invoke(
        self, handler: Handler, payload: bytes, writer: asyncio.StreamWriter
    ) -> None:
        # Per-handler isolation: one bad command must never kill the
        # connection's read loop.
        try:
            await handler(payload, writer)
        except Exception as e:
            logger.error(
                "Handler %r raised: %s: %s",
                getattr(handler, "__name__", handler), type(e).__name__, e,
            )

    async def __cleanup_client(self, writer: asyncio.StreamWriter) -> None:
        self.__peers.pop(writer, None)
        pending = self.__active_connections.pop(writer, None)
        if pending:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        await self.__close(writer)

    @staticmethod
    async def __close(writer: asyncio.StreamWriter) -> None:
        '''Closes a connection, ignoring one that is already gone.'''
        try:
            writer.close()
            await writer.wait_closed()
        except (ConnectionError, OSError):
            pass
