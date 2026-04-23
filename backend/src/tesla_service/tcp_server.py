from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .vehicle import Vehicle
    from ..media_service.media_manager import MediaManager

import asyncio
import struct
import json
import logging

from ..utils import protocol

logger = logging.getLogger("tesla_service.tcp_server")


class TeslaDataServer:
    def __init__(self, vehicle: Vehicle = None, media_manager: MediaManager = None):
        self.__vehicle = vehicle
        self.__media_manager = media_manager
        self.__active_connections = {}

    async def __recv_message(self, reader: asyncio.StreamReader) -> tuple:
        msg_len = struct.unpack("!I", await reader.readexactly(4))[0]
        if msg_len == 0 or msg_len > protocol.MAX_MSG_SIZE:
            raise ValueError(f"Invalid message size: {msg_len}")

        body = await reader.readexactly(msg_len)
        msg_type = body[0]

        if msg_len == 1:
            return msg_type, []

        payload = body[1:]
        return msg_type, payload

    async def __send_message_stream(
        self, writer: asyncio.StreamWriter, message_stream: bytes
    ) -> None:
        try:
            writer.write(message_stream)
            await writer.drain()
        except (BrokenPipeError, ConnectionRefusedError) as e:
            logger.warning("Failed to send message to client, removing: %s", e)
            if writer in self.__active_connections:
                self.__active_connections.pop(writer)

    async def send_data(self, data: bytes) -> None:
        tasks = []
        for client in list(self.__active_connections.keys()):
            task = asyncio.create_task(coro=self.__send_message_stream(client, data))
            tasks.append(task)
        await asyncio.gather(*tasks)

    async def __build_message_stream(self, data: list) -> bytes:
        message_stream = bytes()

        for entry in data:
            msg_type = struct.pack("!B", protocol.MSG_STREAM)
            packet_length = struct.pack("!I", len(msg_type) + len(entry))
            message_stream += packet_length + msg_type + entry

        return message_stream

    async def update_clients(self, data: list) -> None:
        message_stream = await self.__build_message_stream(data)

        send_tasks = []
        for client in list(self.__active_connections.keys()):
            send_task = asyncio.create_task(
                coro=self.__send_message_stream(client, message_stream)
            )
            send_tasks.append(send_task)

        await asyncio.gather(*send_tasks)

    async def __build_forecast_stream(self, data: list) -> bytes:
        message_stream = bytes()

        for entry in data:
            message_stream += entry

        msg_type = struct.pack("!B", protocol.WEATHER_FORECAST)
        packet_length = struct.pack("!I", len(msg_type) + len(message_stream))

        return packet_length + msg_type + message_stream

    async def update_forecast(self, data: list) -> None:
        message_stream = await self.__build_forecast_stream(data)

        send_tasks = []
        for client in list(self.__active_connections.keys()):
            send_task = asyncio.create_task(
                coro=self.__send_message_stream(client, message_stream)
            )
            send_tasks.append(send_task)

        await asyncio.gather(*send_tasks)

    async def __handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self.__active_connections[writer] = set()
        logger.info("Client connected: %s", writer.get_extra_info("peername"))

        await self.__media_manager.stream_everything()

        while True:
            try:
                # No inactivity timeout: clients are display-only and are not
                # required to send anything. Broken connections are surfaced by
                # readexactly() raising IncompleteReadError / ConnectionError,
                # not by an idle timer. See CLAUDE.md "TCP Server Invariants".
                msg_type, payload = await self.__recv_message(reader)

                if msg_type == protocol.MSG_JSON:
                    logger.warning("MSG_JSON received but not implemented, ignoring")
                    continue

                if msg_type == protocol.MEDIA_SKIP:
                    await self.__media_manager.skip_forward()
                    continue

                if msg_type == protocol.MEDIA_SKIP_BACKWARD:
                    await self.__media_manager.skip_backward()
                    continue

                if msg_type == protocol.MEDIA_PAUSE_PLAY:
                    await self.__media_manager.pause_play()
                    continue

                if msg_type == protocol.MEDIA_SET_PROGRESS:
                    if len(payload) < 4:
                        logger.warning("MEDIA_SET_PROGRESS: payload too short (%d bytes)", len(payload))
                        continue
                    await self.__media_manager.set_progress(
                        struct.unpack("!I", payload[:4])[0]
                    )
                    continue

                if msg_type == protocol.TESLA_SWITCH_CLIMATE_STATE:
                    logger.info("Climate toggle command received")
                    await self.__vehicle.switch_climate_state()
                    continue

                if msg_type == protocol.TESLA_MINUS_TARGET_TEMP:
                    await self.__vehicle.minus_temp()
                    continue

                if msg_type == protocol.TESLA_PLUS_TARGET_TEMP:
                    await self.__vehicle.plus_temp()
                    continue

                if msg_type == protocol.MSG_TERMINATE:
                    logger.info("Client termination message received")
                    break

            except (asyncio.IncompleteReadError, ConnectionError, OSError) as e:
                # Peer disconnected or network-layer failure — expected lifecycle event.
                if writer in self.__active_connections:
                    self.__active_connections.pop(writer)
                logger.info("Client disconnect: %s: %s", type(e).__name__, e)
                break
            except ValueError as e:
                # Protocol-level error from __recv_message (oversized/zero length).
                if writer in self.__active_connections:
                    self.__active_connections.pop(writer)
                logger.warning("Protocol error from client: %s", e)
                break
            except Exception as e:
                # Unexpected application error — log with type and tear down the client.
                if writer in self.__active_connections:
                    self.__active_connections.pop(writer)
                logger.error("Unexpected client handler error: %s: %s", type(e).__name__, e)
                break

        logger.info("Client disconnected")

    def set_vehicle(self, vehicle: Vehicle) -> None:
        self.__vehicle = vehicle

    def set_media_manager(self, media_manager: MediaManager) -> None:
        self.__media_manager = media_manager

    async def start(self) -> None:
        logger.info("TCP data server starting on 0.0.0.0:6969")
        self.__server = await asyncio.start_server(
            self.__handle_connection, host="0.0.0.0", port=6969
        )
        async with self.__server:
            await self.__server.serve_forever()
