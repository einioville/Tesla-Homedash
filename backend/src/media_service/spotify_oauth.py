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

import json
import logging
import os
import time

from spotipy.oauth2 import SpotifyOAuth, SpotifyOauthError

from ..utils.config_parser import Config, get_env

logger = logging.getLogger("media_service.spotify_oauth")

# THE canonical scope set: what the player needs, and the scope every READING
# manager is built with. Changing it invalidates every existing grant, so a
# change here means every deployment must re-authorize from the Options view.
SPOTIFY_SCOPE = (
    "user-read-playback-state,"
    "user-modify-playback-state,"
    "user-read-currently-playing"
)

# Asked for at authorization time on top of SPOTIFY_SCOPE, and never required to
# READ a grant. Only the account's e-mail needs it (the Options view names the
# account the grant belongs to). Kept out of SPOTIFY_SCOPE on purpose: a reader
# built with it would refuse every grant issued before it existed, which is the
# same silent playback death the one-constant rule above prevents. Issuing with a
# WIDER scope than the reader's is safe; spotipy stamps the refreshing manager's
# scope back onto the cache at each refresh, so the stamp simply narrows to
# SPOTIFY_SCOPE again while Spotify keeps the wider grant on its side.
SPOTIFY_AUTH_SCOPE = SPOTIFY_SCOPE + ",user-read-email"

# Spotify's refresh tokens expire six months after issue and refreshing does not
# extend them. 180 days is the conservative reading of "6 months" (every run of
# six calendar months is 181-184 days), so the Options view warns a day or few
# early rather than late.
GRANT_LIFETIME_SECONDS = 180 * 24 * 3600

# Suffix of the grant record written beside the token cache. See write_grant_record.
_GRANT_RECORD_SUFFIX = ".grant.json"


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


def build_oauth(config: Config, interactive: bool = False,
                scope: str = SPOTIFY_SCOPE) -> SpotifyOAuth:
    '''
    Builds a SpotifyOAuth from the .env credentials and the config.json paths.
    Arguments:
        config (Config): Loaded backend configuration (redirect URI, cache path).
        interactive (bool): True only for the one-off CLI setup helper, which is
            allowed to prompt.  Every in-process caller passes False.
        scope (str): Scope to request.  SPOTIFY_SCOPE for anything that READS
            the cache; SPOTIFY_AUTH_SCOPE only for a manager that ISSUES a new
            grant (see SPOTIFY_AUTH_SCOPE for why the two differ).
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
        scope=scope,
        open_browser=False,
    )


def _grant_record_path(config: Config) -> str:
    '''
    Where the grant record lives: beside the token cache, named after it.
    Arguments:
        config (Config): Loaded backend configuration (cache path).
    '''
    return config.spotify_cache_path + _GRANT_RECORD_SUFFIX


def read_grant_record(config: Config) -> dict:
    '''
    Reads the record of the last authorization made through this app, or {} when
    there is none (a grant from before the record existed, or a cache carried in
    from elsewhere) or it cannot be read.  Never raises: it is read for every
    status snapshot, which must not fail over a cosmetic file.
    Arguments:
        config (Config): Loaded backend configuration (cache path).
    '''
    try:
        with open(_grant_record_path(config), encoding="utf-8") as f:
            record = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        logger.warning("Could not read the Spotify grant record: %s", e)
        return {}
    return record if isinstance(record, dict) else {}


def write_grant_record(config: Config, profile: dict | None) -> None:
    '''
    Records that a grant was issued now, and whose it is.

    Spotify exposes neither when a grant was issued nor when it runs out, and the
    token cache cannot carry it: spotipy rebuilds the cache document from each
    refresh response, dropping any key it did not put there. So the one fact the
    user needs twice a year — when to re-authorize — exists only if this app
    writes it down at the moment of the exchange.  The account details ride along
    so the Options view can say which account is signed in without an API call
    on every snapshot.

    Written atomically (temp file + replace) and owner-only: it holds an e-mail
    address.  Raises OSError; the caller decides how much a failure matters.
    Arguments:
        config (Config): Loaded backend configuration (cache path).
        profile (dict | None): SpotifyPlayer.current_user() result, or None when
            the profile could not be fetched — the date is recorded regardless.
    '''
    profile = profile or {}
    record = {
        "authorizedAt": int(time.time()),
        "email": profile.get("email") or "",
        "displayName": profile.get("displayName") or "",
        "userId": profile.get("id") or "",
    }
    path = _grant_record_path(config)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False)
    os.replace(tmp, path)


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
