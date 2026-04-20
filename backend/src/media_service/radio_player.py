import asyncio
import logging
import struct

import aiohttp
import vlc

from ..utils.config_parser import ConfigUtils
from .base_media_player import BaseMediaPlayer
from .media_manager import MediaManager

logger = logging.getLogger("media_service.radio_player")


class RadioPlayer(BaseMediaPlayer):
    def __init__(self, media_manager: MediaManager):
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

        config = ConfigUtils.get_config()
        self.__media_ids = config["radioMediaIds"]
        self.__channels = list(config["radioMediaIds"].keys())
        self.__channel = config["defaultRadioStation"]
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
        except Exception:
            logger.debug("Failed to reload radio stream")

    async def __fetch_radio_station(self) -> None:
        '''
        Fetches the stream URL and image URL for the current channel
        from the Nelonen Media API.
        '''
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://mcc.nm-ovp.nelonenmedia.fi/v2/media/"
                    + str(self.__media_ids[self.__channel]),
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    response.raise_for_status()
                    data = await response.json()

            self.__stream_url = data["clip"]["playback"]["media"]["streamUrls"][
                "audioHls"
            ]["url"]
            self.__image_url = data["clip"]["playback"]["media"]["images"]["square"][
                "576x576"
            ]
        except Exception:
            logger.debug("Failed to fetch radio station data for %s", self.__channel)

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
        except Exception:
            logger.debug("Failed to download radio channel image")
            return None

    async def __stream_channel_image(self) -> None:
        image_data = await self.__download_image()
        if image_data is None:
            return
        msg_type = struct.pack("!B", MediaManager.MEDIA_STREAM_IMAGE)
        packet = (
            struct.pack("!I", len(msg_type) + len(image_data)) + msg_type + image_data
        )
        await self._media_manager.stream_data(data=packet, player=self)

    async def __stream_channel_name(self) -> None:
        msg_type = struct.pack("!B", MediaManager.MEDIA_STREAM_NAME)
        payload = self.__channel.encode("utf-8")
        payload_length = struct.pack("!H", len(payload))
        packet = (
            struct.pack("!I", len(msg_type) + len(payload_length) + len(payload))
            + msg_type
            + payload_length
            + payload
        )
        await self._media_manager.stream_data(data=packet, player=self)

    async def __stream_play_state(self) -> None:
        msg_type = struct.pack("!B", MediaManager.MEDIA_IS_PLAYING)
        payload = struct.pack("!B", self.__vlc_player.is_playing())
        packet = struct.pack("!I", len(msg_type) + len(payload)) + msg_type + payload
        await self._media_manager.stream_data(data=packet, player=self)

    async def stream_everything(self) -> None:
        await self.__stream_channel_name()
        await self.__stream_channel_image()
        await self.__stream_play_state()
