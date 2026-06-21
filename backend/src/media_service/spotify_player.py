import asyncio
import logging
import struct

import aiohttp
import requests
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from spotipy import Spotify, SpotifyException
from spotipy.oauth2 import SpotifyOAuth

from ..utils import protocol
from ..utils.config_parser import Config, get_env
from .base_media_player import BaseMediaPlayer
from .media_manager import MediaManager

logger = logging.getLogger("media_service.spotify_player")

_FAILED = object()
_IMAGE_FETCH_TIMEOUT = aiohttp.ClientTimeout(total=10)


class SpotifyPlayer(BaseMediaPlayer):
    _POLL_IDLE = 10
    _POLL_ACTIVE = 2

    def __init__(self, media_manager: MediaManager, config: Config):
        super().__init__(media_manager=media_manager)

        self._auth_manager = SpotifyOAuth(
            client_id=get_env("SPOTIFY_CLIENT_ID"),
            client_secret=get_env("SPOTIFY_CLIENT_SECRET"),
            redirect_uri=config.spotify_redirect_uri,
            cache_path=config.spotify_cache_path,
            scope=(
                "user-read-playback-state,"
                "user-modify-playback-state,"
                "user-read-currently-playing"
            ),
        )

        self._spotify = Spotify(auth_manager=self._auth_manager)
        self._target_device_id: str = config.spotify_device_id
        self._market: str = config.spotify_market
        self._loop = asyncio.get_running_loop()

        self._current_device_id: str | None = None
        self._is_playing: bool = False
        self._song_id: str | None = None
        self._song_details: dict | None = None
        self._claimed: bool = False
        self._poll_interval: int = self._POLL_IDLE

        # Serialises state updates. _update_state runs both on the poll timer
        # and inline after every control command, so without this two runs
        # could interleave and double-fire claim/release.
        self._state_lock = asyncio.Lock()

        self._scheduler = AsyncIOScheduler(timezone=config.zone_info)

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
        logger.info("SpotifyPlayer polling started, interval=%ds", self._POLL_IDLE)

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
        except (SpotifyException, requests.exceptions.RequestException, OSError) as e:
            # SpotifyException → API errors (4xx/5xx, auth), RequestException →
            # connection/timeout from the underlying requests client, OSError →
            # low-level socket errors that sometimes escape requests.
            logger.error("Spotify API call failed: %s — %s: %s", func.__name__, type(e).__name__, e)
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
        if progress_ms < 0:
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
        '''
        Guarded entry point for a state refresh.  Skips if a refresh is already
        running: this method is invoked both by the poll timer and inline after
        control commands, and claim_media_control re-enters it via play() — so a
        plain lock would deadlock and an unguarded body would race.  The
        in-progress run (or the next tick) reflects the latest state.
        '''
        if self._state_lock.locked():
            return
        async with self._state_lock:
            await self._update_state_impl()

    async def _update_state_impl(self) -> None:
        playback = await self._call_spotify(
            self._spotify.current_playback, market=self._market, additional_types="episode"
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
        new_device_id = device["id"]
        if new_device_id != self._current_device_id:
            logger.debug("Spotify playback device changed: %s", new_device_id)
        self._current_device_id = new_device_id
        self._is_playing = playback["is_playing"]

        item = playback["item"]
        song_changed = item.get("id") != self._song_id
        if song_changed:
            self._song_id = item.get("id")

        self._song_details = item
        self._song_details["progress_ms"] = playback.get("progress_ms", 0)

        on_target = self._current_device_id == self._target_device_id

        if on_target and not self._claimed:
            logger.info("Spotify device on target, claiming media control: %s", self._current_device_id)
            self._claimed = True
            await self._media_manager.claim_media_control(player=self)
            self._set_poll_interval(self._POLL_ACTIVE)
        elif not on_target and self._claimed:
            logger.info("Spotify device left target, releasing playback: %s", self._current_device_id)
            await self._media_manager.release_playback()
            self._claimed = False
            self._set_poll_interval(self._POLL_IDLE)

        if self._claimed:
            if song_changed:
                logger.info("Track changed: %s", item.get('name'))
                await self._stream_name()
                await self._stream_artists()
                await self._stream_duration()
                await self._stream_image()
            await self._stream_progress()
            await self._stream_play_state()

    def _set_poll_interval(self, seconds: int) -> None:
        if seconds == self._poll_interval:
            return
        self._poll_interval = seconds
        self._scheduler.reschedule_job(
            job_id="spotify_updater", trigger="interval", seconds=seconds
        )
        logger.debug("Spotify poll interval set to %ds", seconds)

    # ── Streaming ─────────────────────────────────────────────────

    async def _stream_progress(self, client=None) -> None:
        payload = struct.pack("!I", self._song_details["progress_ms"])
        packet = protocol.frame(protocol.MEDIA_STREAM_PROGRESS, payload)
        await self._media_manager.stream_data(data=packet, player=self, client=client)

    async def _stream_duration(self, client=None) -> None:
        payload = struct.pack("!I", self._song_details.get("duration_ms", 0))
        packet = protocol.frame(protocol.MEDIA_STREAM_DURATION, payload)
        await self._media_manager.stream_data(data=packet, player=self, client=client)

    async def _stream_name(self, client=None) -> None:
        payload = self._song_details.get("name", "").encode("utf-8")
        body = struct.pack("!H", len(payload)) + payload
        packet = protocol.frame(protocol.MEDIA_STREAM_NAME, body)
        await self._media_manager.stream_data(data=packet, player=self, client=client)

    async def _stream_artists(self, client=None) -> None:
        item_type = self._song_details.get("type", "track")
        if item_type == "episode":
            show = self._song_details.get("show") or {}
            artist_text = show.get("name", "")
        else:
            artists = self._song_details.get("artists") or []
            artist_text = ", ".join(a.get("name", "") for a in artists)

        payload = artist_text.encode("utf-8")
        body = struct.pack("!H", len(payload)) + payload
        packet = protocol.frame(protocol.MEDIA_STREAM_ARTISTS, body)
        await self._media_manager.stream_data(data=packet, player=self, client=client)

    async def _stream_image(self, client=None) -> None:
        image_data = await self._download_image()
        if image_data is None:
            return
        packet = protocol.frame(protocol.MEDIA_STREAM_IMAGE, image_data)
        await self._media_manager.stream_data(data=packet, player=self, client=client)

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

        # Use the highest-resolution image. Spotify orders them widest-first, so
        # images[0] is normally the largest; picking by pixel area is robust to any
        # ordering/size quirks and falls back to the first when sizes are null.
        best = max(
            images,
            key=lambda image: (image.get("width") or 0) * (image.get("height") or 0),
        )
        url = best.get("url") or images[0].get("url")
        if not url:
            return None

        try:
            # Bounded timeout: a slow CDN response would otherwise stall the
            # poll cycle, queueing every subsequent _update_state() behind it.
            async with aiohttp.ClientSession(timeout=_IMAGE_FETCH_TIMEOUT) as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        return None
                    return await response.read()
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.debug("Failed to download album art: %s: %s", type(e).__name__, e)
            return None

    async def _stream_play_state(self, client=None) -> None:
        payload = struct.pack("!B", self._is_playing)
        packet = protocol.frame(protocol.MEDIA_IS_PLAYING, payload)
        await self._media_manager.stream_data(data=packet, player=self, client=client)

    async def stream_everything(self, client=None) -> None:
        if self._song_details is None:
            return
        await self._stream_play_state(client=client)
        await self._stream_name(client=client)
        await self._stream_artists(client=client)
        await self._stream_duration(client=client)
        await self._stream_progress(client=client)
        await self._stream_image(client=client)
