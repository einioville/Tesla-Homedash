from __future__ import annotations

import asyncio
import struct
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .radio_player import RadioPlayer
    from .spotify_player import SpotifyPlayer

import logging

from ..tesla_service.tcp_server import TeslaDataServer
from ..utils import protocol
from .base_media_player import BaseMediaPlayer

logger = logging.getLogger("media_service.media_manager")


class MediaManager:
    def __init__(self, server: TeslaDataServer):
        from .radio_player import RadioPlayer
        from .spotify_player import SpotifyPlayer
        self.__radio_player: RadioPlayer = RadioPlayer(media_manager=self)
        self.__spotify_player: SpotifyPlayer = SpotifyPlayer(media_manager=self)
        self.__active_player: BaseMediaPlayer | None = None
        self.__server = server

    async def play(self) -> None:
        logger.debug("Media command: play")
        if self.__active_player:
            await self.__active_player.play()

    async def pause(self) -> None:
        logger.debug("Media command: pause")
        if self.__active_player:
            await self.__active_player.pause()

    async def pause_play(self) -> None:
        logger.debug("Media command: pause_play")
        if self.__active_player:
            await self.__active_player.pause_play()

    async def skip_forward(self) -> None:
        logger.debug("Media command: skip_forward")
        if self.__active_player:
            await self.__active_player.skip_forward()

    async def skip_backward(self) -> None:
        logger.debug("Media command: skip_backward")
        if self.__active_player:
            await self.__active_player.skip_backward()

    async def stream_data(self, data: bytes, player: BaseMediaPlayer) -> None:
        if player == self.__active_player:
            await self.__server.send_data(data=data)

    async def set_progress(self, progress_ms: int) -> None:
        logger.debug("Media command: set_progress")
        if self.__active_player:
            await self.__active_player.set_progress(progress_ms=progress_ms)

    async def claim_media_control(self, player: BaseMediaPlayer) -> None:
        '''
        Stops the current active player and hands control to the claiming player.
        Playback is started automatically on the new player.
        Arguments:
            player (BaseMediaPlayer): The player claiming control
        '''
        if self.__active_player and self.__active_player != player:
            await self.__active_player.stop()
        self.__active_player = player
        logger.info("Media control claimed by %s", player.__class__.__name__)
        await self.__active_player.play()
        await self.__stream_media_type()
        await self.__active_player.stream_everything()

    async def release_playback(self) -> None:
        '''
        Releases the current player and loads the default media player
        without starting playback.
        '''
        logger.info("Playback released, loading default radio player")
        await self.load_default_media_player()

    async def load_default_media_player(self) -> None:
        '''
        Loads the default radio player without starting playback.
        The radio is prepared and ready, call play() to start.
        '''
        if self.__active_player:
            await self.__active_player.stop()
        self.__active_player = self.__radio_player
        await self.__radio_player.load_player()
        await self.__stream_media_type()
        await self.__active_player.stream_everything()
        logger.info("Default radio player loaded")

    async def __stream_media_type(self) -> None:
        media_type = protocol.MEDIA_TYPE_RADIO
        if self.__active_player == self.__radio_player:
            media_type = protocol.MEDIA_TYPE_RADIO
        elif self.__active_player == self.__spotify_player:
            media_type = protocol.MEDIA_TYPE_SPOTIFY

        msg_type = struct.pack("!B", protocol.MEDIA_STREAM_TYPE)
        payload = struct.pack("!B", media_type)
        packet = struct.pack("!I", len(msg_type) + len(payload)) + msg_type + payload
        await self.__server.send_data(data=packet)

    async def stream_everything(self) -> None:
        if self.__active_player:
            await self.__stream_media_type()
            await self.__active_player.stream_everything()

    async def run(self) -> None:
        '''
        Starts the media manager: launches Spotify polling and loads the
        default media player ready for playback.
        '''
        logger.info("MediaManager starting")
        await self.__spotify_player.run()
        await self.load_default_media_player()

    def get_run_task(self) -> asyncio.Task:
        '''
        Returns an asyncio Task that starts the media manager.
        '''
        return asyncio.create_task(self.run())
