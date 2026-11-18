'''
Installs releases from GitHub's Releases page: the backend half of the Options view's "Päivitys"
card (#56). backend/src/update_service/CLAUDE.md has the load-bearing details.

A device runs an installed release from <root>/releases/<tag> (utils/version), where <root> also
holds the "current" link the systemd units start, the guard (guard.py) and the switch marker. To
move to another release this service downloads its assets, checks the signature over SHA256SUMS
against the key the running release carries (release_signers) and every asset against SHA256SUMS,
unpacks the release beside the running one, builds its venv, snapshots the state files under the
version being left, points "current" at it and restarts both halves. The new backend confirms the
health gate once the display on this device has logged in to it; until then the guard rolls a
crash loop or a timeout back to the release before.

A development machine runs from a git checkout instead: the card shows its commit and nothing is
downloaded or switched.

Why UPDATE_STATE is a broadcast: an install replaces what every display on this backend talks to,
so each one must see it happening rather than be free to start its own. The state document is also
the progress channel — a run in flight is its "job" object — so a display that connects mid-update
sees the whole picture in its on-connect snapshot.

Nothing a client sends reaches a shell: every command is an argv list, and the one thing a request
names, the tag, must match _TAG and be a release this service listed itself.
'''

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import platform
import re
import shutil
import signal
import tarfile
import tempfile
import time
from collections import deque
from pathlib import Path

import aiohttp

from . import guard
from ..auth_service.auth_service import STORE_FILE, TLS_DIR
from ..utils import process, protocol, version
from ..utils.atomic_write import write_atomic
from ..utils.env_file import app_config_dir

logger = logging.getLogger("update_service")

# Where releases come from. Constants rather than settings: they are this project's, not a
# deployment's.
REPOSITORY = "einioville/Tesla-Homedash"
_API = f"https://api.github.com/repos/{REPOSITORY}/releases?per_page=30"
# A generic client name: GitHub wants one, and it says nothing about the device.
_USER_AGENT = "Tesla-Homedash-updater"

SIGN_NAMESPACE = "tesla-homedash-release"
SIGN_IDENTITY = "release@tesla-homedash"
_SIGNERS = Path(__file__).with_name("release_signers")
_GUARD = Path(__file__).with_name("guard.py")
# The interpreter the guard runs under (install.sh's ExecStartPre): the system's, so a broken
# release's venv cannot take its way back with it.
_SYSTEM_PYTHON = "/usr/bin/python3"

BACKEND_UNIT = "tesla-homedash-backend.service"
FRONTEND_UNIT = "tesla-homedash-frontend.service"

# A release tag: v2.0.0, or v2.1.0-rc1 for a pre-release.
_TAG = re.compile(r"\Av(\d+)\.(\d+)\.(\d+)(?:-rc(\d+))?\Z")
_SUMS_LINE = re.compile(r"\A([0-9a-f]{64})  (\S+)\Z")
# What a release must carry to be installable here; one without them predates this updater
# (v1.0.0), and moving a keyboard-less panel onto it would leave no way back but SSH.
_REQUIRED_ASSETS = ("manifest.json", "SHA256SUMS", "SHA256SUMS.sig")

# The frontend's own state files, at its default location (frontend_v2/CLAUDE.md): the display on
# this device is started by install.sh's unit, which sets no override.
_FRONTEND_STATE_FILES = ("frontend_config.json", "frontend_credentials.json")

_LIST_TIMEOUT = 30.0
_SMALL_TIMEOUT = 30.0
_SMALL_LIMIT = 1_000_000
_DOWNLOAD_TIMEOUT = 1800.0
_DEPS_TIMEOUT = 1800.0       # uv sync can compile wheels on ARM
_SYSTEMCTL_TIMEOUT = 30.0
_VERIFY_TIMEOUT = 20.0

# The releases are listed this long after start, then this often. GitHub allows 60 unauthenticated
# API calls an hour, and an unchanged list (ETag) costs none of them.
_FIRST_CHECK_DELAY = 60.0
_CHECK_INTERVAL = 6 * 3600.0
# A card opened again within this long reuses the last list.
_FETCH_MIN_INTERVAL = 120.0
# Notes are a release's own text; capped so the state document stays small at 2 Hz.
_NOTES_CHARS = 4000
_LIST_LENGTH = 20

# How long a new release has to prove healthy (the guard rolls it back after).
HEALTH_GATE_S = 300
# Between the last broadcast and the restart that ends this process.
_RESTART_GRACE = 1.5

# A download, the unpacked release and its venv: about 70 MB, 170 MB and 300 MB.
_MIN_FREE_BYTES = 1_000_000_000

_BROADCAST_MIN_INTERVAL = 0.5
_LOG_LINES = 80
_LOG_LINE_CHARS = 240
# Longest run of bytes without a newline before it is flushed as one line (__pump says why).
_MAX_LINE_BYTES = 8192

# Removed from every child's environment: a venv or project setting inherited from this process
# would point uv at the running release's venv instead of the new one's.
_SCRUBBED = ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "PYTHONHOME", "PYTHONPATH")
_UV_ENV = {"UV_NO_PROGRESS": "1", "TERM": "dumb"}

_STEP_DOWNLOAD = "download"
_STEP_UNPACK = "unpack"
_STEP_DEPS = "deps"
_STEP_SNAPSHOT = "snapshot"
_STEP_SWITCH = "switch"
_STEPS = (
    (_STEP_DOWNLOAD, "Ladataan"),
    (_STEP_UNPACK, "Puretaan"),
    (_STEP_DEPS, "Asennetaan riippuvuudet"),
    (_STEP_SNAPSHOT, "Tallennetaan asetukset"),
    (_STEP_SWITCH, "Vaihdetaan versio"),
)
# Nothing before the switch touches the running release, so stopping there loses nothing; the
# switch itself is a few renames that must not stop halfway.
_CANCELLABLE_STEPS = (_STEP_DOWNLOAD, _STEP_UNPACK, _STEP_DEPS)

# Longest a run could legitimately take, used only to stand the restart veto down: a device that
# cannot be restarted is worse than one restarted mid-nothing.
_JOB_SANITY_MS = int((_DOWNLOAD_TIMEOUT * 2 + _DEPS_TIMEOUT + 600.0) * 1000)


class _Refusal(Exception):
    '''Why a release cannot be installed, in the Finnish the card shows.'''


class _Cancelled(Exception):
    '''A cancel reached a step running in a worker thread.'''


