from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .vehicle import Vehicle
    from ..spotify_service.spotify_service import SpotifyService
    from ..media_player.media_player import MediaPlayer

import asyncio
import struct
import json


class TeslaDataServer:
    MSG_JSON = 0x01
    MSG_LIST = 0x02
    MSG_TERMINATE = 0x03
    MSG_STREAM = 0x04

    MEDIA_STREAM_IMAGE = 0x14
    MEDIA_STREAM_NAME = 0x15
    MEDIA_STREAM_PROGRESS = 0x16
    MEDIA_STREAM_DURATION = 0x17
    MEDIA_SKIP = 0x18
    MEDIA_SKIP_BACKWARD = 0x19
    MEDIA_PAUSE_PLAY = 0x1A
    MEDIA_IS_PLAYING = 0x1B
    MEDIA_SET_PROGRESS = 0x1C
    MEDIA_STREAM_ARTISTS = 0x1D

    WEATHER_FORECAST = 0x30

    TESLA_SWITCH_CLIMATE_STATE = 0x60
    TESLA_MINUS_TARGET_TEMP = 0x61
    TESLA_PLUS_TARGET_TEMP = 0x62

    def __init__(self, vehicle: Vehicle = None, media_player: MediaPlayer = None):
        self.__vehicle = vehicle
        self.__media_player = media_player
        self.__active_connections = {}

    async def __recv_message(self, reader: asyncio.StreamReader) -> tuple:
        msg_len = struct.unpack("!I", await reader.readexactly(4))[0]

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
        except (BrokenPipeError, ConnectionRefusedError):
            if writer in self.__active_connections:
                self.__active_connections.pop(writer)

    async def send_data(self, data: bytes) -> None:
        tasks = []
        for client in self.__active_connections.keys():
            task = asyncio.create_task(coro=self.__send_message_stream(client, data))
            tasks.append(task)
        await asyncio.gather(*tasks)

    async def __build_message_stream(self, data: list) -> bytes:
        message_stream = bytes()

        for entry in data:
            msg_type = struct.pack("!B", TeslaDataServer.MSG_STREAM)
            packet_length = struct.pack("!I", len(msg_type) + len(entry))
            message_stream += packet_length + msg_type + entry

        return message_stream

    async def update_clients(self, data: list) -> None:
        message_stream = await self.__build_message_stream(data)

        send_tasks = []
        for client in self.__active_connections.keys():
            send_task = asyncio.create_task(
                coro=self.__send_message_stream(client, message_stream)
            )
            send_tasks.append(send_task)

        await asyncio.gather(*send_tasks)

    async def __build_spotify_message_stream(self, data: dict) -> bytes:
        message_stream = bytes()

        for msg_type, entry in data.items():
            packet_length = struct.pack("!I", len(msg_type) + len(entry))
            message_stream += packet_length + msg_type + entry

        return message_stream

    async def update_spotify(self, data: dict) -> None:
        message_stream = await self.__build_spotify_message_stream(data)

        send_tasks = []
        for client in self.__active_connections.keys():
            send_task = asyncio.create_task(
                coro=self.__send_message_stream(client, message_stream)
            )
            send_tasks.append(send_task)

        await asyncio.gather(*send_tasks)

    async def __build_forecast_stream(self, data: list) -> bytes:
        message_stream = bytes()

        for entry in data:
            message_stream += entry

        msg_type = struct.pack("!B", TeslaDataServer.WEATHER_FORECAST)
        packet_length = struct.pack("!I", len(msg_type) + len(message_stream))

        return packet_length + msg_type + message_stream

    async def update_forecast(self, data: list) -> None:
        message_stream = await self.__build_forecast_stream(data)

        send_tasks = []
        for client in self.__active_connections.keys():
            send_task = asyncio.create_task(
                coro=self.__send_message_stream(client, message_stream)
            )
            send_tasks.append(send_task)

        await asyncio.gather(*send_tasks)

    async def __handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self.__active_connections[writer] = set()
        print(writer.get_extra_info("peername"))

        await self.__media_player.stream_everything()

        while True:
            try:
                msg_type, payload = await self.__recv_message(reader)

                if msg_type == TeslaDataServer.MSG_JSON:
                    await self.__parse_json(payload, writer)
                    continue

                if msg_type == TeslaDataServer.MEDIA_SKIP:
                    await self.__media_player.skip_forward()
                    continue

                if msg_type == TeslaDataServer.MEDIA_SKIP_BACKWARD:
                    await self.__media_player.skip_backward()
                    continue

                if msg_type == TeslaDataServer.MEDIA_PAUSE_PLAY:
                    await self.__media_player.pause_play()
                    continue

                if msg_type == TeslaDataServer.MEDIA_SET_PROGRESS:
                    await self.__media_player.set_progress(
                        struct.unpack("!I", payload[:4])[0]
                    )
                    continue
                
                if msg_type == TeslaDataServer.TESLA_SWITCH_CLIMATE_STATE:
                    await self.__vehicle.switch_climate_state()
                    continue

                if msg_type == TeslaDataServer.TESLA_MINUS_TARGET_TEMP:
                    await self.__vehicle.minus_temp()
                    continue
                
                if msg_type == TeslaDataServer.TESLA_PLUS_TARGET_TEMP:
                    await self.__vehicle.plus_temp()
                    continue

                if msg_type == TeslaDataServer.MSG_TERMINATE:
                    break

            except Exception as e:
                if writer in self.__active_connections:
                    self.__active_connections.pop(writer)
                print(e)
                break

    def set_vehicle(self, vehicle: Vehicle) -> None:
        self.__vehicle = vehicle

    def set_media_player(self, media_player: MediaPlayer) -> None:
        self.__media_player = media_player

    async def start(self) -> None:
        self.__server = await asyncio.start_server(
            self.__handle_connection, host="0.0.0.0", port=6969
        )
        async with self.__server:
            await self.__server.serve_forever()