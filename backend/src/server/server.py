'''
TCP server that fans dashboard data out to all connected frontends and
routes incoming command bytes to registered service handlers.

The server is intentionally protocol-agnostic: it knows about message
length framing and a single integer message-type byte, but never about
the meaning of any specific code.  Services register handlers keyed by
those integers (see backend/src/utils/protocol.py for the authoritative
list of codes) and snapshot their state into newly connected clients via
register_service().

All wiring (register_handler / register_service) must complete before
start() is called.
'''
from __future__ import annotations

import asyncio
import logging
import struct
from typing import Awaitable, Callable

from ..utils import protocol

logger = logging.getLogger("server.server")

Handler = Callable[[bytes, asyncio.StreamWriter], Awaitable[None]]


class Server:
    '''
    asyncio TCP server on 0.0.0.0:6969.  Owns the active-connections map
    and the message-type handler registry.  Services build framed packets
    (via protocol.frame) and call broadcast()/send_to() to deliver them.
    '''

    HOST = "0.0.0.0"
    PORT = 6969

    def __init__(self) -> None:
        # Each writer maps to the set of in-flight handler tasks spawned by
        # incoming commands from that client.  Tasks are tracked so they can
        # be cancelled if the client disconnects mid-handler.
        self.__active_connections: dict[asyncio.StreamWriter, set[asyncio.Task]] = {}
        self.__handlers: dict[int, Handler] = {}
        self.__services: list = []  # duck-typed: any object with async stream_everything(client)
        self.__server: asyncio.Server | None = None

    # ── Wiring ────────────────────────────────────────────────────────

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

    # ── Outgoing ──────────────────────────────────────────────────────

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
        # CLAUDE.md invariant: snapshot the keys before iterating, since
        # __safe_write may pop entries during disconnect handling.
        clients = list(self.__active_connections.keys())
        if not clients:
            return
        await asyncio.gather(
            *(self.__safe_write(writer, packet) for writer in clients),
            return_exceptions=True,
        )

    async def send_to(self, writer: asyncio.StreamWriter, packet: bytes) -> None:
        '''
        Sends a pre-framed packet to a single client.  Used by services'
        stream_everything(client) implementations to deliver a snapshot
        only to the new connection.
        Arguments:
            writer (StreamWriter): The connection to write to.
            packet (bytes): One or more length-prefixed messages.
        '''
        await self.__safe_write(writer, packet)

    # ── Lifecycle ─────────────────────────────────────────────────────

    async def start(self) -> None:
        '''
        Binds the TCP server and serves forever.  All handlers and services
        must already be registered before this is awaited.
        '''
        logger.info("TCP server starting on %s:%d", self.HOST, self.PORT)
        self.__server = await asyncio.start_server(
            self.__handle_connection, host=self.HOST, port=self.PORT
        )
        async with self.__server:
            await self.__server.serve_forever()

    # ── Internals ─────────────────────────────────────────────────────

    async def __handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = writer.get_extra_info("peername")
        self.__active_connections[writer] = set()
        logger.info("Client connected: %s", peer)

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
            logger.info("Client disconnected: %s", peer)

    async def __read_loop(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        # No inactivity timeout: clients are display-only and may idle
        # indefinitely.  Disconnects surface as IncompleteReadError /
        # ConnectionError from readexactly().  See CLAUDE.md
        # "TCP Server Invariants".
        while True:
            try:
                msg_type, payload = await self.__recv_message(reader)
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

    async def __recv_message(
        self, reader: asyncio.StreamReader
    ) -> tuple[int, bytes]:
        msg_len = struct.unpack("!I", await reader.readexactly(4))[0]
        # CLAUDE.md invariant: enforce MAX_MSG_SIZE to prevent OOM from
        # malformed or hostile length prefixes.
        if msg_len == 0 or msg_len > protocol.MAX_MSG_SIZE:
            raise ValueError(f"Invalid message size: {msg_len}")

        body = await reader.readexactly(msg_len)
        msg_type = body[0]
        payload = body[1:] if msg_len > 1 else b""
        return msg_type, payload

    async def __safe_write(
        self, writer: asyncio.StreamWriter, packet: bytes
    ) -> None:
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
        pending = self.__active_connections.pop(writer, None)
        if pending:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        try:
            writer.close()
            await writer.wait_closed()
        except (ConnectionError, OSError):
            pass