def _version_key(tag: str) -> tuple | None:
    '''
    Orders release tags: by number, and a pre-release before the release it leads to.
    Arguments:
        tag (str): A tag such as v2.1.0 or v2.1.0-rc1.
    '''
    match = _TAG.match(tag or "")
    if match is None:
        return None
    major, minor, patch, rc = match.groups()
    return (int(major), int(minor), int(patch), int(rc) if rc else 10**9)


def _numbers(text: str) -> tuple:
    '''
    A dotted version as a tuple of ints, for comparing (2.38 < 2.41).
    Arguments:
        text (str): "2.38".
    '''
    return tuple(int(part) for part in str(text).split(".") if part.isdigit())


def _which(command: str) -> str | None:
    '''
    Finds a command on PATH or in ~/.local/bin, where uv installs itself and which a systemd
    user unit's PATH may lack.
    Arguments:
        command (str): The command's name.
    '''
    path = os.environ.get("PATH", "") + os.pathsep + str(Path.home() / ".local" / "bin")
    return shutil.which(command, path=path)


def _parse_sums(text: str) -> dict[str, str]:
    '''
    Reads SHA256SUMS (sha256sum's format) into {file name: hex digest}.
    Arguments:
        text (str): The file's text.
    '''
    sums = {}
    for line in text.splitlines():
        match = _SUMS_LINE.match(line.strip())
        if match:
            sums[match.group(2)] = match.group(1)
    return sums


def _is_local(address: str) -> bool:
    '''
    Whether a connection came from this device itself.
    Arguments:
        address (str): The client's IP address.
    '''
    return address in ("127.0.0.1", "::1") or address.startswith("::ffff:127.")


