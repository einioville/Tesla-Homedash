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

        # Retained so a station change can be remembered (__remember_channel).
        self.__config = config
        self.__media_ids = config.radio_media_ids
        self.__channels = list(self.__media_ids.keys())
        self.__channel = self.__initial_channel()
        self.__channel_index = self.__channels.index(self.__channel)

        self.__stream_url: str | None = None
        self.__image_url: str | None = None

        # Flag to prevent restart loops when intentionally stopped
        self.__intentional_stop = False

        self.__async_loop = asyncio.get_running_loop()

    def __initial_channel(self) -> str:
        '''
        The station to start on: the one last tuned to, else the
        defaultRadioStation of a config.json written before the station was
        remembered, else the first configured.  A name that is not (or no longer)
        a radioMediaIds key is skipped rather than raising, so renaming a station
        in config.json cannot stop the backend from starting.
        '''
        for candidate in (self.__config.media_config.get("lastRadioStation"),
                          self.__config.get("defaultRadioStation")):
            if candidate in self.__channels:
                return candidate
        return self.__channels[0]

    def __remember_channel(self) -> None:
        '''
        Saves the current station as media.lastRadioStation, so the radio comes
        back on it after a restart.  (After Spotify it already does: the release
        reloads whatever station is current.)

        Written straight through Config, not ConfigService: this is state the radio
        owns, not a setting — it is in no schema, has no hook to run, and is valid
        by construction, being always a radioMediaIds key.  Saved at once rather
        than debounced: each skip already waits on a stream fetch, so writes cannot
        outpace a finger, and a debounce window is a window in which a power cut
        loses the station.  A failed save is logged and the station still changes;
        the value stays in memory and rides along with the next successful save.
        '''
        if self.__config.media_config.get("lastRadioStation") == self.__channel:
            return
        self.__config.set("media.lastRadioStation", self.__channel)
        try:
            self.__config.save()
        except OSError as e:
            logger.warning("Could not save the radio station %s: %s", self.__channel, e)

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
            self.__image_url = self.__pick_cover(
                media.get("images", {}).get("square", {})
            )
            if not self.__stream_url:
                logger.warning("Nelonen API response missing streamUrls.audioHls.url for %s", self.__channel)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
            # ValueError covers JSON decode errors from response.json()
            logger.warning("Failed to fetch radio station data for %s: %s: %s", self.__channel, type(e).__name__, e)

    @staticmethod
    def __pick_cover(square: dict, target: int = 720) -> str | None:
        '''
        Picks the square cover closest to the target width from the Nelonen image
        map (keys like "576x576" -> url). The API offers several square sizes; the
        720x720 one is the sweet spot — large enough for the fullscreen view but
        not needlessly heavy like the bigger variants. Returns the exact target
        when present, else the nearest available size.
        Arguments:
            square (dict): The images.square map (size-string -> URL) from the API.
            target (int): Preferred square width in pixels.
        '''
        best_url = None
        best_diff = None
        for size, url in square.items():
            if not url:
                continue
            try:
                width = int(str(size).split("x", 1)[0])
            except (ValueError, IndexError):
                continue
            diff = abs(width - target)
            if best_diff is None or diff < best_diff:
                best_diff = diff
                best_url = url
        return best_url

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

    def is_playing(self) -> bool:
        '''
        Whether VLC is currently producing audio.

        Needed by the Spotify device scan, which silences the radio while the
        user picks a device and restores it afterwards: resuming must not START
        audio that was not playing to begin with, and only VLC knows which it
        was.  Stays synchronous — it reads a libVLC flag and awaits nothing.
        '''
        return bool(self.__vlc_player.is_playing())

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
        self.__remember_channel()
        await self.load_player()
        self.__vlc_player.play()

    async def skip_backward(self) -> None:
        self.__channel_index -= 1
        if self.__channel_index == -1:
            self.__channel_index = len(self.__channels) - 1
        self.__channel = self.__channels[self.__channel_index]
        logger.info("Skipped to previous channel: %s", self.__channel)
        self.__remember_channel()
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
