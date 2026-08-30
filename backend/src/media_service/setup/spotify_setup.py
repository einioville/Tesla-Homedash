'''
Guided one-off Spotify setup helper for Tesla-Homedash.

Walks the user through the two manual Spotify steps that the running backend
expects to already be done:
  1. Completing the Spotify OAuth handshake so spotipy has a refresh token
     cached at the path `config.json` points to (`spotifyCachePath`).
  2. Identifying the Spotify Connect device ID that should be set as
     `spotifyDeviceId` in `config.json`.

The script does NOT edit `config.json` — it prints the device ID and the user
pastes it in by hand. Run from the `backend/` directory:

    uv run python -m src.media_service.setup.spotify_setup
'''
import sys
import webbrowser

import requests
from spotipy import Spotify, SpotifyException
from spotipy.oauth2 import SpotifyOAuth

from ...utils.config_parser import Config, default_config_path, get_env
from ..spotify_oauth import SPOTIFY_SCOPE

# Re-exported so this script keeps its old name for the value, while the one
# authoritative definition lives beside the player that depends on it. A scope
# that disagrees between issuer and reader silently invalidates the grant.
SCOPE = SPOTIFY_SCOPE

MAX_ATTEMPTS = 3


def _fail(message: str) -> None:
    '''
    Prints an error message to stderr and exits with code 1.
    Arguments:
        message (str): Human-readable explanation of what went wrong.
    '''
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def _run_oauth(config: Config, client_id: str, client_secret: str) -> SpotifyOAuth:
    '''
    Drives the manual Spotify OAuth flow: opens the authorize URL in the system
    browser, prompts the user to paste the redirect URL back, then exchanges
    the code for a token. spotipy writes the token cache to disk at
    `config.spotify_cache_path` as a side effect of `get_access_token`.

    Returns the SpotifyOAuth instance so the caller can reuse it for an
    authenticated Spotify client without re-reading the cache file.
    Arguments:
        config (Config): Loaded backend configuration.
        client_id (str): Spotify Developer app client ID.
        client_secret (str): Spotify Developer app client secret.
    '''
    sp_oauth = SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=config.spotify_redirect_uri,
        cache_path=config.spotify_cache_path,
        scope=SCOPE,
        open_browser=False,
    )

    auth_url = sp_oauth.get_authorize_url()
    print()
    print("Step 1 of 2 — Spotify OAuth handshake")
    print("-------------------------------------")
    print("Opening the Spotify authorization page in your browser...")
    print(f"If it doesn't open automatically, visit this URL manually:\n{auth_url}\n")
    webbrowser.open(auth_url)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        print(f"After authorizing, your browser will be redirected to a URL like")
        print(f"  {config.spotify_redirect_uri}?code=...")
        response = input("Paste that full redirect URL here: ").strip()

        # spotipy.parse_response_code returns the input unchanged when no
        # `code=` parameter is present — treat that as an invalid paste.
        code = sp_oauth.parse_response_code(response)
        if not response or code == response:
            print(f"  Could not find a `code=` parameter in that URL. "
                  f"(attempt {attempt}/{MAX_ATTEMPTS})\n")
            continue

        sp_oauth.get_access_token(code, as_dict=False, check_cache=False)
        print(f"\nSaved Spotify token cache to {config.spotify_cache_path}")
        return sp_oauth

    _fail("Too many invalid redirect URLs — aborting.")


def _pick_device(sp_oauth: SpotifyOAuth, config: Config) -> None:
    '''
    Asks the user to start playback on the Spotify Connect device they want the
    dashboard to control, then reads the currently-active playback and prints
    that device's name and ID. The user is expected to copy the ID into
    `spotifyDeviceId` in `config.json` themselves.
    Arguments:
        sp_oauth (SpotifyOAuth): Auth manager from the OAuth step (reused so
            the just-written token cache is picked up without re-reading).
        config (Config): Loaded backend configuration, used only to show the
            current `spotifyDeviceId` value for reference.
    '''
    sp = Spotify(auth_manager=sp_oauth)

    print()
    print("Step 2 of 2 — Spotify Connect device ID")
    print("---------------------------------------")

    for attempt in range(1, MAX_ATTEMPTS + 1):
        input(
            "Start playing something on the Spotify Connect device you want "
            "the dashboard to control, then press Enter..."
        )

        playback = sp.current_playback()
        if playback is None or not playback.get("device"):
            print(f"  No active playback detected — make sure Spotify is "
                  f"actually playing on the target device. "
                  f"(attempt {attempt}/{MAX_ATTEMPTS})\n")
            continue

        device = playback["device"]
        print()
        print(f"Active device: {device.get('name', '<unknown>')}")
        print(f"Device ID:     {device.get('id', '<unknown>')}")
        print()
        print("Copy the ID above into spotifyDeviceId in config.json.")
        print(f"(current value: {config.spotify_device_id})")
        return

    _fail("No active playback detected after multiple attempts — aborting.")


def main() -> None:
    '''
    Entry point. Loads `.env` + `config.json`, then runs the OAuth handshake
    followed by the device-ID lookup.
    '''
    config_path = get_env("CONFIG_PATH") or default_config_path()

    try:
        config = Config(config_path)
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        _fail(f"Could not load config.json: {e}")

    client_id = get_env("SPOTIFY_CLIENT_ID")
    client_secret = get_env("SPOTIFY_CLIENT_SECRET")
    if not client_id or not client_secret:
        _fail("SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET must be set in `.env`. "
              "Register a Spotify Developer app at "
              "https://developer.spotify.com/dashboard if you haven't yet.")

    try:
        sp_oauth = _run_oauth(config, client_id, client_secret)
        _pick_device(sp_oauth, config)
    except (SpotifyException, requests.exceptions.RequestException) as e:
        _fail(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        sys.exit(130)
