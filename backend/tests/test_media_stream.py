'''
Pins the media packets the radio and Spotify players stream to the dashboard:
their order, their bytes, and how each fetches its cover image (which timeout,
what a failed fetch does).  The players are built without libVLC or Spotify;
aiohttp is replaced by a fake session.

Runs under pytest, or standalone: `uv run python tests/test_media_stream.py`.
'''
import asyncio
import os
import struct
import sys

import aiohttp

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.media_service.radio_player import RadioPlayer  # noqa: E402
from src.media_service.spotify_player import _IMAGE_FETCH_TIMEOUT, SpotifyPlayer  # noqa: E402
from src.utils import protocol  # noqa: E402


class Manager:
    '''Collects (packet, client) pairs the way MediaManager.stream_data receives them.'''

    def __init__(self):
        self.sent = []

    async def stream_data(self, data, player, client=None):
        '''Records one packet.'''
        self.sent.append((data, client))


class Response:
    def __init__(self, status, body):
        self.status, self.body = status, body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def read(self):
        '''The response body.'''
        return self.body


class Session:
    '''Stands in for aiohttp.ClientSession; records the timeout each one got.'''
    timeouts = []
    status = 200

    def __init__(self, **kwargs):
        Session.timeouts.append(kwargs.get("timeout"))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def get(self, url):
        '''Answers with the URL as the body.'''
        if url == "boom":
            raise aiohttp.ClientError("boom")
        return Response(Session.status, url.encode())


def _text(msg_type, text):
    raw = text.encode("utf-8")
    return protocol.frame(msg_type, struct.pack("!H", len(raw)) + raw)


class Vlc:
    def __init__(self, playing):
        self.playing = playing

    def is_playing(self):
        '''libVLC returns 0/1.'''
        return 1 if self.playing else 0


def _radio(image_url):
    player = RadioPlayer.__new__(RadioPlayer)
    player._media_manager = Manager()
    player._RadioPlayer__channel = "Radio Suomipop"
    player._RadioPlayer__image_url = image_url
    player._RadioPlayer__vlc_player = Vlc(True)
    return player


def _spotify(image_url):
    player = SpotifyPlayer.__new__(SpotifyPlayer)
    player._media_manager = Manager()
    player._is_playing = False
    player._song_details = {
        "name": "Kappale ä", "duration_ms": 200_000, "progress_ms": 1234,
        "artists": [{"name": "A"}, {"name": "B"}],
        "album": {"images": [{"url": image_url, "width": 640, "height": 640}]} if image_url else {},
    }
    return player


def _with_fake_aiohttp(fn):
    original = aiohttp.ClientSession
    aiohttp.ClientSession = Session
    Session.timeouts = []
    Session.status = 200
    try:
        return fn()
    finally:
        aiohttp.ClientSession = original


def test_radio_stream_everything():
    def run():
        player = _radio("http://img")
        asyncio.run(player.stream_everything(client="c"))
        return player._media_manager.sent, Session.timeouts
    sent, timeouts = _with_fake_aiohttp(run)
    assert sent == [
        (_text(protocol.MEDIA_STREAM_NAME, "Radio Suomipop"), "c"),
        (protocol.frame(protocol.MEDIA_STREAM_IMAGE, b"http://img"), "c"),
        (protocol.frame(protocol.MEDIA_IS_PLAYING, b"\x01"), "c"),
    ]
    # The radio's cover fetch runs on aiohttp's default timeout.
    assert timeouts == [None]


def test_radio_without_image_or_failed_fetch_sends_no_image():
    for url, status in ((None, 200), ("http://img", 404), ("boom", 200)):
        def run():
            Session.status = status
            player = _radio(url)
            asyncio.run(player.stream_everything())
            return [data[4] for data, _ in player._media_manager.sent]
        assert _with_fake_aiohttp(run) == [protocol.MEDIA_STREAM_NAME, protocol.MEDIA_IS_PLAYING], url


def test_spotify_stream_everything():
    def run():
        player = _spotify("http://cover")
        asyncio.run(player.stream_everything(client="c"))
        return player._media_manager.sent, Session.timeouts
    sent, timeouts = _with_fake_aiohttp(run)
    assert sent == [
        (protocol.frame(protocol.MEDIA_IS_PLAYING, b"\x00"), "c"),
        (_text(protocol.MEDIA_STREAM_NAME, "Kappale ä"), "c"),
        (_text(protocol.MEDIA_STREAM_ARTISTS, "A, B"), "c"),
        (protocol.frame(protocol.MEDIA_STREAM_DURATION, struct.pack("!I", 200_000)), "c"),
        (protocol.frame(protocol.MEDIA_STREAM_PROGRESS, struct.pack("!I", 1234)), "c"),
        (protocol.frame(protocol.MEDIA_STREAM_IMAGE, b"http://cover"), "c"),
    ]
    assert timeouts == [_IMAGE_FETCH_TIMEOUT]


def test_spotify_nothing_streamed_before_a_song():
    player = _spotify(None)
    player._song_details = None
    asyncio.run(player.stream_everything())
    assert player._media_manager.sent == []


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS  {test.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL  {test.__name__}: {e}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(1 if failures else 0)
