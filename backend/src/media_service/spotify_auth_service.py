'''
Spotify re-authorization driven from the Options view.

Refreshing the OAuth grant used to mean SSHing to the Pi and running
`media_service/setup/spotify_setup.py` by hand.  This serves the same handshake
over the protocol so it can be done from the dashboard itself, which is the only
interface the deployment actually has — the panel is fullscreen and keyboard-less.

The split keeps the secret where it belongs: the BACKEND builds the authorize URL
and performs the token exchange (it holds SPOTIFY_CLIENT_SECRET), while the
frontend only renders the page and reports back the authorization code Spotify
redirects to.  That code is single-use, expires in about ten minutes, and is
worthless without the secret — so the plain TCP link never carries an access or
refresh token, only the code.
'''

import asyncio
import json
import logging
import secrets
import shutil
import struct
import time
import urllib.parse

import requests
from spotipy.oauth2 import SpotifyOauthError

from ..utils import protocol
from .spotify_oauth import SPOTIFY_SCOPE, build_oauth, scope_covers

logger = logging.getLogger("media_service.spotify_auth")

# A pending flow is abandoned after this long. Spotify's own codes expire in about
# ten minutes, so holding one longer only invites a confusing failure.
_FLOW_TTL_SECONDS = 600


class SpotifyAuthService:
    '''
    Serves the SPOTIFY_AUTH_* codes: hands the frontend an authorize URL,
    exchanges the authorization code it intercepts, writes the resulting grant to
    the spotipy token cache, and reports the current grant state.

    Registered with the Server both as a handler target and as a snapshot source,
    exactly like ConfigService.  Stateless apart from one pending flow, so it has
    no run task.
    Arguments:
        config (Config): Shared configuration (redirect URI, cache path).
        server (Server): TCP server used for send_to and broadcast.
        media_manager (MediaManager): Told after a successful exchange so the
            player reflects the new grant immediately, not at its next poll.
    '''

    def __init__(self, config, server, media_manager):
        self.__config = config
        self.__server = server
        self.__media_manager = media_manager
        # One flow at a time: a new GET_URL replaces whatever was pending.
        self.__pending: dict | None = None

    # ── Handlers ──────────────────────────────────────────────────

    async def handle_get_url(self, _payload: bytes, writer) -> None:
        '''
        SPOTIFY_AUTH_GET_URL handler: starts a flow and replies with the URL the
        frontend should open.
        Arguments:
            _payload (bytes): Unused; the request carries no body.
            writer (StreamWriter): The requesting client.
        '''
        try:
            oauth = build_oauth(self.__config)
            nonce = secrets.token_urlsafe(16)
            # The nonce goes to get_authorize_url(), NOT to the constructor: with
            # SpotifyOAuth.state left None, spotipy omits `state` from the token
            # POST body, which is what Spotify expects.
            url = oauth.get_authorize_url(state=nonce)
        except Exception as e:
            logger.error("Could not build the Spotify authorize URL: %s", e)
            await self.__reply_url_error(
                writer,
                "Spotify-tunnuksia ei ole määritetty (SPOTIFY_CLIENT_ID / _SECRET)",
            )
            return

        # A new flow replaces whatever was pending, listener and all — otherwise
        # the second attempt cannot rebind the redirect port.
        await self.__cancel_pending()
        pending = {
            "state": nonce,
            "oauth": oauth,
            "created": time.monotonic(),
            "writer": writer,
            "server": None,
            "timer": None,
            # Set by the first redirect that actually carries a code, so a reload
            # or a second connection cannot re-enter the exchange.
            "claimed": False,
        }
        self.__pending = pending

        # The external-browser path (RFC 8252 §7.3, Loopback Interface
        # Redirection): hand the consent page to the host's real browser and catch
        # the redirect ourselves. Spotify's login sits behind reCAPTCHA Enterprise,
        # which an embedded browser does not get past, and RFC 8252 §8.12 says
        # native apps MUST NOT use an embedded user-agent for authorization anyway.
        #
        # There is no fallback left to degrade to, so either half failing is a hard
        # error the user has to see: without a listener the code cannot be caught,
        # and without a browser the page cannot be reached. Failing loudly here
        # beats a dialog that waits forever for a redirect nobody can produce.
        try:
            pending["server"] = await self.__start_callback_server(pending)
        except OSError as e:
            logger.error(
                "Could not listen on the Spotify redirect URI %s: %s",
                self.__config.spotify_redirect_uri, e,
            )
            await self.__cancel_pending()
            await self.__reply_url_error(
                writer,
                f"Osoitetta {self.__config.spotify_redirect_uri} ei voitu kuunnella: {e}",
            )
            return

        pending["timer"] = asyncio.create_task(self.__expire(pending))
        if not await self.__open_in_browser(url):
            await self.__cancel_pending()
            await self.__reply_url_error(
                writer, "Selainta ei voitu avata (xdg-open puuttuu)"
            )
            return

        logger.info("Spotify authorization flow started | consent page opened in the browser")
        body = json.dumps(
            {
                "url": url,
                "redirectUri": self.__config.spotify_redirect_uri,
                "state": nonce,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        await self.__server.send_to(
            writer,
            self.__json_frame(protocol.SPOTIFY_AUTH_URL, protocol.SPOTIFY_AUTH_OK, body),
        )

    # ── Loopback callback (the external-browser flow) ─────────────

    async def __start_callback_server(self, pending: dict):
        '''
        Listens on the redirect URI's own host and port for exactly the redirect
        Spotify is about to make, so the authorization code never has to be read
        off the screen and pasted back by hand.

        This does NOT reintroduce the hazard `NonInteractiveSpotifyOAuth` exists to
        prevent (§5.2.8d): spotipy's version blocks a worker thread forever on
        `handle_request()`. This one is an asyncio server on the main loop, bound
        to loopback only, torn down on the first hit or at `_FLOW_TTL_SECONDS`.
        Arguments:
            pending (dict): The flow this listener belongs to.
        '''
        parsed = urllib.parse.urlparse(self.__config.spotify_redirect_uri)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 80

        async def respond(http_writer, status: bytes, body: bytes = b"") -> None:
            '''
            Writes one minimal HTTP response and closes the connection.
            Arguments:
                http_writer (StreamWriter): The browser's connection.
                status (bytes): Status line remainder, e.g. b"200 OK".
                body (bytes): UTF-8 HTML body; empty for a bodiless status.
            '''
            try:
                http_writer.write(
                    b"HTTP/1.1 " + status + b"\r\n"
                    b"Content-Type: text/html; charset=utf-8\r\n"
                    b"Content-Length: " + str(len(body)).encode() +
                    b"\r\nConnection: close\r\n\r\n" + body
                )
                await http_writer.drain()
            except OSError:
                # The browser hung up early; anything we parsed is still good.
                pass
            finally:
                http_writer.close()

        async def handle(reader, http_writer) -> None:
            '''
            Serves the one redirect, then hands the code to the exchange.
            Arguments:
                reader (StreamReader): The browser's request.
                http_writer (StreamWriter): The browser's connection.
            '''
            code = state = error = None
            try:
                request_line = await asyncio.wait_for(reader.readline(), 15)
                parts = request_line.decode("latin-1", "replace").split(" ")
                query = urllib.parse.parse_qs(urllib.parse.urlparse(parts[1]).query) \
                    if len(parts) > 1 else {}
                code = (query.get("code") or [None])[0]
                state = (query.get("state") or [None])[0]
                error = (query.get("error") or [None])[0]
            except (asyncio.TimeoutError, OSError, IndexError, UnicodeError) as e:
                logger.warning("Malformed request on the Spotify redirect port: %s", e)

            # A browser opens MORE than one connection to this port: a speculative
            # preconnect before the navigation, and a /favicon.ico fetch the moment
            # the page below renders. Neither carries the redirect's parameters, and
            # treating "no code" as fatal cancelled the flow WHILE the real exchange
            # was still in flight — reporting a failure for an authorization that had
            # already succeeded and written its token. So only a request actually
            # carrying `code` or `error` is allowed to decide anything; everything
            # else is answered and ignored.
            if code is None and error is None:
                await respond(http_writer, b"204 No Content")
                return

            # First code wins. A reload of the redirect URL would otherwise re-enter
            # the exchange with a code Spotify has already spent.
            if pending.get("claimed"):
                await respond(http_writer, b"204 No Content")
                return
            pending["claimed"] = True

            if error:
                text = f"Spotify palautti virheen: {error}. Voit sulkea taman valilehden."
            else:
                text = "Tunnistautuminen valmis. Voit sulkea taman valilehden."
            page = (
                "<!doctype html><html lang=\"fi\"><meta charset=\"utf-8\">"
                "<title>Tesla-Homedash</title>"
                "<body style=\"font-family:sans-serif;background:#111;color:#eee;"
                "display:flex;align-items:center;justify-content:center;height:100vh\">"
                f"<p>{text}</p></body></html>"
            ).encode("utf-8")
            await respond(http_writer, b"200 OK", page)

            # Only now: the reply above must reach the browser before the exchange
            # (which talks to Spotify over the network) delays anything.
            if self.__pending is not pending:
                return
            reply_to = pending["writer"]
            if error:
                await self.__cancel_pending()
                await self.__reply_result(reply_to, False, f"Spotify palautti virheen: {error}")
                return
            await self.__exchange_and_reply(pending, code, state, reply_to)

        return await asyncio.start_server(handle, host, port)

    async def __open_in_browser(self, url: str) -> bool:
        '''
        Opens the authorize URL in the host's default browser.  A system call, so
        it belongs on this side — the same boundary `display_service` follows.
        Returns False (rather than raising) when the host has no launcher, so the
        frontend can fall back to showing the URL.
        Arguments:
            url (str): The Spotify authorize URL.
        '''
        opener = (shutil.which("xdg-open") or shutil.which("x-www-browser")
                  or shutil.which("sensible-browser"))
        if opener is None:
            logger.warning("No browser launcher (xdg-open) on this host")
            return False
        try:
            await asyncio.create_subprocess_exec(
                opener, url,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except OSError as e:
            logger.warning("Could not launch a browser with %s: %s", opener, e)
            return False
        return True

    async def __cancel_pending(self) -> None:
        '''
        Tears the pending flow down: closes its loopback listener and cancels the
        expiry timer.

        Deliberately does NOT await `Server.wait_closed()`. Since CPython 3.12.1
        that waits for every active connection to drop as well — and this is
        normally reached from INSIDE the callback handler, which is itself one of
        those connections. Awaiting it there deadlocks the handler, so the exchange
        completes and writes the token but its success reply never reaches the
        frontend: the dashboard sits on "käynnissä" forever, or shows whatever
        earlier failure did get through. `close()` releases the listening socket on
        its own, which is all a retry needs.
        '''
        pending = self.__pending
        self.__pending = None
        if pending is None:
            return
        timer = pending.get("timer")
        if timer is not None:
            pending["timer"] = None
            timer.cancel()
        server = pending.get("server")
        if server is not None:
            pending["server"] = None
            server.close()

    async def __expire(self, pending: dict) -> None:
        '''
        Closes an abandoned flow's listener so the redirect port does not stay
        bound.  Spotify's codes expire in about ten minutes anyway.
        Arguments:
            pending (dict): The flow to expire.
        '''
        try:
            await asyncio.sleep(_FLOW_TTL_SECONDS)
        except asyncio.CancelledError:
            return
        pending["timer"] = None
        if self.__pending is pending:
            logger.info("Spotify authorization flow expired; closing the listener")
            await self.__cancel_pending()

    async def __exchange_and_reply(self, pending: dict, code: str,
                                   returned_state, writer) -> None:
        '''
        Verifies the state, redeems the code and reports the outcome.  Shared by
        the loopback listener and the legacy SPOTIFY_AUTH_CODE handler.
        Arguments:
            pending (dict): The flow the code belongs to.
            code (str): Authorization code from the redirect.
            returned_state: State Spotify echoed back, compared with the nonce.
            writer (StreamWriter): Client to reply to.
        '''
        # Mandatory, not "if present": the state has to be the nonce THIS flow
        # issued or the code belongs to a superseded request. A missing state is a
        # failed check, not a skipped one.
        if returned_state != pending["state"]:
            logger.warning("Spotify auth state mismatch; rejecting the code")
            await self.__cancel_pending()
            await self.__reply_result(writer, False, "Istuntotunniste ei täsmää")
            return

        oauth = pending["oauth"]

        loop = asyncio.get_running_loop()
        try:
            # Blocking `requests` work, so it goes to an executor. check_cache is
            # False on purpose: with the default True a stale-but-valid cache
            # short-circuits and the new code is never redeemed at all.
            await loop.run_in_executor(
                None,
                lambda: oauth.get_access_token(code, as_dict=False, check_cache=False),
            )
            token = oauth.cache_handler.get_cached_token()
        except (SpotifyOauthError, requests.exceptions.RequestException, OSError) as e:
            logger.error("Spotify token exchange failed: %s: %s", type(e).__name__, e)
            await self.__reply_result(writer, False, f"Tunnistautuminen epäonnistui: {e}")
            return
        finally:
            # Single-use either way: a spent code must never be retried, and the
            # listener has done its job.
            await self.__cancel_pending()

        # An exchange that returned cleanly can still have left nothing on disk:
        # spotipy's cache handler swallows write errors. The code is spent by now,
        # so verify rather than assume — otherwise the popup shows a tick while the
        # status broadcast a few lines below reports no grant at all.
        if not token or "refresh_token" not in token:
            logger.error(
                "Spotify token exchange succeeded but the cache was not written: %s",
                self.__config.spotify_cache_path,
            )
            await self.__reply_result(
                writer,
                False,
                "Tunnus vaihdettiin mutta sitä ei voitu tallentaa: "
                f"{self.__config.spotify_cache_path}",
            )
            await self.__server.broadcast(self.__status_frame())
            return

        scope = (token or {}).get("scope", "")
        expires_at = (token or {}).get("expires_at")
        # Never log the code or the token itself.
        logger.info("Spotify re-authorized | scope=%s expires_at=%s", scope, expires_at)

        try:
            await self.__media_manager.refresh_spotify_auth()
        except Exception as e:
            # A failing refresh must not turn a successful grant into a reported
            # failure — the grant is already on disk and the next poll will use it.
            logger.warning("Spotify grant saved, but the player refresh failed: %s", e)

        await self.__reply_result(writer, True, "Tunnistautuminen onnistui",
                                  scope=scope, expires_at=expires_at)
        await self.__server.broadcast(self.__status_frame())

    async def notify_auth_state_changed(self) -> None:
        '''
        Re-broadcasts the grant status to every client.  Registered with the Spotify
        player, which calls it the moment Spotify rejects or re-accepts the grant —
        so the dashboard's prompt appears then, not at the next reconnect.
        '''
        await self.__server.broadcast(self.__status_frame())

    async def stream_everything(self, writer) -> None:
        '''
        Snapshots the current grant state to a newly connected client, so the
        Options view can say whether Spotify is authorized without asking.
        Arguments:
            writer (StreamWriter): The newly connected client.
        '''
        await self.__server.send_to(writer, self.__status_frame())

    # ── Status ────────────────────────────────────────────────────

    def build_status(self) -> dict:
        '''
        Reads the cached grant and reports whether it is usable.  Deliberately
        does no network work: this is sent on every client connect, and
        spotipy's validate_token() would refresh over the wire.
        '''
        status = {
            "authorized": False,
            # True only when a NEW AUTHORIZATION is the fix. The frontend raises its
            # re-auth prompt on this, so a broken config (which re-authorizing
            # cannot repair) must leave it false.
            "needsReauth": False,
            "scope": "",
            "expiresAt": None,
            "redirectUri": self.__config.spotify_redirect_uri,
            "cachePath": self.__config.spotify_cache_path,
            "reason": "",
        }

        # The player's verdict outranks the file's existence: a cached refresh
        # token that Spotify has stopped accepting still sits happily on disk, and
        # since the 6-month refresh-token expiry that is a scheduled certainty.
        # Only the player has actually tried to use it.
        player_error = self.__media_manager.spotify_auth_error()
        if player_error:
            status["reason"] = player_error
            status["needsReauth"] = True
            return status

        try:
            oauth = build_oauth(self.__config)
            token = oauth.cache_handler.get_cached_token()
        except Exception as e:
            # A config the backend cannot read is not something re-authorizing fixes.
            status["reason"] = f"Tunnusta ei voitu lukea: {e}"
            return status

        if not token or "refresh_token" not in token:
            status["reason"] = "Ei tallennettua tunnusta"
            status["needsReauth"] = True
            return status

        status["scope"] = token.get("scope", "")
        # NOTE: this is the ACCESS token's expiry — always within the next hour,
        # and refreshed silently long before the user could notice. It is NOT when
        # the authorization runs out. Do not render it as one: it would imply the
        # grant dies within the hour (it does not) while hiding the only expiry
        # that ever needs the user, the refresh token's 6 months. Spotify does not
        # expose the grant's issue date, so showing a real "valid until" would mean
        # recording our own timestamp at each successful exchange.
        status["expiresAt"] = token.get("expires_at")
        if not scope_covers(SPOTIFY_SCOPE, status["scope"]):
            status["reason"] = "Tunnuksen oikeudet eivät riitä"
            status["needsReauth"] = True
            return status

        status["authorized"] = True
        status["reason"] = "Tunnus löytyi"
        return status

    # ── Internals ─────────────────────────────────────────────────

    def __json_frame(self, msg_type: int, status: int, body: bytes) -> bytes:
        '''
        Frames a status-prefixed JSON body, the shape the CONFIG_* codes use.
        Arguments:
            msg_type (int): Message-type byte.
            status (int): SPOTIFY_AUTH_OK or SPOTIFY_AUTH_ERROR.
            body (bytes): UTF-8 JSON payload.
        '''
        return protocol.frame(
            msg_type, bytes((status,)) + struct.pack("!I", len(body)) + body
        )

    def __status_frame(self) -> bytes:
        '''Builds a SPOTIFY_AUTH_STATUS packet from the cached grant.'''
        body = json.dumps(self.build_status(), ensure_ascii=False).encode("utf-8")
        return self.__json_frame(
            protocol.SPOTIFY_AUTH_STATUS, protocol.SPOTIFY_AUTH_OK, body
        )

    async def __reply_url_error(self, writer, message: str) -> None:
        '''Replies to a failed SPOTIFY_AUTH_GET_URL.'''
        body = json.dumps({"message": message}, ensure_ascii=False).encode("utf-8")
        await self.__server.send_to(
            writer,
            self.__json_frame(protocol.SPOTIFY_AUTH_URL, protocol.SPOTIFY_AUTH_ERROR, body),
        )

    async def __reply_result(self, writer, ok: bool, message: str,
                             scope: str = "", expires_at=None) -> None:
        '''
        Replies to a SPOTIFY_AUTH_CODE exchange.
        Arguments:
            writer (StreamWriter): The requesting client.
            ok (bool): Whether the exchange succeeded.
            message (str): Finnish message shown to the user verbatim.
            scope (str): Granted scope on success.
            expires_at: Token expiry (epoch seconds) on success.
        '''
        body = json.dumps(
            {"ok": ok, "message": message, "scope": scope, "expiresAt": expires_at},
            ensure_ascii=False,
        ).encode("utf-8")
        await self.__server.send_to(
            writer,
            self.__json_frame(
                protocol.SPOTIFY_AUTH_RESULT,
                protocol.SPOTIFY_AUTH_OK if ok else protocol.SPOTIFY_AUTH_ERROR,
                body,
            ),
        )
