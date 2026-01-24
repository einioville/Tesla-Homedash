import vlc
import aiohttp
from ..utils.config_parser import ConfigUtils
from ..media_player.base_media_player import BaseMediaPlayer
import struct
from ..media_player.media_player import MediaPlayer
import asyncio


class RadioPlayer(BaseMediaPlayer):
    def __init__(self, media_player: MediaPlayer):
        super().__init__(media_player=media_player)

        self.__vlc = vlc.Instance(
            "--no-video",
            "--quiet",
            "--network-caching=5000",
        )
        self.__vlc_media_player = self.__vlc.media_player_new()

        self.__event_manager = self.__vlc_media_player.event_manager()
        self.__event_manager.event_attach(
            vlc.EventType.MediaPlayerPaused, self.__run_event_callback
        )
        self.__event_manager.event_attach(
            vlc.EventType.MediaPlayerPlaying, self.__run_event_callback
        )
        self.__event_manager.event_attach(
            vlc.EventType.MediaPlayerMediaChanged, self.__run_event_callback
        )
        self.__event_manager.event_attach(
            vlc.EventType.MediaPlayerMediaChanged, self.__run_event_callback
        )
        self.__event_manager.event_attach(
            vlc.EventType.MediaPlayerEncounteredError, self.__run_event_callback
        )
        self.__event_manager.event_attach(
            vlc.EventType.MediaPlayerEndReached, self.__run_event_callback
        )

        config = ConfigUtils.get_config()
        self.__media_ids = config["radioMediaIds"]
        self.__channels = list(config["radioMediaIds"].keys())
        self.__channel = config["defaultRadioStation"]
        self.__channel_index = self.__channels.index(self.__channel)

        self.__stream_url = None
        self.__image_url = None

        self.__async_loop = asyncio.get_running_loop()

    def __run_event_callback(self, event) -> None:
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
                self.__async_loop.call_soon_threadsafe(
                    asyncio.create_task, self.reload_and_play()
                )

            case vlc.EventType.MediaPlayerEndReached:
                self.__async_loop.call_soon_threadsafe(
                    asyncio.create_task, self.reload_and_play()
                )

    async def reload_and_play(self) -> None:
        await self.load_player()
        await self.play()

    async def __load_radio_station(self) -> None:
        data = None

        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://mcc.nm-ovp.nelonenmedia.fi/v2/media/"
                + str(self.__media_ids[self.__channel]),
                timeout=10,
            ) as response:
                response.raise_for_status()
                data = await response.json()

        self.__stream_url = data["clip"]["playback"]["media"]["streamUrls"]["audioHls"][
            "url"
        ]
        self.__image_url = data["clip"]["playback"]["media"]["images"]["square"][
            "576x576"
        ]

    async def load_player(self) -> None:
        await self.stop()

        await self.__load_radio_station()

        media = self.__vlc.media_new(self.__stream_url)
        self.__vlc_media_player.set_media(media)

    async def stop(self) -> None:
        self.__vlc_media_player.stop()
        self.__vlc_media_player.set_media(None)

    async def pause(self) -> None:
        self.__vlc_media_player.pause()

    async def play(self) -> None:
        if not self.__vlc_media_player.will_play():
            await self.__load_radio_station()
        self.__vlc_media_player.play()

    async def pause_play(self) -> None:
        if self.__vlc_media_player.is_playing():
            await self.pause()
        else:
            await self.play()

    async def skip_forward(self) -> None:
        self.__channel_index += 1
        if self.__channel_index == len(self.__channels):
            self.__channel_index = 0

        self.__channel = self.__channels[self.__channel_index]
        await self.__load_radio_station()
        await self.load_player()
        await self.play()

    async def skip_backward(self) -> None:
        self.__channel_index -= 1
        if self.__channel_index == -1:
            self.__channel_index = len(self.__channels) - 1

        self.__channel = self.__channels[self.__channel_index]
        await self.__load_radio_station()
        await self.load_player()
        await self.play()

    async def __download_image(self) -> bytes:
        async with aiohttp.ClientSession() as session:
            async with session.get(self.__image_url) as response:
                response.raise_for_status()
                return await response.read()

    async def __stream_channel_image(self) -> None:
        msg_type = struct.pack("!B", MediaPlayer.MEDIA_STREAM_IMAGE)
        payload = await self.__download_image()
        packet = struct.pack("!I", len(msg_type) + len(payload)) + msg_type + payload
        await self._media_player.stream_data(data=packet, player=self)

    async def __stream_channel_name(self) -> None:
        msg_type = struct.pack("!B", MediaPlayer.MEDIA_STREAM_NAME)
        payload = self.__channel.encode("utf-8")
        payload_length = struct.pack("!H", len(payload))
        packet = (
            struct.pack("!I", len(msg_type) + len(payload_length) + len(payload))
            + msg_type
            + payload_length
            + payload
        )
        await self._media_player.stream_data(data=packet, player=self)

    async def __stream_play_state(self) -> None:
        msg_type = struct.pack("!B", MediaPlayer.MEDIA_IS_PLAYING)
        payload = struct.pack("!B", self.__vlc_media_player.is_playing())
        packet = struct.pack("!I", len(msg_type) + len(payload)) + msg_type + payload
        await self._media_player.stream_data(data=packet, player=self)

    async def stream_everything(self) -> None:
        await self.__stream_channel_name()
        await self.__stream_channel_image()
        await self.__stream_play_state()
