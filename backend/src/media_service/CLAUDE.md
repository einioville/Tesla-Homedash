# `media_service/` — media manager, players, Spotify auth & device

## The manager and the players

- **`media_manager.py`** (`MediaManager`) constructs both players, holds the **active** one, and
  routes controls to it. `claim_media_control` (Spotify took over) stops radio, switches active,
  starts playback, streams media type + full state; `release_playback`/`load_default_media_player`
  return to radio without auto-play. `stream_data` drops packets from the non-active player.
  `get_run_task` starts Spotify polling then loads radio. **Talks to:** both players, `Server`.
- **`base_media_player.py`**: the abstract control/stream interface both players implement.
- **`spotify_player.py`** (`SpotifyPlayer`) polls the Spotify Web API via spotipy on an APScheduler
  interval (10 s idle / 2 s active). `_update_state` is **serialised by `self._state_lock`**: it
  runs both on the timer and inline after every control command, and `claim_media_control` re-enters
  it via `play()`, so the guard (`if self._state_lock.locked(): return`) prevents both a deadlock and
  double claim/release. On detecting playback on `spotifyDeviceId` it claims control and streams
  name/artists/duration/image/progress/play-state; controls call `start/pause/next/previous/seek`.
  **Talks to:** Spotify Web API (run in an executor), `MediaManager`. *(If `spotifyDeviceId` is
  wrong, controls silently no-op — the `_current_device_id` vs `_target_device_id` comparison drives
  claim/release.)*
- **`radio_player.py`** (`RadioPlayer`) plays Nelonen Media HLS streams through libVLC, fetching the
  stream + art URL per station, cycling stations on skip, and restarting on VLC error/end events
  (guarded by `__intentional_stop`). **Talks to:** Nelonen API (aiohttp), libVLC, `MediaManager`.
- **`setup/spotify_setup.py`**: a one-off helper (run during setup) that completes the OAuth
  handshake and prints the active Connect device id for `config.json`. Not part of the runtime.

## `spotify_auth_service.py` + `spotify_oauth.py` — re-authorisation (issue #38)

Serves `0xA0`–`0xA4` so the OAuth grant can be refreshed from the dashboard instead of by SSHing in
to run `setup/spotify_setup.py`. **Only the authorization code crosses the wire** — single-use,
~10-minute, and worthless without `SPOTIFY_CLIENT_SECRET`, which never leaves the backend. The
exchange passes `check_cache=False` (with the default `True` a stale-but-valid cache short-circuits
and the new code is never redeemed) and runs in an executor, since spotipy is blocking `requests`.

