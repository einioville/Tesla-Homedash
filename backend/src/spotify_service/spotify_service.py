from spotipy import Spotify
from spotipy.oauth2 import SpotifyOAuth
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import asyncio
from ..utils.config_parser import ConfigUtils
import aiohttp
import struct
from ..media_player.base_media_player import BaseMediaPlayer
from ..media_player.media_player import MediaPlayer


class SpotifyService(BaseMediaPlayer):
    def __init__(self, media_player: MediaPlayer):
        super().__init__(media_player=media_player)
        self.__scopes = """
            user-read-playback-state,
            user-modify-playback-state,
            user-read-currently-playing,
            app-remote-control,
            streaming,
            playlist-read-private,
            playlist-read-collaborative,
            playlist-modify-private,
            playlist-modify-public,
            user-read-playback-position,
            user-top-read,
            user-read-recently-played,
            user-library-modify,
            user-library-read
        """

        self.__auth_manager = SpotifyOAuth(
            client_id=ConfigUtils.get_env("SPOTIFY_CLIENT_ID"),
            client_secret=ConfigUtils.get_env("SPOTIFY_CLIENT_SECRET"),
            redirect_uri=ConfigUtils.get_config()["spotifyRedirectUri"],
            cache_path=ConfigUtils.get_config()["spotifyCachePath"],
            scope=self.__scopes,
        )

        self.__spotify = Spotify(auth_manager=self.__auth_manager)

        self.__playback_is_none = True
        self.__is_playing = False
        self.__current_device_id = None
        self.__current_device_name = None
        self.__target_device_id = ConfigUtils.get_config()["spotifyDeviceId"]
        self.__controls_enabled = True
        self.__is_active = False
        self.__context = None
        self.__resuming = False
        self.__media_player_claimed = False
        self.__song_details = {"id": "snoopdogg"}

        self.__async_loop = asyncio.get_running_loop()

        self.__scheduler = AsyncIOScheduler()
        self.__scheduler.start()
        self.__scheduler.add_job(
            func=self.__update_state,
            trigger="interval",
            seconds=10,
            id="spotify_updater",
        )

    async def __overload_prevention(self) -> None:
        self.__controls_enabled = False
        await asyncio.sleep(1)
        self.__controls_enabled = True

    async def __update_playback(self) -> bool:
        playback = None
        try:
            playback = await self.__async_loop.run_in_executor(
                None, lambda: self.__spotify.current_playback(market="FI")
            )
        except Exception:
            return

        if playback is None:
            self.__current_device_id = "None"
            return None

        self.__current_device_id = playback["device"]["id"]
        self.__current_device_name = playback["device"]["name"]
        self.__is_active = playback["device"]["is_active"]
        self.__is_playing = playback["is_playing"]
        self.__context = playback["context"]

        song_changed = False

        if playback["item"]["id"] != self.__song_details["id"]:
            self.__song_details = playback["item"]
            song_changed = True

        self.__song_details["progress_ms"] = playback["progress_ms"]

        return song_changed

    async def pause_play(self) -> None:
        if self.__is_playing:
            await self.pause()
        else:
            await self.play()

    async def pause(self) -> None:
        if not self.__controls_enabled:
            return

        if self.__current_device_id != self.__target_device_id:
            return

        self.__controls_enabled = False

        try:
            await self.__async_loop.run_in_executor(
                None,
                lambda: self.__spotify.pause_playback(
                    device_id=self.__current_device_id
                ),
            )
        except Exception:
            await self.__overload_prevention()
            return
        finally:
            await self.__update_state()
            await self.__overload_prevention()

    async def play(self) -> None:
        if not self.__controls_enabled:
            return

        await self.__update_playback()

        if self.__current_device_id != self.__target_device_id:
            return

        if self.__context["type"] != "playlist":
            return

        if not self.__is_active:
            return

        if self.__song_details is not None:
            self.__controls_enabled = False

            try:
                await self.__async_loop.run_in_executor(
                    None,
                    lambda: self.__spotify.start_playback(
                        device_id=self.__current_device_id,
                        context_uri=self.__context["uri"],
                        offset={"uri": self.__song_details["uri"]},
                        position_ms=self.__song_details["progress_ms"],
                    ),
                )
            except Exception:
                await self.__overload_prevention()
                return
            finally:
                await self.__update_state()
                await self.__overload_prevention()

    async def skip_forward(self) -> None:
        if not self.__controls_enabled:
            return

        if self.__current_device_id != self.__target_device_id:
            return

        if not self.__is_playing:
            return

        self.__controls_enabled = False

        try:
            await self.__async_loop.run_in_executor(
                None,
                lambda: self.__spotify.next_track(device_id=self.__current_device_id),
            )
        except Exception:
            await self.__overload_prevention()
            return
        finally:
            await self.__update_state()

    async def skip_backward(self) -> None:
        if not self.__controls_enabled:
            return

        if self.__current_device_name != self.__target_device_id:
            return

        if not self.__is_playing:
            return

        self.__controls_enabled = False

        if self.__song_details["progress_ms"] > 5000:
            try:
                await self.__async_loop.run_in_executor(
                    None,
                    lambda: self.__spotify.seek_track(
                        position_ms=0, device_id=self.__current_device_id
                    ),
                )
            except Exception:
                await self.__overload_prevention()
                return
            finally:
                await self.__update_state()
                await self.__overload_prevention()

        else:
            try:
                await self.__async_loop.run_in_executor(
                    None,
                    lambda: self.__spotify.previous_track(
                        device_id=self.__current_device_id
                    ),
                )
            except Exception:
                await self.__overload_prevention()
                return
            finally:
                await self.__update_state()
                await self.__overload_prevention()

    async def set_progress(self, progress_ms: int) -> None:
        if not self.__controls_enabled:
            return

        if self.__current_device_id != self.__target_device_id:
            return

        if not self.__is_playing:
            return

        self.__controls_enabled = False

        try:
            await self.__async_loop.run_in_executor(
                None,
                lambda: self.__spotify.seek_track(
                    position_ms=progress_ms, device_id=self.__current_device_id
                ),
            )
        except Exception:
            await self.__overload_prevention()
            return
        finally:
            await self.__update_state()
            await self.__overload_prevention()

    async def __update_state(self) -> None:
        song_changed = await self.__update_playback()

        if song_changed is None:
            self.__playback_is_none = True
            if self.__media_player_claimed:
                await self._media_player.load_default_media_player()
                self.__media_player_claimed = False
            self.__scheduler.reschedule_job(
                job_id="spotify_updater", trigger="interval", seconds=10
            )
            return
        else:
            self.__playback_is_none = False

        if (
            self.__current_device_id == self.__target_device_id
            and not self.__media_player_claimed
        ):
            self.__media_player_claimed = True
            await self._media_player.claim_media_control(player=self)
            self.__scheduler.reschedule_job(
                job_id="spotify_updater", trigger="interval", seconds=2
            )

        elif (
            self.__current_device_id != self.__target_device_id
            and self.__media_player_claimed
        ):
            if self.__media_player_claimed:
                await self._media_player.load_default_media_player()
                self.__media_player_claimed = False
            self.__scheduler.reschedule_job(
                job_id="spotify_updater", trigger="interval", seconds=10
            )

        if self.__media_player_claimed:
            if song_changed:
                await self.__stream_name()
                await self.__stream_artists()
                await self.__stream_duration()
                await self.__stream_image()

            await self.__stream_progress()
            await self.__stream_play_state()

    async def __stream_progress(self) -> None:
        msg_type = struct.pack("!B", MediaPlayer.MEDIA_STREAM_PROGRESS)
        payload = struct.pack("!I", self.__song_details["progress_ms"])
        packet = struct.pack("!I", len(msg_type) + len(payload)) + msg_type + payload
        await self._media_player.stream_data(data=packet, player=self)

    async def __stream_duration(self) -> None:
        msg_type = struct.pack("!B", MediaPlayer.MEDIA_STREAM_DURATION)
        payload = struct.pack("!I", self.__song_details["duration_ms"])
        packet = struct.pack("!I", len(msg_type) + len(payload)) + msg_type + payload
        await self._media_player.stream_data(data=packet, player=self)

    async def __stream_name(self) -> None:
        msg_type = struct.pack("!B", MediaPlayer.MEDIA_STREAM_NAME)
        payload = self.__song_details["name"].encode("utf-8")
        payload_length = struct.pack("!H", len(payload))
        packet = (
            struct.pack("!I", len(msg_type) + len(payload_length) + len(payload))
            + msg_type
            + payload_length
            + payload
        )
        await self._media_player.stream_data(data=packet, player=self)

    async def __stream_artists(self) -> None:
        msg_type = struct.pack("!B", MediaPlayer.MEDIA_STREAM_ARTISTS)
        payload = ", ".join(
            [artist["name"] for artist in self.__song_details["artists"]]
        ).encode("utf-8")
        payload_length = struct.pack("!H", len(payload))
        packet = (
            struct.pack("!I", len(msg_type) + len(payload_length) + len(payload))
            + msg_type
            + payload_length
            + payload
        )
        await self._media_player.stream_data(data=packet, player=self)

    async def __stream_image(self) -> None:
        msg_type = struct.pack("!B", MediaPlayer.MEDIA_STREAM_IMAGE)
        payload = await self.__download_image()
        packet = struct.pack("!I", len(msg_type) + len(payload)) + msg_type + payload
        await self._media_player.stream_data(data=packet, player=self)

    async def __download_image(self) -> bytes:
        url = self.__song_details["album"]["images"][0]["url"]

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                response.raise_for_status()
                return await response.read()

    async def __stream_play_state(self) -> None:
        msg_type = struct.pack("!B", MediaPlayer.MEDIA_IS_PLAYING)
        payload = struct.pack("!B", self.__is_playing)
        packet = struct.pack("!I", len(msg_type) + len(payload)) + msg_type + payload
        await self._media_player.stream_data(data=packet, player=self)

    async def stream_everything(self) -> None:
        if self.__playback_is_none:
            return
        await self.__stream_play_state()
        await self.__stream_name()
        await self.__stream_artists()
        await self.__stream_duration()
        await self.__stream_progress()
        await self.__stream_image()
