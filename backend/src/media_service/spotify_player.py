import asyncio
import logging
import struct

import aiohttp
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from spotipy import Spotify
from spotipy.oauth2 import SpotifyOAuth

from ..utils.config_parser import ConfigUtils
from .base_media_player import BaseMediaPlayer
from .media_manager import MediaManager

logger = logging.getLogger(__name__)

_FAILED = object()


class SpotifyPlayer(BaseMediaPlayer):
    _POLL_IDLE = 10
    _POLL_ACTIVE = 2

    def __init__(self, media_manager: MediaManager):
        super().__init__(media_manager=media_manager)

        config = ConfigUtils.get_config()

        self._auth_manager = SpotifyOAuth(
            client_id=ConfigUtils.get_env("SPOTIFY_CLIENT_ID"),
            client_secret=ConfigUtils.get_env("SPOTIFY_CLIENT_SECRET"),
            redirect_uri=config["spotifyRedirectUri"],
            cache_path=config["spotifyCachePath"],
            scope=(
                "user-read-playback-state,"
                "user-modify-playback-state,"
                "user-read-currently-playing"
            ),
        )

        self._spotify = Spotify(auth_manager=self._auth_manager)
        self._target_device_id: str = config["spotifyDeviceId"]
        self._loop = asyncio.get_running_loop()

        self._current_device_id: str | None = None
        self._is_playing: bool = False
        self._song_id: str | None = None
        self._song_details: dict | None = None
        self._claimed: bool = False

        self._scheduler = AsyncIOScheduler()

    async def run(self) -> None:
        '''
        Starts the APScheduler polling loop for periodic Spotify state updates.
        '''
        self._scheduler.start()
        self._scheduler.add_job(
            func=self._update_state,
            trigger="interval",
            seconds=self._POLL_IDLE,
            id="spotify_updater",
        )

    # ── Spotify API helper ────────────────────────────────────────

    async def _call_spotify(self, func, *args, **kwargs):
        '''
        Runs a spotipy method in an executor.
        Returns _FAILED sentinel on any error, otherwise the API result.
        Arguments:
            func (callable): The spotipy method to call
        '''
        try:
            return await self._loop.run_in_executor(
                None, lambda: func(*args, **kwargs)
            )
        except Exception:
            logger.debug("Spotify API call %s failed", func.__name__)
            return _FAILED

    async def _cooldown(self) -> None:
        await asyncio.sleep(1)

    # ── Controls ──────────────────────────────────────────────────

    async def pause_play(self) -> None:
        if self._is_playing:
            await self.pause()
        else:
            await self.play()

    async def play(self) -> None:
        if not self._claimed:
            return
        result = await self._call_spotify(
            self._spotify.start_playback,
            device_id=self._current_device_id,
        )
        if result is _FAILED:
            await self._cooldown()
            return
        await self._update_state()

    async def pause(self) -> None:
        if not self._claimed:
            return
        result = await self._call_spotify(
            self._spotify.pause_playback,
            device_id=self._current_device_id,
        )
        if result is _FAILED:
            await self._cooldown()
            return
        await self._update_state()

    async def skip_forward(self) -> None:
        if not self._claimed:
            return
        result = await self._call_spotify(
            self._spotify.next_track,
            device_id=self._current_device_id,
        )
        if result is _FAILED:
            await self._cooldown()
            return
        await self._update_state()

    async def skip_backward(self) -> None:
        if not self._claimed:
            return

        progress = 0
        if self._song_details:
            progress = self._song_details.get("progress_ms", 0)

        if progress > 5000:
            result = await self._call_spotify(
                self._spotify.seek_track,
                position_ms=0,
                device_id=self._current_device_id,
            )
        else:
            result = await self._call_spotify(
                self._spotify.previous_track,
                device_id=self._current_device_id,
            )

        if result is _FAILED:
            await self._cooldown()
            return
        await self._update_state()

    async def set_progress(self, progress_ms: int) -> None:
        if not self._claimed:
            return
        result = await self._call_spotify(
            self._spotify.seek_track,
            position_ms=progress_ms,
            device_id=self._current_device_id,
        )
        if result is _FAILED:
            await self._cooldown()
            return
        await self._update_state()

    # ── Polling / state ───────────────────────────────────────────

    async def _update_state(self) -> None:
        playback = await self._call_spotify(
            self._spotify.current_playback, market="FI"
        )

        # API error — skip this cycle
        if playback is _FAILED:
            return

        if playback is None or playback.get("item") is None:
            self._current_device_id = None
            self._is_playing = False
            if self._claimed:
                await self._media_manager.release_playback()
                self._claimed = False
            self._set_poll_interval(self._POLL_IDLE)
            return

        device = playback["device"]
        self._current_device_id = device["id"]
        self._is_playing = playback["is_playing"]

        item = playback["item"]
        song_changed = item.get("id") != self._song_id
        if song_changed:
            self._song_id = item.get("id")

        self._song_details = item
        self._song_details["progress_ms"] = playback.get("progress_ms", 0)

        on_target = self._current_device_id == self._target_device_id

        if on_target and not self._claimed:
            self._claimed = True
            await self._media_manager.claim_media_control(player=self)
            self._set_poll_interval(self._POLL_ACTIVE)
        elif not on_target and self._claimed:
            await self._media_manager.release_playback()
            self._claimed = False
            self._set_poll_interval(self._POLL_IDLE)

        if self._claimed:
            if song_changed:
                await self._stream_name()
                await self._stream_artists()
                await self._stream_duration()
                await self._stream_image()
            await self._stream_progress()
            await self._stream_play_state()

    def _set_poll_interval(self, seconds: int) -> None:
        self._scheduler.reschedule_job(
            job_id="spotify_updater", trigger="interval", seconds=seconds
        )

    # ── Streaming ─────────────────────────────────────────────────

    async def _stream_progress(self) -> None:
        msg_type = struct.pack("!B", MediaManager.MEDIA_STREAM_PROGRESS)
        payload = struct.pack("!I", self._song_details["progress_ms"])
        packet = struct.pack("!I", len(msg_type) + len(payload)) + msg_type + payload
        await self._media_manager.stream_data(data=packet, player=self)

    async def _stream_duration(self) -> None:
        msg_type = struct.pack("!B", MediaManager.MEDIA_STREAM_DURATION)
        payload = struct.pack("!I", self._song_details.get("duration_ms", 0))
        packet = struct.pack("!I", len(msg_type) + len(payload)) + msg_type + payload
        await self._media_manager.stream_data(data=packet, player=self)

    async def _stream_name(self) -> None:
        msg_type = struct.pack("!B", MediaManager.MEDIA_STREAM_NAME)
        payload = self._song_details.get("name", "").encode("utf-8")
        payload_length = struct.pack("!H", len(payload))
        packet = (
            struct.pack("!I", len(msg_type) + len(payload_length) + len(payload))
            + msg_type
            + payload_length
            + payload
        )
        await self._media_manager.stream_data(data=packet, player=self)

    async def _stream_artists(self) -> None:
        msg_type = struct.pack("!B", MediaManager.MEDIA_STREAM_ARTISTS)

        item_type = self._song_details.get("type", "track")
        if item_type == "episode":
            show = self._song_details.get("show") or {}
            artist_text = show.get("name", "")
        else:
            artists = self._song_details.get("artists") or []
            artist_text = ", ".join(a.get("name", "") for a in artists)

        payload = artist_text.encode("utf-8")
        payload_length = struct.pack("!H", len(payload))
        packet = (
            struct.pack("!I", len(msg_type) + len(payload_length) + len(payload))
            + msg_type
            + payload_length
            + payload
        )
        await self._media_manager.stream_data(data=packet, player=self)

    async def _stream_image(self) -> None:
        image_data = await self._download_image()
        if image_data is None:
            return
        msg_type = struct.pack("!B", MediaManager.MEDIA_STREAM_IMAGE)
        packet = (
            struct.pack("!I", len(msg_type) + len(image_data)) + msg_type + image_data
        )
        await self._media_manager.stream_data(data=packet, player=self)

    async def _download_image(self) -> bytes | None:
        item_type = self._song_details.get("type", "track")

        if item_type == "episode":
            images = self._song_details.get("images") or []
            if not images:
                show = self._song_details.get("show") or {}
                images = show.get("images") or []
        else:
            album = self._song_details.get("album") or {}
            images = album.get("images") or []

        if not images:
            return None

        url = images[0].get("url")
        if not url:
            return None

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        return None
                    return await response.read()
        except Exception:
            logger.debug("Failed to download album art")
            return None

    async def _stream_play_state(self) -> None:
        msg_type = struct.pack("!B", MediaManager.MEDIA_IS_PLAYING)
        payload = struct.pack("!B", self._is_playing)
        packet = struct.pack("!I", len(msg_type) + len(payload)) + msg_type + payload
        await self._media_manager.stream_data(data=packet, player=self)

    async def stream_everything(self) -> None:
        if self._song_details is None:
            return
        await self._stream_play_state()
        await self._stream_name()
        await self._stream_artists()
        await self._stream_duration()
        await self._stream_progress()
        await self._stream_image()
