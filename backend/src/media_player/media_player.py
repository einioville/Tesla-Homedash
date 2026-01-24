from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..radio_service.radio_player import RadioPlayer
    from ..spotify_service.spotify_service import SpotifyService
from ..tesla_service.tcp_server import TeslaDataServer
from .base_media_player import BaseMediaPlayer
import struct


class MediaPlayer:
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
    MEDIA_STREAM_TYPE = 0x1E

    def __init__(self, server: TeslaDataServer):
        self.__radio_player = None
        self.__spotify_player = None

        self.__server = server

    async def play(self) -> None:
        await self.__active_player.play()

    async def pause(self) -> None:
        await self.__active_player.pause()

    async def pause_play(self) -> None:
        await self.__active_player.pause_play()

    async def skip_forward(self) -> None:
        await self.__active_player.skip_forward()

    async def skip_backward(self) -> None:
        await self.__active_player.skip_backward()

    async def stream_data(self, data: bytes, player: BaseMediaPlayer) -> None:
        if player == self.__active_player:
            await self.__server.send_data(data=data)

    async def set_progress(self, progress_ms: int) -> None:
        if self.__active_player == self.__spotify_player:
            await self.__active_player.set_progress(progress_ms=progress_ms)

    async def claim_media_control(self, player: BaseMediaPlayer) -> None:
        await self.__active_player.stop()
        self.__active_player = player
        await self.__stream_media_type()
        await self.__active_player.stream_everything()

    async def load_default_media_player(self) -> None:
        self.__active_player = self.__radio_player
        await self.__radio_player.load_player()
        await self.__radio_player.play()
        await self.__stream_media_type()
        await self.__active_player.stream_everything()

    async def __stream_media_type(self) -> None:
        media_type = 0x01
        if self.__active_player == self.__radio_player:
            media_type = 0x01
        elif self.__active_player == self.__spotify_player:
            media_type = 0x02

        msg_type = struct.pack("!B", MediaPlayer.MEDIA_STREAM_TYPE)
        payload = struct.pack("!B", media_type)
        packet = struct.pack("!I", len(msg_type) + len(payload)) + msg_type + payload
        await self.__server.send_data(data=packet)

    async def stream_everything(self) -> None:
        await self.__stream_media_type()
        await self.__active_player.stream_everything()

    async def set_spotify_player(self, spotify_player: SpotifyService) -> None:
        self.__spotify_player = spotify_player

    async def set_radio_player(self, radio_player: RadioPlayer) -> None:
        self.__radio_player = radio_player
