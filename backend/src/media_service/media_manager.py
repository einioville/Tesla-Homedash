from __future__ import annotations

import asyncio
import struct
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .radio_player import RadioPlayer
    from .spotify_player import SpotifyPlayer

import logging

from ..server.server import Server
from ..utils import protocol
from ..utils.config_parser import Config
from .base_media_player import BaseMediaPlayer

logger = logging.getLogger("media_service.media_manager")


class MediaManager:
    def __init__(self, server: Server, config: Config):
        from .radio_player import RadioPlayer
        from .spotify_player import SpotifyPlayer
        self.__radio_player: RadioPlayer = RadioPlayer(media_manager=self, config=config)
        self.__spotify_player: SpotifyPlayer = SpotifyPlayer(media_manager=self, config=config)
        self.__active_player: BaseMediaPlayer | None = None
        self.__server = server
        self.__config = config
        # Snapshot of the media block, re-read by apply_config_media().
        self.__autoplay_radio: bool = False
        self.__resume_radio_after_spotify: bool = False
        self.apply_config_media()
        # Whether the radio was audibly playing at the moment Spotify took over.
        # "Resume" means putting back what Spotify interrupted, so a radio that
        # was silent before Spotify is never started by Spotify ending.
        self.__radio_interrupted: bool = False

    def apply_config_radio(self) -> None:
        '''
        Forwards a config change to the radio player (the default station).
        Exposed separately from the Spotify hook so ConfigService can apply just
        the setting that changed rather than poking both players.
        '''
        self.__radio_player.apply_config()

    def apply_config_spotify(self) -> None:
        '''Forwards a config change to the Spotify player (market, target device).'''
        self.__spotify_player.apply_config()

    def apply_config_media(self) -> None:
        '''
        Re-snapshots the media block (radio autoplay at startup, resuming the radio
        after Spotify).  Neither needs anything restarted: autoplay is consulted
        once per process start, and the resume flag at the next release.
        '''
        media = self.__config.media_config
        self.__autoplay_radio = bool(media.get("autoplayRadio"))
        self.__resume_radio_after_spotify = bool(media.get("resumeRadioAfterSpotify"))

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

    async def stream_data(
        self, data: bytes, player: BaseMediaPlayer, client=None
    ) -> None:
        '''
        Routes a framed media packet to the network.  Only the currently
        active player's packets are sent — packets from a non-active player
        (e.g. radio left as a fallback while Spotify is claimed) are dropped.
        Arguments:
            data (bytes): Pre-framed packet (built via protocol.frame).
            player (BaseMediaPlayer): The player that produced the packet.
            client: Optional StreamWriter; when provided, the packet is sent
                only to that client (used by stream_everything for new
                connections).  When None, broadcasts to all clients.
        '''
        if player != self.__active_player:
            return
        if client is None:
            await self.__server.broadcast(data)
        else:
            await self.__server.send_to(client, data)

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
            # Read before stop(): afterwards the radio is silent by definition.
            if (player is self.__spotify_player
                    and self.__active_player is self.__radio_player):
                self.__radio_interrupted = self.__radio_player.is_playing()
            await self.__active_player.stop()
        self.__active_player = player
        logger.info("Media control claimed by %s", player.__class__.__name__)
        await self.__active_player.play()
        await self.__stream_media_type()
        await self.__active_player.stream_everything(client=None)

    async def release_playback(self, was_playing: bool = False) -> None:
        '''
        Releases the current player and loads the default media player.  The
        radio stays silent unless resumeRadioAfterSpotify is on AND both halves
        of "resume" hold: Spotify interrupted a playing radio, and Spotify itself
        was still playing when it let go.  The second condition is what keeps a
        Spotify paused at night from starting the radio twenty minutes later,
        when its Connect session times out.
        Arguments:
            was_playing (bool): Whether Spotify was playing on the target device
                at its last observation before the release.
        '''
        interrupted = self.__radio_interrupted
        self.__radio_interrupted = False
        logger.info("Playback released, loading default radio player")
        await self.load_default_media_player()
        if self.__resume_radio_after_spotify and interrupted and was_playing:
            logger.info("Resuming the radio Spotify interrupted")
            await self.__radio_player.play()
            await self.__radio_player.stream_everything(client=None)

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
        await self.__active_player.stream_everything(client=None)
        logger.info("Default radio player loaded")

    async def __stream_media_type(self, client=None) -> None:
        media_type = protocol.MEDIA_TYPE_RADIO
        if self.__active_player == self.__radio_player:
            media_type = protocol.MEDIA_TYPE_RADIO
        elif self.__active_player == self.__spotify_player:
            media_type = protocol.MEDIA_TYPE_SPOTIFY

        packet = protocol.frame(
            protocol.MEDIA_STREAM_TYPE, struct.pack("!B", media_type)
        )
        if client is None:
            await self.__server.broadcast(packet)
        else:
            await self.__server.send_to(client, packet)

    async def stream_everything(self, client) -> None:
        '''
        Snapshots the current media-player state (active player type plus
        all per-player fields) into a single new client.  No-op when no
        player has been initialised yet.
        Arguments:
            client: StreamWriter for the new connection.
        '''
        if self.__active_player:
            await self.__stream_media_type(client=client)
            await self.__active_player.stream_everything(client=client)

    async def run(self) -> None:
        '''
        Starts the media manager: launches Spotify polling and loads the
        default media player ready for playback.
        '''
        logger.info("MediaManager starting")
        await self.__spotify_player.run()
        await self.load_default_media_player()
        if self.__autoplay_radio:
            logger.info("Starting the default radio station (autoplayRadio)")
            await self.__radio_player.play()
            await self.__radio_player.stream_everything(client=None)

    def set_spotify_auth_listener(self, listener) -> None:
        '''
        Registers the coroutine the Spotify player awaits when its grant's validity
        changes, so SpotifyAuthService can re-broadcast the status immediately.
        Arguments:
            listener (callable): Zero-argument coroutine function.
        '''
        self.__spotify_player.set_auth_listener(listener)

    def spotify_auth_error(self) -> str | None:
        '''
        The Finnish reason the Spotify grant is unusable, or None while it works.
        Reported by the player, which is the only part that actually talks to
        Spotify — a cache file on disk proves nothing about whether it is accepted.
        '''
        return self.__spotify_player.spotify_auth_error_reason()

    async def refresh_spotify_auth(self) -> None:
        '''
        Forwards a completed re-authorization to the Spotify player.  Separate
        from apply_config_spotify(), which only re-reads the market: a new grant
        is not a config change, and the player has to ACT on it (poll now) rather
        than re-snapshot a value.
        '''
        await self.__spotify_player.refresh_auth()

    async def probe_spotify_playback(self) -> dict | None:
        '''
        Asks the Spotify player what is playing on ANY Connect device, for the
        Options view's device scan.  Forwarded rather than reached for directly,
        the same boundary spotify_auth_error() keeps: the player owns the Spotify
        client, the auth latch and the executor pattern, so all API access stays
        there.
        '''
        return await self.__spotify_player.probe_playback()

    async def list_spotify_devices(self) -> list | None:
        '''
        Lists the available Spotify Connect devices, or None when the call failed.
        Used only to resolve the configured device id to a display name.
        '''
        return await self.__spotify_player.list_devices()

    def spotify_target_device_id(self) -> str:
        '''The Connect device id the Spotify player currently claims from.'''
        return self.__spotify_player.target_device_id()

    async def stop_other_playback(self) -> bool:
        '''
        Silences whatever is playing locally so a Spotify device scan can be
        heard.  The scan asks the user to start playback on the device they want
        to select, which is impossible to judge over the radio — and the radio is
        exactly what is playing whenever Spotify has not claimed control.

        A no-op when Spotify is already active (there is nothing else to stop)
        or when no player has been loaded at all.

        Returns True only when a non-Spotify player that was ACTUALLY PLAYING
        was stopped — i.e. when there is something for resume_default_playback()
        to bring back.  A loaded-but-silent radio must not be started by the end
        of a scan the user never heard anything through.
        '''
        if self.__active_player is None or self.__active_player is self.__spotify_player:
            return False

        was_playing = (
            self.__radio_player.is_playing()
            if self.__active_player is self.__radio_player
            else False
        )
        logger.info(
            "Stopping %s for a Spotify device scan (was playing: %s)",
            self.__active_player.__class__.__name__, was_playing,
        )
        await self.__active_player.stop()
        # RadioPlayer.stop() produces no VLC state event (there is no
        # MediaPlayerStopped case in its handler), so without this re-stream
        # MEDIA_IS_PLAYING would keep claiming 1 over silence: the media card
        # shows a pause icon, and the next transport tap does the opposite of
        # what that icon says.  Every other caller of stop() re-streams too.
        await self.__active_player.stream_everything(client=None)
        return was_playing

    async def resume_default_playback(self) -> None:
        '''
        Restarts the radio a Spotify device scan silenced.  The scan's dialog
        promises playback resumes "tunnistuksen ajaksi" — for the duration of
        the identification — so the backend has to keep that promise on every
        way out of a scan: cancel, timeout, a dead client or a failed write.

        RadioPlayer.play() reloads the stream itself when no media is set, which
        is exactly the state stop() left it in.
        '''
        if self.__active_player is self.__spotify_player:
            # Spotify claimed control while the scan ran — which is the outcome
            # the scan was arranging.  The radio is only the fallback under it
            # and must stay silent.
            logger.debug("Not resuming the radio: Spotify holds playback")
            return
        if self.__active_player is not self.__radio_player:
            await self.load_default_media_player()
        logger.info("Resuming radio playback after a Spotify device scan")
        await self.__radio_player.play()
        await self.__radio_player.stream_everything(client=None)

    def health(self) -> dict:
        '''Reports which player currently owns playback.'''
        if self.__active_player is self.__spotify_player:
            return {"state": "ok", "detail": "Spotify"}
        if self.__active_player is self.__radio_player:
            return {"state": "ok", "detail": "Radio"}
        return {"state": "warn", "detail": "Ei aktiivista soitinta"}

    def get_run_task(self) -> asyncio.Task:
        '''
        Returns an asyncio Task that starts the media manager.
        '''
        return asyncio.create_task(self.run())