> **The consent page is opened in the HOST'S REAL BROWSER. There is no embedded
> browser any more — Qt WebEngine was removed from the project entirely.** `handle_get_url`
> stands up a one-shot `asyncio.start_server` on the redirect URI's own host/port
> (`127.0.0.1:8080`), launches the page with `xdg-open`, and catches Spotify's redirect itself —
> so nothing is pasted by hand and the authorization code never leaves loopback. This is RFC 8252
> §7.3 (Loopback Interface Redirection), and it is also why the redirect URI is allowed to be plain
> HTTP. The reason it is not embedded is RFC 8252 §8.12: native apps **MUST NOT** use an embedded
> user-agent for authorization — an embedded view can read the user's password keystrokes and lift
> session cookies, which is exactly why providers block it. Measured: with WebGL and rendering both
> fixed, the embedded `WebEngineView` still could not get past the login gate.
>
> **This does NOT reintroduce the `NonInteractiveSpotifyOAuth` hazard below.** That one is spotipy's
> loopback server blocking a worker thread forever on `handle_request()`. This is an asyncio server
> on the main loop, bound to loopback only, torn down on the first hit or at `_FLOW_TTL_SECONDS` by
> `__cancel_pending()` (which awaits `wait_closed()`, so a retry can rebind the port).
>
> **Two traps in the listener, both found the hard way, both silent:**
> - **A browser opens more than one connection to that port** — a speculative preconnect, and a
>   `/favicon.ico` fetch the moment the response page renders. Neither carries the redirect's
>   parameters. Treating "no code" as fatal cancelled the flow *while the real exchange was still
>   in flight*, so the dashboard reported a failure for an authorization that had already succeeded
>   and written its token. Only a request actually carrying `code` or `error` may decide anything;
>   everything else gets a `204` and is ignored. `pending["claimed"]` makes the first code win, so a
>   reload of the redirect URL cannot re-enter the exchange with a spent code.
> - **Never `await Server.wait_closed()` from inside the callback handler.** Since CPython 3.12.1 it
>   waits for every active connection to drop too — and the handler IS one of those connections, so
>   it deadlocks there. The exchange completes and the token lands on disk, but the success reply
>   never reaches the frontend. `close()` alone releases the listening socket, which is all a retry
>   needs.
>
> There is no fallback left to degrade to, so **either half failing is a hard error** replied as
> `SPOTIFY_AUTH_URL` + `SPOTIFY_AUTH_ERROR`: without a listener the code cannot be caught, without a
> browser the page cannot be reached, and a dialog waiting forever for a redirect nobody can produce
> is worse than a message. The target supports this natively — README §Pi notes the dashboard runs
> *on top of* the full Raspberry Pi OS desktop, not as a kiosk, and the pre-existing
> `spotify_setup.py` already told the user to run it "from the Pi's desktop (it needs to open a
> browser window)".
>
> **The grant EXPIRES — 6 months, absolute.** Verified against
> `developer.spotify.com/documentation/web-api/tutorials/refreshing-tokens`: *"Refresh tokens issued
> to apps registered in the Developer Dashboard have a lifetime of 6 months … Refreshing an access
> token does not extend the refresh token's lifetime."* Announced 2026-06-18, enforced for existing
> apps **2026-07-20**, and it covers the authorization-code flow this app uses (PKCE or not). So
> re-authorization is not an incident-recovery tool — it is **routine maintenance roughly twice a
> year**, and the reason the Options view's card carries that warning in its `help`.
>
> Do not confuse the two expiries. The cache's `expires_in`/`expires_at` is the **access** token's
> ~1 hour, refreshed silently by spotipy before every request; the status packet's `expiresAt`
> carries that value and **must never be rendered as "authorization valid until"** — it would imply
> the grant dies within the hour while hiding the only expiry the user ever needs. Spotify does not
> expose the grant's issue date, so a real "valid until" would mean recording our own timestamp at
> each successful exchange.
>
> When it does expire the token endpoint returns **HTTP 400 `{"error": "invalid_grant"}`**, raised by
> spotipy as `SpotifyOauthError`. `SpotifyPlayer._call_spotify` catches that **before** the
> `SpotifyBaseException` arm it is a subclass of — only there can "the grant is gone" be told apart
> from "the API said no" — and `_note_auth_failure` latches the player off:
> - **Only terminal codes latch** (`invalid_grant`, `invalid_client`, `unauthorized_client`,
>   `invalid_scope`, plus `NonInteractiveSpotifyOAuth`'s message-only "No usable Spotify token
>   cache"). A 5xx from the token endpoint or a network blip is logged and ignored, or one bad
>   minute at Spotify would silence the dashboard until someone restarted it.
> - **While latched, `_call_spotify` and `_update_state` return before touching the network.**
>   spotipy does not clear its cache on rejection, so without this the poller retries a dead token
>   every 10 s forever, for nothing. `refresh_auth()` clears the latch and resumes.
> - `_auth_listener` (wired in `start_services` to `SpotifyAuthService.notify_auth_state_changed`)
>   re-broadcasts the status the instant the verdict changes, so the dashboard's prompt appears then
>   rather than at the next reconnect.
>
> **`build_status()` asks the player first.** A cached refresh token Spotify has stopped accepting
> still sits happily on disk, so cache presence proves nothing; only the player has actually tried
> to use it. Its verdict overrides, and sets `needsReauth`.
>
> **The gate on Spotify's login page is Google reCAPTCHA Enterprise, not Cloudflare.** Measured:
> `accounts.spotify.com` answers `server: envoy` with no `cf-*` header, and its CSP whitelists
> `google.com/recaptcha`. `challenge-orchestrator /v1/invoke-challenge-command` is Spotify's own
> wrapper around it. This matters because it scores the *execution environment* — a Chromium with
> no WebGL context cannot produce a solvable challenge, which is how the whole flow dead-ended on
> a WSL2 dev box (the GPU half of that story is in `scripts/CLAUDE.md`). Earlier comments in this
> repo blamed Cloudflare; they were wrong.

`spotify_oauth.py` holds the **one canonical `SPOTIFY_SCOPE`** and `NonInteractiveSpotifyOAuth`.
Both are fixes for real hazards found while building this:
- The scope literal was **duplicated** between the player and the setup helper. spotipy stamps the
  *issuing* manager's scope onto the cached token and then refuses the cache unless the *reading*
  manager's scope is a subset, so a re-auth issued with a narrower scope silently kills playback with
  no error anywhere.
- Stock `SpotifyOAuth` falls back to an **interactive** handshake when the cache is unusable: for a
  `127.0.0.1` redirect it starts a local HTTP server and blocks forever *inside the player's
  executor thread*, after which APScheduler refuses every later poll. Exactly the failure shape
  `../weather_service/CLAUDE.md` records for the weather service. The subclass raises instead,
  turning a silent hang into a logged error.
- **A successful exchange could leave nothing on disk and still report success.** spotipy's
  `CacheFileHandler` swallows every `OSError` from the token write and **never creates parent
  directories**, so a `spotifyCachePath` whose directory is missing loses the grant silently: a tick
  in the Options view, `authorized=false` in the status broadcast a line later, and the single-use
  code already spent. `build_oauth` now `makedirs` the parent (warn-only — it runs on every client
  connect via `build_status()`, so it must never crash a status read), and `handle_code` **verifies
  the cache afterwards** rather than assuming, replying with the path when it is empty.
- **The CSRF state check was a no-op.** The frontend round-tripped the backend's own nonce and the
  backend compared it with itself, because spotipy's `parse_response_code` discards the state
  Spotify echoes. `handle_code` now uses **`parse_auth_response_url`**, which returns `(state, code)`,
  and the comparison is **mandatory** — a missing state is a failed check, not a skipped one.

## `spotify_device_service.py` — device identification

Serves `0xA5`–`0xA9` so `spotifyDeviceId` can be discovered from the dashboard. It exists because a
wrong value **fails silently**: `SpotifyPlayer` claims control only when `_current_device_id ==
_target_device_id`, so a stale id makes every transport control a no-op with nothing in the log —
and until now the only fix was SSHing in to run `setup/spotify_setup.py`. The flow is "play
something on the device you want, then confirm what the backend sees": the user starts playback, the
service polls `current_playback()` every 2 s and streams back the **device** (name, type, volume,
`is_restricted`) beside the **track** (name, artists, album, cover URL), so the device is confirmed
against both what is on screen and what is audible.

**All Spotify API access stays in `SpotifyPlayer`** (`probe_playback`, `list_devices`), behind its
`_call_spotify` executor helper and its auth latch; the service reaches them through `MediaManager`,
the same boundary `SpotifyAuthService` uses for `spotify_auth_error()`. A latched-off grant is
reported once rather than polled against. Load-bearing details, most of them defects found in review:
- **The write goes through `ConfigService.apply_write()`**, not around it — `handle_set`'s body was
  extracted so both share one validated path (coerce → dynamic options → guard → unchanged
  short-circuit → `set` → `save` → rollback on `OSError` → hooks → broadcast). That is why
  `spotifyDeviceId` had to become a real `SETTINGS_SCHEMA` entry: the schema **is** the write
  allow-list. It carries a `spotify_device_id` validator, because a `string` with no validator
  accepts `""` — and an empty target reintroduces exactly the silent no-op this feature removes.
- **`SpotifyPlayer.apply_config()` now re-reads `spotifyDeviceId`** and spawns an immediate
  `_update_state()` so the claim happens while the user is still looking at the screen that caused
  it. The task is **retained with a done-callback**: the loop holds only a weak reference, so a
  bare `create_task` can be collected mid-flight and its exception never retrieved.
- **A scan is owned by one client's `StreamWriter`.** `Server.__safe_write` *swallows*
  `ConnectionError`, drops the client and returns normally, so a write to a dead peer never raises
  — the poll loop therefore checks `writer.is_closing()` itself, or a killed dashboard would leave
  it polling Spotify for the full `_SCAN_TTL_SECONDS` (300). `SCAN_STOP` and `SELECT` are
  owner-gated too: with two panels open, one panel's *Peruuta* must not cancel the other's scan.
- **The radio is stopped for the scan and put back afterwards.** `stop_other_playback()` returns
  whether it silenced a genuinely *playing* non-Spotify player and re-streams the play state —
  `RadioPlayer.stop()` emits no VLC event, so without that `MEDIA_IS_PLAYING` stays 1 and the media
  card shows a pause icon over silence. Every scan-ending path resumes, except a successful select
  on a device that was already playing, where `SpotifyPlayer` claims within one poll and resuming
  would emit a second of radio for nothing. A *failed* select deliberately does NOT end the scan,
  so the retry has something to retry against.
- **`scanId` is a frontend-generated epoch**, echoed on every state and result and required on a
  select. A single "is a flow running" bool cannot tell WHICH flow a packet belongs to: cancel a
  scan, start another, and a state already in flight repopulates the dialog with the previous
  device — which the user can then save. The two fences answer different questions and both stay.
