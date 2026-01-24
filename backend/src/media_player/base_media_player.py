from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from media_player import MediaPlayer


class BaseMediaPlayer:
    def __init__(self, media_player: MediaPlayer):
        self._media_player = media_player
    
    async def play(self) -> None:
        pass
    
    async def pause(self) -> None:
        pass
    
    async def skip_forward(self) -> None:
        pass
    
    async def skip_backward(self) -> None:
        pass
    
    async def pause_play(self) -> None:
        pass
    
    async def set_progress(self, progress_ms: int) -> None:
        pass
    
    async def stream_everything(self) -> None:
        pass
    
    async def claim_media_player(self) -> None:
        self._media_player.claim_media_control(self)
        
    async def release_media_player(self) -> None:
        self._media_player.load_default_media_player()
