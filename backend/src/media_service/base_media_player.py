from __future__ import annotations

import asyncio
import logging
import struct
from typing import TYPE_CHECKING

import aiohttp

from ..utils import protocol

if TYPE_CHECKING:
    from .media_manager import MediaManager

logger = logging.getLogger("media_service.base_media_player")


class BaseMediaPlayer:
    '''
    What MediaManager drives: transport controls, which do nothing unless a
    player overrides them, and the senders both players stream their state
    through.  Every packet goes via MediaManager.stream_data, which drops it
    unless this player is the active one.
    Arguments:
        media_manager (MediaManager): The manager that routes this player's packets.
    '''

    def __init__(self, media_manager: MediaManager):
        self._media_manager = media_manager

    async def play(self) -> None:
        pass

    async def pause(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def skip_forward(self) -> None:
        pass

    async def skip_backward(self) -> None:
        pass

    async def pause_play(self) -> None:
        pass

    async def set_progress(self, progress_ms: int) -> None:
        pass

    async def stream_everything(self, client=None) -> None:
        raise NotImplementedError

    async def _send(self, msg_type: int, payload: bytes, client=None) -> None:
        '''
        Frames one media packet and hands it to the manager.
        Arguments:
            msg_type (int): A protocol.MEDIA_* code.
            payload (bytes): The packet's payload.
            client (StreamWriter | None): One client, or None for every client.
        '''
        await self._media_manager.stream_data(
            data=protocol.frame(msg_type, payload), player=self, client=client)

    async def _send_text(self, msg_type: int, text: str, client=None) -> None:
        '''
        Sends a len(2B) + UTF-8 text packet (MEDIA_STREAM_NAME / _ARTISTS).
        Arguments:
            msg_type (int): A protocol.MEDIA_* code.
            text (str): The text.
            client (StreamWriter | None): One client, or None for every client.
        '''
        raw = text.encode("utf-8")
        await self._send(msg_type, struct.pack("!H", len(raw)) + raw, client)

    async def _send_image(self, url: str | None, client=None,
                          timeout: aiohttp.ClientTimeout | None = None) -> None:
        '''
        Downloads a cover image and sends it as MEDIA_STREAM_IMAGE.  Nothing is
        sent when there is no URL or the download fails; the dashboard keeps the
        image it has.
        Arguments:
            url (str | None): The image URL.
            client (StreamWriter | None): One client, or None for every client.
            timeout (ClientTimeout | None): The download's bound; None is aiohttp's
                default (five minutes).
        '''
        if not url:
            return
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        return
                    image = await response.read()
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.debug("Failed to download a cover image: %s: %s", type(e).__name__, e)
            return
        await self._send(protocol.MEDIA_STREAM_IMAGE, image, client)