class UpdateService:
    '''
    Serves UPDATE_GET_STATE / UPDATE_APPLY / UPDATE_CANCEL and broadcasts UPDATE_STATE.

    Registered with Server.register_service, so every connecting display gets the last known
    state without asking — including a run already in progress.

    Arguments:
        server (Server): TLS server used to broadcast and to reply.
        config_service (ConfigService): Given a veto, so the Options view's restart buttons
            cannot interrupt a run, and its restart as the fallback when systemd cannot restart
            the unit.
        config (Config): For the config file's path, the first of the state files a switch
            snapshots.
    '''

    def __init__(self, server, config_service, config):
        self.__server = server
        self.__config_service = config_service
        self.__config = config

        self.__root = version.install_root()
        self.__version = version.app_version()
        self.__commit = version.commit()
        self.__reason = "" if self.__root is not None else (
            "Kehitysversio: tämä laite ajaa git-työhakemistoa, joka päivitetään gitillä")
        # install.sh writes the dashboard's unit only on a device with its own panel.
        unit_dir = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "systemd" / "user"
        self.__local_display = (unit_dir / FRONTEND_UNIT).is_file()

        self.__releases: list[dict] = []
        self.__assets: dict[str, dict] = {}
        self.__verified: dict[str, tuple] = {}
        self.__checked_ms: int | None = None
        self.__check_error = ""
        # Throttling keys on the ATTEMPT: keyed on success, an unreachable GitHub would never be
        # throttled and every card open would pay the full timeout again.
        self.__last_check_attempt: float | None = None
        self.__etag = ""
        self.__raw_releases: list = []
        self.__session: aiohttp.ClientSession | None = None

        self.__health: dict | None = None
        self.__last_switch: dict | None = None
        self.__rollback: dict | None = None
        self.__load_records()

        self.__job: dict | None = None
        self.__job_seq = 0
        self.__job_assets: list[str] = []
        self.__log: deque[str] = deque(maxlen=_LOG_LINES)
        self.__proc: asyncio.subprocess.Process | None = None
        self.__task: asyncio.Task | None = None
        self.__cancelled = False
        # Set by handle_apply before its first await, while self.__job does not exist yet.
        self.__starting = False
        self.__last_broadcast = 0.0
        # One listing at a time: two cards opening together share it.
        self.__lock = asyncio.Lock()

        config_service.register_restart_veto("update", self.__veto_restart)

    # ── Records beside the releases ───────────────────────────────

    def __load_records(self) -> None:
        '''
        Reads what the last switch left: the open health gate (switch.json, when it is this
        release's), a rollback the guard made and the last switch confirmed.
        '''
        if self.__root is None:
            return
        marker = self.__read_json(self.__root / "switch.json")
        if marker and marker.get("to") == self.__version:
            self.__health = {key: marker.get(key) for key in
                             ("from", "to", "deadline", "localDisplay", "restoredSnapshot")}
        self.__rollback = self.__read_json(self.__root / "rollback.json")
        self.__last_switch = self.__read_json(self.__root / "last-switch.json")

    @staticmethod
    def __read_json(path: Path) -> dict | None:
        '''
        One small JSON record; None when it is missing or unreadable.
        Arguments:
            path (Path): The file.
        '''
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    # ── Gates ─────────────────────────────────────────────────────

    def __run_in_flight(self) -> bool:
        '''Whether a run is live, or claimed by a handle_apply that has not started one yet.'''
        if self.__starting:
            return True
        return self.__job is not None and not self.__job.get("finished")

    def __veto_restart(self) -> str:
        '''
        Refuses a CONFIG_RESTART while a run is in flight; empty string means no objection.
        Bounded by _JOB_SANITY_MS, so a wedged job cannot leave a device that never restarts.
        '''
        if not self.__run_in_flight():
            return ""
        started = (self.__job or {}).get("startedMs") or 0
        if started and (time.time() * 1000 - started) > _JOB_SANITY_MS:
            logger.warning("Restart veto stood down: job %s has run past its deadline",
                           (self.__job or {}).get("id"))
            return ""
        return "Päivitys on kesken — uudelleenkäynnistys keskeyttäisi sen"

    # ── Protocol handlers ─────────────────────────────────────────

    async def handle_get_state(self, payload: bytes, writer) -> None:
        '''
        UPDATE_GET_STATE handler: lists the releases again when asked (throttled), then replies
        with the state to the requesting client.
        Arguments:
            payload (bytes): len(4B) + UTF-8 JSON {"fetch": <bool>}.
            writer (StreamWriter): The requesting client.
        '''
        body = self.__decode_json(payload, "UPDATE_GET_STATE") or {}
        if body.get("fetch") and not self.__run_in_flight():
            await self.__check(force=False)
        await self.__server.send_to(writer, self.__state_frame())

    async def handle_apply(self, payload: bytes, _writer) -> None:
        '''
        UPDATE_APPLY handler: validates the request and starts the run. A refusal is broadcast
        as a finished, failed job, so every display learns why nothing happened.
        Arguments:
            payload (bytes): len(4B) + UTF-8 JSON {"tag": "v2.1.0"}.
            _writer (StreamWriter): Unused — the answer is a broadcast.
        '''
        # Claimed before any await: the server runs each packet as its own task, and two applies
        # inside the listing below would otherwise both pass a test that only read __job.
        if self.__run_in_flight():
            await self.__refuse("Päivitys on jo käynnissä")
            return
        self.__starting = True
        try:
            await self.__start(payload)
        finally:
            self.__starting = False

    async def __start(self, payload: bytes) -> None:
        '''
        Validates one apply request and launches the run.
        Arguments:
            payload (bytes): The raw UPDATE_APPLY body.
        '''
        body = self.__decode_json(payload, "UPDATE_APPLY")
        if body is None:
            await self.__refuse("Virheellinen päivityspyyntö")
            return
        # Truncated before it can reach a message every later state frame repeats.
        tag = str(body.get("tag", ""))[:40]
        if self.__root is None:
            await self.__refuse(self.__reason)
            return
        if _version_key(tag) is None:
            await self.__refuse("Virheellinen versio")
            return

        await self.__check(force=False)
        entry = next((e for e in self.__releases if e["tag"] == tag), None)
        if entry is None:
            await self.__refuse(f"Versiota {tag} ei löytynyt julkaisuista")
            return
        if entry["direction"] == "current":
            await self.__refuse("Tämä versio on jo käytössä")
            return
        if not entry["installable"]:
            await self.__refuse(entry["reason"] or "Tätä versiota ei voi asentaa")
            return
        blocker = await self.__preflight()
        if blocker:
            await self.__refuse(blocker)
            return

        # self.__job is set before the task exists, so one of the two fences always holds.
        self.__cancelled = False
        self.__log.clear()
        self.__job = self.__new_job(entry)
        self.__task = asyncio.create_task(self.__run_job(entry))
        # The loop holds only a weak reference to a task.
        self.__task.add_done_callback(self.__on_job_done)

    async def handle_cancel(self, _payload: bytes, _writer) -> None:
        '''
        UPDATE_CANCEL handler: stops a run during a step before the switch (job.cancellable).
        Arguments:
            _payload (bytes): Unused; the command carries no body.
            _writer (StreamWriter): Unused.
        '''
        if self.__job is None or self.__job.get("finished"):
            return
        if not self.__job.get("cancellable", False):
            logger.info("Cancel refused during the %s step", self.__job.get("stepId"))
            return
        logger.warning("Update cancelled by a client")
        self.__cancelled = True
        self.__append_log("Peruutetaan…")
        self.__kill_process()

    async def stream_everything(self, writer) -> None:
        '''
        On-connect snapshot: the last known state, including a run in progress. Lists nothing:
        a connect burst must stay cheap, and the card asks for a fresh list when it opens.
        Arguments:
            writer (StreamWriter): The newly connected client.
        '''
        await self.__server.send_to(writer, self.__state_frame())

    def on_display_login(self, _display: dict, address: str) -> None:
        '''
        AuthService's login listener: the display on this device logging in to the new release
        is what closes its health gate.
        Arguments:
            _display (dict): The display that logged in.
            address (str): Its IP address.
        '''
        if self.__health is not None and _is_local(address):
            asyncio.get_running_loop().create_task(self.__confirm())

    def version_label(self) -> str | None:
        '''What this backend runs — the release, or a checkout's commit — for the Palvelin card.'''
        return self.__version or None

    # ── Run task ──────────────────────────────────────────────────

    async def run(self) -> None:
        '''
        Closes a health gate that needs no display, then lists the releases shortly after start
        and every _CHECK_INTERVAL, broadcasting each list so a new release shows its notice.
        '''
        await self.__broadcast(force=True)
        if self.__root is None:
            return
        if self.__health is not None and not self.__health.get("localDisplay"):
            await self.__confirm()
        await asyncio.sleep(_FIRST_CHECK_DELAY)
        while True:
            try:
                if not self.__run_in_flight():
                    await self.__check(force=True)
                    await self.__broadcast(force=True)
            except Exception as e:  # noqa: BLE001 - one bad check must not end the loop
                logger.error("Release check failed: %s", e)
            await asyncio.sleep(_CHECK_INTERVAL)

    def get_run_task(self):
        '''Returns the run task for start_services to gather.'''
        return asyncio.create_task(self.run())

    # ── The health gate ───────────────────────────────────────────

    async def __confirm(self) -> None:
        '''
        This release is healthy: removes the switch marker and its timer, installs this
        release's guard beside the releases, records the switch and removes every release but
        this one and the one before it.
        '''
        health, self.__health = self.__health, None
        if health is None or self.__root is None:
            return
        root = self.__root
        (root / "switch.json").unlink(missing_ok=True)
        await self.__systemctl("stop", f"{guard.TIMER}.timer")
        try:
            write_atomic(str(root / "guard.py"), _GUARD.read_text(encoding="utf-8"), 0o755)
        except OSError as e:
            logger.warning("Could not install the guard: %s", e)
        self.__last_switch = {"from": health.get("from"), "to": health.get("to"),
                              "atMs": int(time.time() * 1000)}
        self.__rollback = None
        try:
            write_atomic(str(root / "last-switch.json"), json.dumps(self.__last_switch))
            (root / "rollback.json").unlink(missing_ok=True)
        except OSError as e:
            logger.warning("Could not record the switch: %s", e)
        await asyncio.to_thread(self.__prune, {self.__version, str(health.get("from") or "")})
        logger.warning("Release %s confirmed healthy (from %s)", health.get("to"), health.get("from"))
        await self.__broadcast(force=True)

    def __prune(self, keep: set[str]) -> None:
        '''
        Removes the release folders not in keep, and every download.
        Arguments:
            keep (set[str]): The tags to keep: the running release and the one before it.
        '''
        assert self.__root is not None
        for folder in (self.__root / "releases").iterdir():
            if folder.is_dir() and folder.name not in keep:
                shutil.rmtree(folder, ignore_errors=True)
                logger.info("Removed release %s", folder.name)
        shutil.rmtree(self.__root / "downloads", ignore_errors=True)

    # ── Listing ───────────────────────────────────────────────────

    async def __check(self, force: bool) -> None:
        '''
        Lists the releases from GitHub and decides for each whether it can be installed here.
        A failure keeps the last list and says so (checkError).
        Arguments:
            force (bool): Skip the _FETCH_MIN_INTERVAL throttle (the periodic check).
        '''
        if self.__root is None:
            return
        if (not force and self.__last_check_attempt is not None
                and time.monotonic() - self.__last_check_attempt < _FETCH_MIN_INTERVAL):
            return
        async with self.__lock:
            self.__last_check_attempt = time.monotonic()
            try:
                raw = await self.__fetch_list()
            except asyncio.TimeoutError:
                self.__check_error = "GitHub ei vastannut"
                logger.warning("Release list timed out")
                return
            except (aiohttp.ClientError, ValueError) as e:
                self.__check_error = "Julkaisuja ei voitu hakea GitHubista"
                logger.warning("Release list failed: %s", e)
                return
            entries = []
            for release in raw:
                if not isinstance(release, dict) or release.get("draft"):
                    continue
                tag = str(release.get("tag_name", ""))
                if _version_key(tag) is not None:
                    entries.append(await self.__describe(release, tag))
            entries.sort(key=lambda e: _version_key(e["tag"]) or (), reverse=True)
            self.__releases = entries[:_LIST_LENGTH]
            self.__check_error = ""
            self.__checked_ms = int(time.time() * 1000)

    async def __http(self) -> aiohttp.ClientSession:
        '''The shared HTTP session, made on first use (it needs the running loop).'''
        if self.__session is None or self.__session.closed:
            self.__session = aiohttp.ClientSession(
                headers={"User-Agent": _USER_AGENT},
                timeout=aiohttp.ClientTimeout(total=None, sock_connect=15, sock_read=60))
        return self.__session

    async def __fetch_list(self) -> list:
        '''
        GitHub's release list, newest first. An unchanged list answers 304 to the ETag, which
        GitHub does not count against the hourly limit.
        '''
        session = await self.__http()
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.__etag:
            headers["If-None-Match"] = self.__etag

        async def fetch() -> list:
            async with session.get(_API, headers=headers) as response:
                if response.status == 304:
                    return self.__raw_releases
                response.raise_for_status()
                data = await response.json(content_type=None)
                self.__raw_releases = data if isinstance(data, list) else []
                self.__etag = response.headers.get("ETag", "")
                return self.__raw_releases

        return await asyncio.wait_for(fetch(), _LIST_TIMEOUT)

    async def __get_small(self, url: str) -> bytes:
        '''
        Downloads one small asset (the manifest, the checksums, the signature) into memory.
        Arguments:
            url (str): Its browser_download_url.
        '''
        session = await self.__http()

        async def fetch() -> bytes:
            async with session.get(url) as response:
                response.raise_for_status()
                data = await response.content.read(_SMALL_LIMIT + 1)
                if len(data) > _SMALL_LIMIT:
                    raise ValueError(f"{url} is larger than {_SMALL_LIMIT} bytes")
                return data

        return await asyncio.wait_for(fetch(), _SMALL_TIMEOUT)

    async def __describe(self, release: dict, tag: str) -> dict:
        '''
        One release as the card shows it, with whether and why not it can be installed here.
        Arguments:
            release (dict): The release from GitHub's list.
            tag (str): Its tag, already checked against _TAG.
        '''
        assets = {a.get("name"): a for a in release.get("assets", []) if isinstance(a, dict)}
        self.__assets[tag] = assets
        current = _version_key(self.__version)
        direction = ("current" if tag == self.__version
                     else "update" if current is None or (_version_key(tag) or ()) > current
                     else "downgrade")
        entry = {
            "tag": tag,
            "name": str(release.get("name") or tag)[:120],
            "notes": str(release.get("body") or "")[:_NOTES_CHARS],
            "publishedAt": release.get("published_at") or "",
            "prerelease": bool(release.get("prerelease")),
            "direction": direction,
            "installable": False,
            "reason": "",
            "size": 0,
            "snapshot": (self.__root / "snapshots" / tag / "snapshot.json").is_file()
            if self.__root else False,
        }
        try:
            if any(name not in assets for name in _REQUIRED_ASSETS):
                raise _Refusal("Julkaisussa ei ole päivitystoimintoa, joten sitä ei voi asentaa "
                               "näytöltä")
            manifest, _sums = await self.__verified_manifest(tag, assets)
            names = self.__bundle_names(manifest)
            if any(name not in assets for name in names):
                raise _Refusal("Julkaisusta puuttuu tiedostoja")
            entry["size"] = sum(int(assets[name].get("size") or 0) for name in names)
            missing = self.__missing(manifest)
            if missing:
                raise _Refusal("Vaatii: " + ", ".join(missing))
            entry["installable"] = direction != "current"
        except _Refusal as e:
            entry["reason"] = str(e)
        except asyncio.TimeoutError:
            entry["reason"] = "Julkaisun tietoja ei saatu ladattua"
        except (aiohttp.ClientError, ValueError, KeyError, TypeError) as e:
            entry["reason"] = "Julkaisun tietoja ei voitu tarkistaa"
            logger.warning("Release %s could not be checked: %s", tag, e)
        return entry

    def __bundle_names(self, manifest: dict) -> list[str]:
        '''
        The bundles this device needs from a release: the backend, and the frontend when the
        dashboard runs here too.
        Arguments:
            manifest (dict): The release's verified manifest.
        '''
        assets = manifest["assets"]
        return [str(assets["backend"])] + ([str(assets["frontend"])] if self.__local_display else [])

    async def __verified_manifest(self, tag: str, assets: dict) -> tuple[dict, dict]:
        '''
        A release's manifest and checksums, once the signature over the checksums has verified
        and the manifest matches them. Kept per tag until its assets change.
        Arguments:
            tag (str): The release.
            assets (dict): Its assets by name.
        '''
        key = tuple((assets[n].get("id"), assets[n].get("updated_at")) for n in _REQUIRED_ASSETS)
        cached = self.__verified.get(tag)
        if cached is not None and cached[0] == key:
            return cached[1], cached[2]
        sums_bytes = await self.__get_small(assets["SHA256SUMS"]["browser_download_url"])
        signature = await self.__get_small(assets["SHA256SUMS.sig"]["browser_download_url"])
        manifest_bytes = await self.__get_small(assets["manifest.json"]["browser_download_url"])
        sums = await self.__check_signature(sums_bytes, signature)
        manifest = self.__check_manifest(tag, manifest_bytes, sums)
        self.__verified[tag] = (key, manifest, sums)
        return manifest, sums

    @staticmethod
    def __check_manifest(tag: str, manifest_bytes: bytes, sums: dict) -> dict:
        '''
        Parses a manifest the checksums vouch for.
        Arguments:
            tag (str): The release it must name.
            manifest_bytes (bytes): manifest.json as downloaded.
            sums (dict): The verified checksums.
        '''
        if hashlib.sha256(manifest_bytes).hexdigest() != sums.get("manifest.json"):
            raise _Refusal("Julkaisun tiedot eivät täsmää sen tarkistussummiin")
        manifest = json.loads(manifest_bytes)
        if not isinstance(manifest, dict) or manifest.get("version") != tag:
            raise _Refusal("Julkaisun tiedot kuuluvat toiselle versiolle")
        return manifest

    async def __check_signature(self, sums_bytes: bytes, signature: bytes) -> dict:
        '''
        Checks the signature over SHA256SUMS against the key this release carries, and parses
        the checksums once it holds.
        Arguments:
            sums_bytes (bytes): SHA256SUMS.
            signature (bytes): SHA256SUMS.sig.
        '''
        keygen = _which("ssh-keygen")
        if keygen is None:
            raise _Refusal("ssh-keygen puuttuu, joten julkaisun allekirjoitusta ei voi tarkistaa")
        if not _SIGNERS.is_file():
            raise _Refusal("Tästä versiosta puuttuu julkaisujen allekirjoitusavain")
        with tempfile.NamedTemporaryFile(prefix="tesla-homedash-", suffix=".sig") as sig_file:
            sig_file.write(signature)
            sig_file.flush()
            try:
                code, out, err = await process.run(
                    (keygen, "-Y", "verify", "-f", str(_SIGNERS), "-I", SIGN_IDENTITY,
                     "-n", SIGN_NAMESPACE, "-s", sig_file.name), _VERIFY_TIMEOUT, stdin=sums_bytes)
            except asyncio.TimeoutError:
                raise _Refusal("Allekirjoituksen tarkistus ei valmistunut") from None
        if code != 0:
            logger.warning("Release signature did not verify: %s", (err or out).strip()[:200])
            raise _Refusal("Julkaisun allekirjoitus ei kelpaa")
        return _parse_sums(sums_bytes.decode("utf-8", "replace"))

    def __missing(self, manifest: dict) -> list[str]:
        '''
        What this device lacks of a release's requirements, as the card names it.
        Arguments:
            manifest (dict): The release's verified manifest.
        '''
        requires = manifest.get("requires") or {}
        missing = []
        if self.__local_display:
            arch = requires.get("arch")
            if arch and platform.machine() != arch:
                missing.append(f"{arch}-suoritin")
            glibc = requires.get("glibc")
            if glibc and _numbers(platform.libc_ver()[1]) < _numbers(glibc):
                missing.append(f"glibc {glibc}")
        commands = list(requires.get("commands") or [])
        if self.__local_display:
            commands += list(requires.get("displayCommands") or [])
        missing += [str(c) for c in commands if _which(str(c)) is None]
        # .env is loaded into the environment by then (config_parser.get_env).
        missing += [f".env: {name}" for name in requires.get("env") or [] if not os.environ.get(name)]
        return missing

    async def __preflight(self) -> str:
        '''What stops a run from starting on this device, in the card's words; empty for nothing.'''
        assert self.__root is not None
        if _which("uv") is None:
            return "uv puuttuu, joten riippuvuuksia ei voi asentaa"
        try:
            free = shutil.disk_usage(self.__root).free
        except OSError:
            free = None
        if free is not None and free < _MIN_FREE_BYTES:
            return "Levytilaa on liian vähän päivitykseen"
        if not await self.__systemctl("is-active", "--quiet", BACKEND_UNIT):
            return "Palvelinta ei ajeta systemd-palveluna, joten päivitys ei voi käynnistää sitä uudelleen"
        return ""

    # ── The run ───────────────────────────────────────────────────

    def __new_job(self, entry: dict) -> dict:
        '''
        Builds the job document for one run. Synchronous on purpose: it is what holds the slot
        between handle_apply returning and the run task first being scheduled.
        Arguments:
            entry (dict): The listed release being installed.
        '''
        self.__job_seq += 1
        return {
            "id": self.__job_seq,
            "running": True,
            "finished": False,
            "ok": None,
            "cancellable": False,
            "stepId": "",
            "stepIndex": 0,
            "tag": entry["tag"],
            "from": self.__version,
            "direction": entry["direction"],
            "restoresSnapshot": entry["direction"] == "downgrade" and entry["snapshot"],
            "startedMs": int(time.time() * 1000),
            "finishedMs": None,
            "message": "",
            "progress": None,
            "steps": [{"id": sid, "label": label, "state": "pending"} for sid, label in _STEPS],
            "log": [],
        }

    async def __run_job(self, entry: dict) -> None:
        '''
        Executes the whole install, closing the job out whatever happens: every gate in the
        service reads "finished", and a job left open would block every later run and, through
        the veto, every restart.
        Arguments:
            entry (dict): The listed release being installed.
        '''
        try:
            await self.__run_steps(entry)
        except Exception as e:  # noqa: BLE001 - the job must never stay open
            logger.error("Update run crashed: %s", e)
            self.__append_log(f"{type(e).__name__}: {e}")
            self.__finish(False, "Päivitys keskeytyi odottamattomaan virheeseen")
            await self.__broadcast(force=True)
        finally:
            if self.__job is not None and not self.__job.get("finished"):
                self.__finish(False, "Päivitys päättyi kesken")
                await self.__broadcast(force=True)

    async def __run_steps(self, entry: dict) -> None:
        '''
        The step loop. A release folder left complete by an earlier install (the one before
        this one is kept) is switched to without downloading it again.
        Arguments:
            entry (dict): The listed release being installed.
        '''
        assert self.__root is not None
        tag = entry["tag"]
        ready = (self.__root / "releases" / tag / ".complete").is_file()
        logger.warning("Installing %s over %s (%s)", tag, self.__version, entry["direction"])
        await self.__broadcast(force=True)

        runners = {
            _STEP_DOWNLOAD: lambda: self.__run_download(tag, ready),
            _STEP_UNPACK: lambda: self.__run_unpack(tag, ready),
            _STEP_DEPS: lambda: self.__run_deps(tag, ready),
            _STEP_SNAPSHOT: lambda: self.__run_snapshot(tag),
            _STEP_SWITCH: lambda: self.__run_switch(entry),
        }
        for index, (step_id, label) in enumerate(_STEPS):
            if self.__cancelled:
                await self.__fail(index, "Päivitys peruutettiin", tag)
                return
            self.__set_step(index, "running")
            await self.__broadcast(force=True)
            try:
                ok = await runners[step_id]()
            except Exception as e:  # noqa: BLE001 - a broken step must not kill the loop
                logger.error("Update step %s crashed: %s", step_id, e)
                self.__append_log(f"{type(e).__name__}: {e}")
                ok = False
            if self.__job is not None and self.__job.get("finished"):
                return
            if self.__cancelled:
                await self.__fail(index, "Päivitys peruutettiin", tag)
                return
            if not ok:
                await self.__fail(index, f"Vaihe epäonnistui: {label}", tag)
                return
            self.__set_step(index, "done")
            await self.__broadcast(force=True)

    async def __fail(self, index: int, message: str, tag: str) -> None:
        '''
        Ends a run that did not succeed. Nothing before the switch touches the running release,
        so this only removes what the run left half-made: an incomplete release folder and the
        downloads.
        Arguments:
            index (int): The step that failed.
            message (str): Finnish summary for the card.
            tag (str): The release the run was installing.
        '''
        self.__set_step(index, "failed")
        assert self.__root is not None
        folder = self.__root / "releases" / tag
        if not (folder / ".complete").is_file():
            await asyncio.to_thread(shutil.rmtree, folder, True)
        await asyncio.to_thread(shutil.rmtree, self.__root / "downloads" / tag, True)
        self.__finish(False, message)
        await self.__broadcast(force=True)

    def __on_job_done(self, task: asyncio.Task) -> None:
        '''
        Retrieves a finished run task's exception so it is logged rather than lost.
        Arguments:
            task (Task): The completed run task.
        '''
        self.__task = None
        if not task.cancelled() and task.exception() is not None:
            logger.error("Update task failed: %s", task.exception())

    async def __run_download(self, tag: str, ready: bool) -> bool:
        '''
        Download step: the checksums, their signature and the manifest again — checked afresh
        rather than trusted from the listing — then the bundles, each against its checksum.
        Arguments:
            tag (str): The release.
            ready (bool): The release folder is already complete; only the manifest is needed.
        '''
        assert self.__root is not None
        folder = self.__root / "downloads" / tag
        await asyncio.to_thread(shutil.rmtree, folder, True)
        folder.mkdir(parents=True)
        assets = self.__assets.get(tag, {})
        sums_bytes = await self.__get_small(assets["SHA256SUMS"]["browser_download_url"])
        signature = await self.__get_small(assets["SHA256SUMS.sig"]["browser_download_url"])
        manifest_bytes = await self.__get_small(assets["manifest.json"]["browser_download_url"])
        try:
            sums = await self.__check_signature(sums_bytes, signature)
            manifest = self.__check_manifest(tag, manifest_bytes, sums)
        except _Refusal as e:
            self.__append_log(str(e))
            return False
        (folder / "manifest.json").write_bytes(manifest_bytes)
        self.__append_log("Allekirjoitus tarkistettu")
        if ready:
            self.__append_log(f"{tag} on jo tällä laitteella, sitä ei ladata uudelleen")
            return True

        self.__job_assets = self.__bundle_names(manifest)
        total = sum(int(assets[name].get("size") or 0) for name in self.__job_assets)
        assert self.__job is not None
        self.__job["progress"] = {"done": 0, "total": total}
        for name in self.__job_assets:
            if not await self.__download(assets[name]["browser_download_url"], folder / name,
                                         sums.get(name, "")):
                return False
        return True

    async def __download(self, url: str, path: Path, expected: str) -> bool:
        '''
        Streams one bundle to disk, hashing it on the way, and checks it against SHA256SUMS.
        Arguments:
            url (str): Its browser_download_url.
            path (Path): Where it goes.
            expected (str): Its hex digest from the verified SHA256SUMS.
        '''
        self.__append_log(f"Ladataan {path.name}")
        digest = hashlib.sha256()
        session = await self.__http()
        assert self.__job is not None
        progress = self.__job["progress"]
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(
                    total=_DOWNLOAD_TIMEOUT, sock_connect=15, sock_read=60)) as response:
                response.raise_for_status()
                with path.open("wb") as out:
                    async for chunk in response.content.iter_chunked(65536):
                        if self.__cancelled:
                            return False
                        out.write(chunk)
                        digest.update(chunk)
                        progress["done"] += len(chunk)
                        await self.__broadcast()
        except asyncio.TimeoutError:
            self.__append_log(f"{path.name}: lataus aikakatkaistiin")
            return False
        except (aiohttp.ClientError, OSError) as e:
            self.__append_log(f"{path.name}: {e}")
            return False
        if not expected or digest.hexdigest() != expected:
            self.__append_log(f"{path.name} ei täsmää tarkistussummaansa")
            return False
        return True

    async def __run_unpack(self, tag: str, ready: bool) -> bool:
        '''
        Unpack step: the bundles into releases/<tag>, in a worker thread. tarfile's "data"
        filter refuses links and paths that leave the folder; on top of that, nothing but
        backend/ and frontend/ may be in a bundle.
        Arguments:
            tag (str): The release.
            ready (bool): The release folder is already complete.
        '''
        if ready:
            return True
        assert self.__root is not None
        destination = self.__root / "releases" / tag
        downloads = self.__root / "downloads" / tag
        names = list(self.__job_assets)

        def unpack() -> None:
            shutil.rmtree(destination, ignore_errors=True)
            destination.mkdir(parents=True)
            for name in names:
                with tarfile.open(downloads / name, "r:gz") as archive:
                    for member in archive:
                        if self.__cancelled:
                            raise _Cancelled
                        if member.name.split("/")[0] not in ("backend", "frontend"):
                            raise ValueError(f"unexpected {member.name} in {name}")
                        archive.extract(member, destination, filter="data")
            shutil.copy2(downloads / "manifest.json", destination / "manifest.json")

        self.__append_log(f"Puretaan {destination}")
        try:
            await asyncio.to_thread(unpack)
        except _Cancelled:
            return False
        except (OSError, tarfile.TarError, ValueError) as e:
            self.__append_log(f"Purku epäonnistui: {e}")
            return False
        return True

    async def __run_deps(self, tag: str, ready: bool) -> bool:
        '''
        Dependency step: the release's own venv, from its uv.lock. --locked fails loudly on a
        lock that does not match pyproject.toml; --no-install-project skips building the backend
        as a package, which run.py does not need.
        Arguments:
            tag (str): The release.
            ready (bool): The release folder is already complete.
        '''
        if ready:
            return True
        assert self.__root is not None
        uv = _which("uv")
        if uv is None:
            self.__append_log("uv puuttuu")
            return False
        folder = self.__root / "releases" / tag
        ok = await self.__run_step_process(
            [uv, "sync", "--locked", "--no-install-project", "--no-progress"],
            cwd=folder / "backend", timeout=_DEPS_TIMEOUT, env=_UV_ENV)
        if ok:
            (folder / ".complete").touch()
        return ok

    def __state_files(self) -> list[tuple[str, Path]]:
        '''The state files a switch snapshots: the name each is saved under, and where it lives.'''
        config = Path(self.__config.path)
        frontend = Path(app_config_dir())
        return ([("config.json", config),
                 (STORE_FILE, config.parent / STORE_FILE),
                 (TLS_DIR, config.parent / TLS_DIR)]
                + [(name, frontend / name) for name in _FRONTEND_STATE_FILES])

    async def __run_snapshot(self, tag: str) -> bool:
        '''
        Snapshot step: copies the state files into snapshots/<the version being left>, replacing
        an older snapshot of it, so going back to this version later restores them (guard.py
        restores one the same way). Private (0700): it holds the certificate's key and the login.
        Arguments:
            tag (str): The release being installed, recorded in the snapshot.
        '''
        assert self.__root is not None
        if not self.__version:
            self.__append_log("Käytössä olevan version nimi puuttuu, asetuksia ei tallenneta")
            return True
        folder = self.__root / "snapshots" / self.__version
        files = self.__state_files()

        def take() -> int:
            staging = folder.with_name(folder.name + ".new")
            shutil.rmtree(staging, ignore_errors=True)
            staging.mkdir(parents=True, mode=0o700)
            saved = {}
            for name, source in files:
                if source.is_dir():
                    shutil.copytree(source, staging / name)
                elif source.is_file():
                    shutil.copy2(source, staging / name)
                else:
                    continue
                saved[name] = str(source)
            (staging / "snapshot.json").write_text(json.dumps(
                {"files": saved, "takenMs": int(time.time() * 1000), "leftFor": tag}),
                encoding="utf-8")
            shutil.rmtree(folder, ignore_errors=True)
            os.replace(staging, folder)
            return len(saved)

        try:
            count = await asyncio.to_thread(take)
        except OSError as e:
            self.__append_log(f"Asetusten tallennus epäonnistui: {e}")
            return False
        self.__append_log(f"{count} asetustiedostoa tallennettu versiolle {self.__version}")
        return True

    async def __run_switch(self, entry: dict) -> bool:
        '''
        Switch step: stops this device's dashboard, restores the target's snapshot on a
        downgrade that has one, leaves the switch marker, points "current" at the target, arms
        the guard's timer and restarts both units — which ends this process.

        The marker goes down BEFORE the link moves: a power cut between the two leaves a marker
        for a release that never ran, which the guard reads as a failed start and undoes, rather
        than a moved link with no marker and nothing watching it.
        Arguments:
            entry (dict): The listed release being installed.
        '''
        assert self.__root is not None and self.__job is not None
        root, tag = self.__root, entry["tag"]
        stopped = False
        if self.__local_display:
            if not await self.__systemctl("stop", FRONTEND_UNIT):
                self.__append_log("Näkymää ei voitu pysäyttää")
                return False
            stopped = True
        restored = False
        try:
            snapshot = root / "snapshots" / tag
            if entry["direction"] == "downgrade" and (snapshot / "snapshot.json").is_file():
                await asyncio.to_thread(guard.restore_snapshot, snapshot)
                restored = True
                self.__append_log(f"Palautettiin asetukset, jotka tallennettiin versiosta {tag}")
            guard.write_json(root / "switch.json", {
                "from": self.__version, "to": tag, "deadline": time.time() + HEALTH_GATE_S,
                "starts": 0, "restoredSnapshot": restored, "localDisplay": self.__local_display})
            guard.point_current(root, tag)
        except OSError as e:
            self.__append_log(f"Versiota ei voitu vaihtaa: {e}")
            (root / "switch.json").unlink(missing_ok=True)
            if stopped:
                await self.__systemctl("start", FRONTEND_UNIT)
            return False
        await asyncio.to_thread(guard.arm_timer, root / "guard.py", HEALTH_GATE_S, _SYSTEM_PYTHON)
        logger.warning("Switched to %s; restarting", tag)
        self.__finish(True, f"Vaihdettu versioon {tag} — käynnistetään uudelleen")
        await self.__broadcast(force=True)
        await asyncio.sleep(_RESTART_GRACE)
        units = [BACKEND_UNIT] + ([FRONTEND_UNIT] if self.__local_display else [])
        # --no-block: restarting the backend's own unit stops this process before a blocking
        # call could return.
        if not await self.__systemctl("--no-block", "restart", *units):
            self.__config_service.request_restart(force=True)
        return True

    async def __systemctl(self, *args: str) -> bool:
        '''
        One systemctl --user command; True when it exits 0.
        Arguments:
            *args (str): The command after "systemctl --user".
        '''
        try:
            code, _out, err = await process.run(("systemctl", "--user", *args), _SYSTEMCTL_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning("systemctl %s timed out", " ".join(args))
            return False
        except OSError as e:
            logger.warning("systemctl %s: %s", " ".join(args), e)
            return False
        if code != 0 and args[:1] != ("is-active",):
            logger.warning("systemctl %s exited %s: %s", " ".join(args), code, err.strip()[:200])
        return code == 0

    # ── Subprocess plumbing ───────────────────────────────────────

    async def __run_step_process(self, argv: list[str], cwd: Path, timeout: float,
                                 env: dict | None = None) -> bool:
        '''
        Runs one step's command, streaming its output into the job log. start_new_session puts
        the child in its own process group, which is what lets a cancel or a timeout stop
        everything it started: uv runs build backends that run compilers.
        Arguments:
            argv (list[str]): Command and arguments; never passed through a shell.
            cwd (Path): Working directory for the child.
            timeout (float): Seconds before the child's group is killed.
            env (dict | None): Overrides merged onto the inherited environment.
        '''
        self.__append_log("$ " + " ".join(argv))
        try:
            child = await asyncio.create_subprocess_exec(
                *argv, cwd=str(cwd), env=self.__child_env(env),
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT, start_new_session=True)
        except OSError as e:
            self.__append_log(f"Komentoa ei voitu käynnistää: {e}")
            return False

        self.__proc = child
        # A cancel between the guard and the spawn signalled nothing; honour it now.
        if self.__cancelled:
            self.__kill_process()
        try:
            await asyncio.wait_for(self.__pump(child), timeout=timeout)
            code = child.returncode if child.returncode is not None else -1
        except asyncio.TimeoutError:
            self.__append_log(f"Aikakatkaisu {int(timeout)} s jälkeen")
            self.__kill_process()
            code = await self.__reap(child)
        except BaseException:
            # CancelledError at loop teardown, or an error out of the pump: the group must not
            # outlive the step.
            self.__kill_process()
            await self.__reap(child)
            raise
        finally:
            self.__proc = None
        if code != 0:
            self.__append_log(f"Komento päättyi koodilla {code}")
        await self.__broadcast(force=True)
        return code == 0

    async def __pump(self, child) -> None:
        '''
        Turns the child's merged output into log lines, reading chunks rather than lines:
        StreamReader.readline raises past its 64 KiB buffer, which would leave the job running
        forever.
        Arguments:
            child (Process): The running child, with stdout piped.
        '''
        buffer = b""
        while True:
            chunk = await child.stdout.read(4096)
            if not chunk:
                break
            buffer = (buffer + chunk).replace(b"\r\n", b"\n").replace(b"\r", b"\n")
            while b"\n" in buffer:
                line, _, buffer = buffer.partition(b"\n")
                self.__append_log(line.decode("utf-8", "replace"))
            if len(buffer) > _MAX_LINE_BYTES:
                self.__append_log(buffer.decode("utf-8", "replace"))
                buffer = b""
            await self.__broadcast()
        if buffer:
            self.__append_log(buffer.decode("utf-8", "replace"))
        await child.wait()

    def __kill_process(self) -> None:
        '''Kills the running step's whole process group, SIGTERM first; no-op between commands.'''
        child = self.__proc
        if child is None or child.returncode is not None:
            return
        try:
            os.killpg(os.getpgid(child.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError) as e:
            logger.warning("Could not signal the update step: %s", e)

    async def __reap(self, child) -> int:
        '''
        Waits for a killed child, escalating to SIGKILL; its exit code, or -1.
        Arguments:
            child (Process): The child that was signalled.
        '''
        try:
            return await asyncio.wait_for(child.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(os.getpgid(child.pid), signal.SIGKILL)
            try:
                return await asyncio.wait_for(child.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                return -1

    @staticmethod
    def __child_env(overrides: dict | None) -> dict:
        '''
        A child's environment: this process's, less _SCRUBBED, plus the step's own.
        Arguments:
            overrides (dict | None): Step-specific variables.
        '''
        env = {k: v for k, v in os.environ.items() if k not in _SCRUBBED}
        env.update(overrides or {})
        return env

    # ── Job bookkeeping + framing ─────────────────────────────────

    def __set_step(self, index: int, state: str) -> None:
        '''
        Marks one step's state and points the job at it.
        Arguments:
            index (int): Index into _STEPS.
            state (str): "pending" | "running" | "done" | "failed".
        '''
        if self.__job is None or not 0 <= index < len(self.__job["steps"]):
            return
        step_id = _STEPS[index][0]
        self.__job["steps"][index]["state"] = state
        self.__job["stepIndex"] = index
        self.__job["stepId"] = step_id
        self.__job["cancellable"] = state == "running" and step_id in _CANCELLABLE_STEPS

    def __finish(self, ok: bool, message: str) -> None:
        '''
        Closes the job out; steps that never ran stay pending.
        Arguments:
            ok (bool): Whether the run succeeded.
            message (str): Finnish summary shown in the card.
        '''
        if self.__job is None:
            return
        self.__job.update(running=False, finished=True, cancellable=False, ok=ok, message=message,
                          finishedMs=int(time.time() * 1000))
        logger.warning("Update finished: ok=%s %s", ok, message)

    def __append_log(self, line: str) -> None:
        '''
        Adds one line to the capped job log.
        Arguments:
            line (str): Raw output line; truncated so one line cannot dominate the document.
        '''
        text = line.rstrip()
        if not text:
            return
        if len(text) > _LOG_LINE_CHARS:
            text = text[:_LOG_LINE_CHARS] + "…"
        self.__log.append(text)

    async def __refuse(self, message: str) -> None:
        '''
        Publishes a refusal as a finished, failed job, so the card explains itself the way it
        does a failure. Never over a run in flight: that would erase its progress and re-arm the
        restart buttons it vetoes.
        Arguments:
            message (str): Finnish reason, shown verbatim.
        '''
        if self.__job is not None and not self.__job.get("finished"):
            logger.warning("Update refusal suppressed (run in flight): %s", message)
            return
        logger.warning("Update refused: %s", message)
        self.__job_seq += 1
        now = int(time.time() * 1000)
        self.__job = {"id": self.__job_seq, "running": False, "finished": True, "ok": False,
                      "cancellable": False, "stepId": "", "stepIndex": 0, "tag": "", "from": "",
                      "direction": "", "restoresSnapshot": False, "startedMs": now,
                      "finishedMs": now, "message": message, "progress": None, "steps": [],
                      "log": []}
        self.__log.clear()
        await self.__broadcast(force=True)

    async def __broadcast(self, force: bool = False) -> None:
        '''
        Broadcasts the state, at most every _BROADCAST_MIN_INTERVAL unless forced.
        Arguments:
            force (bool): Send regardless — every step transition and the final result.
        '''
        now = time.monotonic()
        if not force and now - self.__last_broadcast < _BROADCAST_MIN_INTERVAL:
            return
        self.__last_broadcast = now
        await self.__server.broadcast(self.__state_frame())

    def __state_frame(self) -> bytes:
        '''Builds an UPDATE_STATE packet from the current state and job.'''
        job = None
        if self.__job is not None:
            job = dict(self.__job)
            job["log"] = list(self.__log)
        document = {
            "mode": "release" if self.__root is not None else "development",
            "available": self.__root is not None,
            "reason": self.__reason,
            "current": {"version": self.__version, "commit": self.__commit,
                        "built": version.manifest().get("built", "")},
            "localDisplay": self.__local_display,
            "releases": self.__releases,
            "checkedMs": self.__checked_ms,
            "checkError": self.__check_error,
            "health": self.__health,
            "lastSwitch": self.__last_switch,
            "rollback": self.__rollback,
            "job": job,
        }
        return protocol.json_frame(protocol.UPDATE_STATE, protocol.CONFIG_STATUS_OK, document)

    @staticmethod
    def __decode_json(payload: bytes, label: str) -> dict | None:
        '''
        Parses a len(4B) + UTF-8 JSON request body.
        Arguments:
            payload (bytes): The raw handler payload.
            label (str): Packet name, for the warning line.
        '''
        try:
            return protocol.parse_json_body(payload)
        except ValueError as e:
            logger.warning("%s: %s", label, e)
            return None
