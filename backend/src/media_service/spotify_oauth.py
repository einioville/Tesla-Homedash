'''
Shared Spotify OAuth primitives: the one canonical scope string, and a
SpotifyOAuth subclass that can never block on an interactive handshake.

Three callers need identical behaviour — the player, the re-authorization service
and the one-off CLI setup helper — and two of the three used to carry their own
copy of the scope literal.  That duplication is a live hazard rather than mere
untidiness: spotipy stamps the ISSUING manager's scope onto the cached token and
then refuses the cache unless the READING manager's scope is a subset of it, so a
re-auth issued with a narrower scope silently kills playback with no error
anywhere.  One constant, used everywhere, is the fix.
'''

import logging
import os

from spotipy.oauth2 import SpotifyOAuth, SpotifyOauthError

from ..utils.config_parser import Config, get_env

logger = logging.getLogger("media_service.spotify_oauth")

# THE canonical scope set. Changing it invalidates every existing grant, so a
# change here means every deployment must re-authorize from the Options view.
SPOTIFY_SCOPE = (
    "user-read-playback-state,"
    "user-modify-playback-state,"
    "user-read-currently-playing"
)


class NonInteractiveSpotifyOAuth(SpotifyOAuth):
    '''
    SpotifyOAuth that refuses to fall back to an interactive handshake.

    Without this, a missing or scope-mismatched token cache sends spotipy into
    get_auth_response(), which for an http://127.0.0.1:PORT redirect starts a
    local HTTP server and blocks on handle_request() FOREVER — inside the
    player's executor thread.  APScheduler then refuses every later poll
    ("maximum number of running instances reached") and Spotify is dead until a
    restart, with nothing in the log saying why.  Raising turns that silent hang
    into one logged error per poll, and lets the Options view be the fix.

    Exactly the failure mode CLAUDE.md 5.2.4 records for the weather service,
    in a different service.
    '''

    def get_auth_response(self, open_browser=None):
        '''
        Overrides spotipy's interactive fallback.  Never opens a browser, never
        starts a local server, never reads stdin.
        Arguments:
            open_browser (bool | None): Ignored; kept for signature compatibility.
        '''
        raise SpotifyOauthError(
            "No usable Spotify token cache — re-authorize from the Options view"
        )


def build_oauth(config: Config, interactive: bool = False) -> SpotifyOAuth:
    '''
    Builds a SpotifyOAuth from the .env credentials and the config.json paths.
    Arguments:
        config (Config): Loaded backend configuration (redirect URI, cache path).
        interactive (bool): True only for the one-off CLI setup helper, which is
            allowed to prompt.  Every in-process caller passes False.
    '''
    # spotipy's CacheFileHandler swallows every OSError from the token write and
    # never creates parent directories, so a cache path whose directory is missing
    # loses the grant silently: the Options view shows a tick, the status snapshot
    # a moment later says "no grant", and the single-use code is already spent.
    # Only a warning here — build_status() calls this on every client connect, so
    # it must never be able to crash a status read, and handle_code() verifies the
    # write afterwards anyway.
    cache_dir = os.path.dirname(config.spotify_cache_path)
    if cache_dir:
        try:
            os.makedirs(cache_dir, exist_ok=True)
        except OSError as e:
            logger.warning(
                "Could not create the Spotify cache directory %s: %s", cache_dir, e
            )

    cls = SpotifyOAuth if interactive else NonInteractiveSpotifyOAuth
    return cls(
        client_id=get_env("SPOTIFY_CLIENT_ID"),
        client_secret=get_env("SPOTIFY_CLIENT_SECRET"),
        redirect_uri=config.spotify_redirect_uri,
        cache_path=config.spotify_cache_path,
        scope=SPOTIFY_SCOPE,
        open_browser=False,
    )


def scope_covers(required: str, granted: str | None) -> bool:
    '''
    True when a cached token's scope covers everything this app needs.

    Re-implemented here rather than calling spotipy's private _is_scope_subset,
    and deliberately NOT done with validate_token(), which refreshes over the
    network — wrong for a status snapshot sent on every client connect.
    Arguments:
        required (str): Scope string this app asks for.
        granted (str | None): Scope string stored on the cached token.
    '''
    if not granted:
        return False
    needed = {s for s in required.replace(",", " ").split() if s}
    have = {s for s in granted.replace(",", " ").split() if s}
    return needed.issubset(have)
