from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .media_manager import MediaManager


class BaseMediaPlayer:
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
