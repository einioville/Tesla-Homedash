import asyncio
import logging
import struct

import aiohttp
import vlc

from ..utils import protocol
from ..utils.config_parser import Config
from .base_media_player import BaseMediaPlayer
from .media_manager import MediaManager

logger = logging.getLogger("media_service.radio_player")


class RadioPlayer(BaseMediaPlayer):
    def __init__(self, media_manager: MediaManager, config: Config):
        super().__init__(media_manager=media_manager)

        self.__vlc = vlc.Instance(
            "--no-video",
            "--quiet",
            "--network-caching=5000",
        )
        self.__vlc_player = self.__vlc.media_player_new()

        self.__event_manager = self.__vlc_player.event_manager()
        self.__event_manager.event_attach(
            vlc.EventType.MediaPlayerPaused, self.__on_vlc_event
        )
        self.__event_manager.event_attach(
            vlc.EventType.MediaPlayerPlaying, self.__on_vlc_event
        )
        self.__event_manager.event_attach(
            vlc.EventType.MediaPlayerMediaChanged, self.__on_vlc_event
        )
        self.__event_manager.event_attach(
            vlc.EventType.MediaPlayerEncounteredError, self.__on_vlc_event
        )
        self.__event_manager.event_attach(
            vlc.EventType.MediaPlayerEndReached, self.__on_vlc_event
        )

        self.__media_ids = config.radio_media_ids
        self.__channels = list(self.__media_ids.keys())
        self.__channel = config.default_radio_station
        self.__channel_index = self.__channels.index(self.__channel)

        self.__stream_url: str | None = None
        self.__image_url: str | None = None

        # Flag to prevent restart loops when intentionally stopped
        self.__intentional_stop = False

        self.__async_loop = asyncio.get_running_loop()

    def __on_vlc_event(self, event) -> None:
        '''
        VLC event callback, runs on a VLC thread so it schedules
        async work back onto the main event loop.
        Arguments:
            event (vlc.Event): The VLC event that triggered the callback
        '''
        match event.type:
            case vlc.EventType.MediaPlayerPaused:
                self.__async_loop.call_soon_threadsafe(
                    asyncio.create_task, self.__stream_play_state()
                )

            case vlc.EventType.MediaPlayerPlaying:
                self.__async_loop.call_soon_threadsafe(
                    asyncio.create_task, self.__stream_play_state()
                )

            case vlc.EventType.MediaPlayerMediaChanged:
                self.__async_loop.call_soon_threadsafe(
                    asyncio.create_task, self.__stream_channel_name()
                )
                self.__async_loop.call_soon_threadsafe(
                    asyncio.create_task, self.__stream_channel_image()
                )

            case vlc.EventType.MediaPlayerEncounteredError:
                logger.warning("VLC playback error, attempting restart")
                if not self.__intentional_stop:
                    self.__async_loop.call_soon_threadsafe(
                        asyncio.create_task, self.__reload_and_play()
                    )

            case vlc.EventType.MediaPlayerEndReached:
                logger.info("VLC stream ended, attempting restart")
                if not self.__intentional_stop:
                    self.__async_loop.call_soon_threadsafe(
                        asyncio.create_task, self.__reload_and_play()
                    )

    async def __reload_and_play(self) -> None:
        try:
            await self.load_player()
            self.__vlc_player.play()
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
            logger.debug("Failed to reload radio stream: %s: %s", type(e).__name__, e)

    async def __fetch_radio_station(self) -> None:
        '''
        Fetches the stream URL and image URL for the current channel
        from the Nelonen Media API.
        '''
        self.__stream_url = None
        self.__image_url = None
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://mcc.nm-ovp.nelonenmedia.fi/v2/media/"
                    + str(self.__media_ids[self.__channel]),
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    response.raise_for_status()
                    data = await response.json()

            media = (
                data.get("clip", {})
                    .get("playback", {})
                    .get("media", {})
            )
            self.__stream_url = media.get("streamUrls", {}).get("audioHls", {}).get("url")
            self.__image_url = media.get("images", {}).get("square", {}).get("576x576")
            if not self.__stream_url:
                logger.warning("Nelonen API response missing streamUrls.audioHls.url for %s", self.__channel)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
            # ValueError covers JSON decode errors from response.json()
            logger.warning("Failed to fetch radio station data for %s: %s: %s", self.__channel, type(e).__name__, e)

    async def load_player(self) -> None:
        '''
        Fetches the current channel stream and loads it into VLC
        without starting playback.
        '''
        logger.info("Loading radio player for channel: %s", self.__channel)
        self.__intentional_stop = True
        self.__vlc_player.stop()
        self.__vlc_player.set_media(None)
        self.__intentional_stop = False

        await self.__fetch_radio_station()

        if self.__stream_url:
            media = self.__vlc.media_new(self.__stream_url)
            self.__vlc_player.set_media(media)

    async def stop(self) -> None:
        self.__intentional_stop = True
        self.__vlc_player.stop()
        self.__vlc_player.set_media(None)
        self.__intentional_stop = False
        logger.debug("Radio player stopped")

    async def pause(self) -> None:
        self.__vlc_player.pause()

    async def play(self) -> None:
        # If no media is loaded, do a full load first
        if not self.__vlc_player.get_media():
            await self.load_player()
        self.__vlc_player.play()
        logger.debug("Radio playback started for channel: %s", self.__channel)

    async def pause_play(self) -> None:
        if self.__vlc_player.is_playing():
            await self.pause()
        else:
            await self.play()

    async def skip_forward(self) -> None:
        self.__channel_index += 1
        if self.__channel_index == len(self.__channels):
            self.__channel_index = 0
        self.__channel = self.__channels[self.__channel_index]
        logger.info("Skipped to next channel: %s", self.__channel)
        await self.load_player()
        self.__vlc_player.play()

    async def skip_backward(self) -> None:
        self.__channel_index -= 1
        if self.__channel_index == -1:
            self.__channel_index = len(self.__channels) - 1
        self.__channel = self.__channels[self.__channel_index]
        logger.info("Skipped to previous channel: %s", self.__channel)
        await self.load_player()
        self.__vlc_player.play()

    async def __download_image(self) -> bytes | None:
        if not self.__image_url:
            return None
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.__image_url) as response:
                    if response.status != 200:
                        return None
                    return await response.read()
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.debug("Failed to download radio channel image: %s: %s", type(e).__name__, e)
            return None

    async def __stream_channel_image(self, client=None) -> None:
        image_data = await self.__download_image()
        if image_data is None:
            return
        packet = protocol.frame(protocol.MEDIA_STREAM_IMAGE, image_data)
        await self._media_manager.stream_data(data=packet, player=self, client=client)

    async def __stream_channel_name(self, client=None) -> None:
        payload = self.__channel.encode("utf-8")
        body = struct.pack("!H", len(payload)) + payload
        packet = protocol.frame(protocol.MEDIA_STREAM_NAME, body)
        await self._media_manager.stream_data(data=packet, player=self, client=client)

    async def __stream_play_state(self, client=None) -> None:
        payload = struct.pack("!B", self.__vlc_player.is_playing())
        packet = protocol.frame(protocol.MEDIA_IS_PLAYING, payload)
        await self._media_manager.stream_data(data=packet, player=self, client=client)

    async def stream_everything(self, client=None) -> None:
        await self.__stream_channel_name(client=client)
        await self.__stream_channel_image(client=client)
        await self.__stream_play_state(client=client)
