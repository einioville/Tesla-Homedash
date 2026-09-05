'''
In-place application updates, driven from the Options view's "Päivitys" card.

The dashboard runs from a git checkout, so "update the app" is a git operation
plus everything that has to follow it: re-sync the backend's dependencies,
rebuild the frontend binary, restart both halves.  This service owns all of it,
because every step is a system call and system calls are the backend's job — the
same split display_service makes for the panel's power state.

**Two channels, one comparison.**  The frontend picks between:

  development — track ``origin/main``: whatever is on the default branch now.
  releases    — track the newest ``v*`` tag.

Both resolve to a COMMIT, and the verdict is a commit comparison rather than a
version-string compare:

  up_to_date  HEAD already is the target
  update      the target is a descendant of HEAD          (move forward)
  downgrade   the target is an ancestor of HEAD           (move back)
  switch      neither is an ancestor of the other         (different history)

That is what makes switching channels work in both directions.  Going from
development to releases usually lands on `downgrade` — the newest release is
older than the tip of main — and that is an ordinary, expected outcome here, not
an error to be special-cased.

**The trapdoor rule.**  A target that does not itself contain this service is
REFUSED, however the verdict reads.  Move a keyboard-less panel onto a commit
with no updater and the only way back is SSH; the one release tag this project
has today (v1.0.0) is exactly such a commit.  Downgrading between two versions
that both carry the feature is fine, and is the case the feature is for.

**Safety.**  A run is refused unless the working tree is clean of *tracked*
changes.  config.json and .env are gitignored, so they are never at risk; a
modified tracked file means somebody edited on-device, and a checkout that
silently discarded that would be unforgivable on a machine whose only recovery
path is a 10" touchscreen.  The requested commit is also fenced: the frontend
posts back the exact 40-hex sha it was shown, and a target that has moved since
(a fetch in between) is rejected rather than silently applied.  And anything that
fails AFTER the checkout rolls the tree back to where it started, because the
alternative — a new source tree with an old virtualenv — is a device that never
comes back from its next restart.

**Nothing user-supplied ever reaches a shell.**  Every command is an argv list,
the channel must be one of the two literals above, and the commit must match
``[0-9a-f]{40}``, so there is no ref to inject into.  Same reasoning as the
``_SAFE_ID`` guard in influxdb_handler.

**Why UPDATE_STATE is a broadcast.**  A Spotify device scan belongs to the panel
that started it; an update rewrites the installation *both* panels are running,
so the second one must see it happening rather than be free to start its own.
The state document doubles as the progress channel — a run in flight appears as
its ``job`` object — so a dashboard that connects mid-update sees the whole
picture from its on-connect snapshot instead of having missed the packets.
'''

import asyncio
import contextlib
import json
import logging
import os
import re
import shutil
import signal
import time
from collections import deque
from pathlib import Path

from ..utils import protocol

logger = logging.getLogger("update_service")

# ── Channels ──────────────────────────────────────────────────────────────────

CHANNEL_DEVELOPMENT = "development"
CHANNEL_RELEASES = "releases"
CHANNELS = (CHANNEL_DEVELOPMENT, CHANNEL_RELEASES)

# The remote and branch the development channel tracks, and the tag shape the
# releases channel considers a release. Constants rather than settings: they are
# properties of this project's git layout, not of a deployment.
REMOTE = "origin"
DEV_BRANCH = "main"
RELEASE_TAG_GLOB = "v*"

# A target commit is only ever accepted as a full object name. Anything shorter
# would be a ref this service resolves, and a ref is a string the frontend chose.
_FULL_SHA = re.compile(r"\A[0-9a-f]{40}\Z")

# Paths a candidate target must contain before this service will move onto it.
# See "the trapdoor rule" above: without these, the panel that performed the
# update no longer exists on the version it produced.
_REQUIRED_PATHS = (
    "backend/src/update_service/update_service.py",
    "frontend_v2/items/settings/UpdatePanel.qml",
)

# ── Timeouts ──────────────────────────────────────────────────────────────────
# Generous, because the Pi is slow and a cancel button exists; the point of these
# is that nothing can wedge the card forever, not that they are tight.

_QUERY_TIMEOUT = 20.0        # any single read-only git query
_FETCH_TIMEOUT = 180.0       # git fetch as an update step
# The read path's own bound. Deliberately much shorter: this one runs while the
# card waits for its reply, and a user staring at a spinner for three minutes
# because the remote is black-holed is worse than a stale answer.
_FETCH_READ_TIMEOUT = 45.0
_CHECKOUT_TIMEOUT = 180.0
_DEPS_TIMEOUT = 1800.0       # uv sync can compile wheels on ARM
_BUILD_TIMEOUT = 5400.0      # a cold Qt build on a Pi is measured in tens of minutes
_ROLLBACK_TIMEOUT = 1800.0

# A fetch this recent is reused rather than repeated, so opening the card cannot
# hammer the remote when the user taps between sections.
_FETCH_MIN_INTERVAL = 120.0

# Progress is coalesced: a build emits hundreds of lines and every one of them
# would otherwise be a whole state document to every client.
_BROADCAST_MIN_INTERVAL = 0.5

# How much build output is kept. The tail is what matters — a failure explains
# itself in its last few lines — and the whole document has to stay far below the
# protocol's 1 MB cap even at the worst line length.
_LOG_LINES = 80
_LOG_LINE_CHARS = 240

# Longest run of bytes accepted without a newline before it is flushed as one
# line. StreamReader.readline() would RAISE past its buffer limit and a deep C++
# template diagnostic really does exceed 64 KiB, so the pump reads chunks and
# splits them itself; this is the backstop for output with no newlines at all.
_MAX_LINE_BYTES = 8192

# Refuse to start a build with less headroom than this. frontend_v2/build is
# ~230 MB and a link needs room for a second copy of a 57 MB binary; running an
# SD card out of space mid-link is one of the few ways to produce an artifact
# that exists, is executable, and does not run.
_MIN_FREE_BYTES = 1_500_000_000

# Smallest believable frontend binary. A floor, NOT a ratio against the previous
# one: the first in-app update legitimately replaces a Debug binary (the build
# script's default, ~60 MB here) with a Release one several times smaller, and a
# ratio test would reject that perfectly good build and roll the update back. What
# is actually being detected is a link killed part-way, which leaves bytes, not
# megabytes.
_MIN_ARTIFACT_BYTES = 1_000_000

# Longest a run could legitimately take, used only to stand the restart veto
# down. Past this the job is wedged rather than slow, and a device that cannot be
# restarted is worse than one that restarts mid-nothing.
_JOB_SANITY_MS = int((_FETCH_TIMEOUT + _CHECKOUT_TIMEOUT + _BUILD_TIMEOUT
                      + _DEPS_TIMEOUT + _ROLLBACK_TIMEOUT + 600.0) * 1000)

# Between telling the frontend to restart and restarting ourselves. Long enough
# for the broadcast to reach it and for it to exit; short enough that the two
# halves come back together rather than the dashboard reconnecting to a backend
# that is about to disappear.
_FRONTEND_RESTART_GRACE = 2.0

# Environment forced onto every git subprocess.
#
# GIT_ASKPASS set to the EMPTY STRING is the load-bearing entry, and it is not
# obvious: GIT_TERMINAL_PROMPT=0 alone only suppresses git's own tty prompt, and
# git then falls through to an askpass helper — measured hanging forever on a
# credential prompt nobody can answer. Setting the variable at all (even empty)
# also suppresses the SSH_ASKPASS fallback, which matters here because the Pi
# runs a full desktop, so DISPLAY is set and a GUI helper is a real possibility.
# With it, an unauthenticated fetch fails in milliseconds with "terminal prompts
# disabled" instead of parking the step until its timeout.
#
# GIT_DIR / GIT_WORK_TREE are scrubbed, not set: inherited values would silently
# redirect the checkout at a different repository.
_GIT_ENV = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_ASKPASS": "",
    "SSH_ASKPASS": "",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_SSH_COMMAND": "ssh -oBatchMode=yes -oStrictHostKeyChecking=accept-new "
                       "-oConnectTimeout=10",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_PAGER": "cat",
    "LC_ALL": "C",
}

# Environment variables removed from every child, git or not.
_SCRUBBED = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")

# Environment for the build and dependency steps. NINJA_STATUS is what turns the
# log into a progress report — ninja prints "[12/177 8.4s]" per finished edge —
# and both tools are told not to draw progress bars, since a carriage-returned
# spinner is noise in a line-oriented log.
_BUILD_ENV = {
    "NINJA_STATUS": "[%f/%t %es] ",
    "UV_NO_PROGRESS": "1",
    "GCC_COLORS": "",
    "TERM": "dumb",
}

# The frontend binary the build produces, and the script that produces it.
#
# Nothing renames it out of the way first, and that is deliberate: ld UNLINKS its
# output before creating it rather than truncating in place, so relinking a
# running executable succeeds and the live process keeps its old inode intact —
# measured, including that never-paged-in code still faults in correctly
# afterwards. (cp and shell redirection DO fail with ETXTBSY, because they
# truncate. The linker is the exception.) A rename dance would only add a
# half-moved-binary failure mode to solve a problem that does not exist.
_FRONTEND_EXE = Path("frontend_v2") / "build" / "appfrontend_v2"
_BUILD_SCRIPT = Path("scripts") / "build-frontend.sh"
_BUILD_CACHE = Path("frontend_v2") / "build" / "CMakeCache.txt"

# Qt kit directory names, newest-first by version once sorted. The Pi's ARM kit
# is gcc_arm64, not gcc_64 — the build script's own glob missed that.
_QT_KIT_DIRS = ("gcc_64", "gcc_arm64")

# The steps of a run, in order.
_STEP_FETCH = "fetch"
_STEP_CHECKOUT = "checkout"
_STEP_DEPS = "deps"
_STEP_BUILD = "build"
_STEP_RESTART = "restart"

# The BUILD runs BEFORE the dependency sync, which is not the obvious order.
# `uv sync` rewrites backend/.venv — the virtualenv this very interpreter is
# running from — and the build that follows it takes tens of minutes on a Pi. Any
# lazily-imported submodule of a package the sync replaced would then fail in a
# process with no supervisor (CLAUDE.md §5.2: an unhandled failure ends it), and
# systemd would restart the backend mid-build, destroying the run's own rollback.
# Syncing last shrinks that window from the whole build to the seconds before the
# restart, and means a failed build rolls back without ever having touched the
# virtualenv.
_STEPS = (
    (_STEP_FETCH, "Haetaan muutokset"),
    (_STEP_CHECKOUT, "Vaihdetaan versio"),
    (_STEP_BUILD, "Käännetään käyttöliittymä"),
    (_STEP_DEPS, "Päivitetään riippuvuudet"),
    (_STEP_RESTART, "Käynnistetään uudelleen"),
)

# Steps a cancel may interrupt. A checkout takes seconds and stopping halfway is
# how you get a half-written index; the restart step is a sleep and a signal.
_CANCELLABLE_STEPS = (_STEP_FETCH, _STEP_DEPS, _STEP_BUILD)


def _short(sha: str) -> str:
    '''
    Abbreviates a commit sha for display.
    Arguments:
        sha (str): Full or partial object name; may be empty.
    '''
    return sha[:7] if sha else ""


def _version_key(path: Path) -> list:
    '''
    Sort key that orders Qt kit directories by version rather than lexically, so
    6.11.1 beats 6.9.0.
    Arguments:
        path (Path): A kit directory such as ~/Qt/6.11.1/gcc_64.
    '''
    return [int(part) if part.isdigit() else 0
            for part in re.split(r"[._-]", path.parent.name)]


class UpdateService:
    '''
    Serves UPDATE_GET_STATE / UPDATE_APPLY / UPDATE_CANCEL and broadcasts
    UPDATE_STATE.

    Registered with Server.register_service, so every connecting dashboard gets
    the last known state without asking — including a run already in progress.

    Arguments:
        server (Server): TCP server used to broadcast and to reply.
        config_service (ConfigService): Consulted for its restart trigger, so the
            updater does not grow a second way to exit the process, and given a
            veto so the Options view's own restart button cannot kill a run.
        repo_path (str | None): Override for the checkout to update. Normally
            None, and the repository containing this file is used.
    '''

    def __init__(self, server, config_service, repo_path: str | None = None):
        self.__server = server
        self.__config_service = config_service
        self.__requested_root = Path(repo_path).expanduser() if repo_path else None

        # Resolved on the first probe in run(); until then the card reports that
        # it is still working it out rather than claiming the feature is missing.
        self.__root: Path | None = None
        self.__available = False
        self.__reason = "Selvitetään…"

        self.__state: dict = {}
        self.__job: dict | None = None
        self.__job_seq = 0
        self.__log: deque[str] = deque(maxlen=_LOG_LINES)
        self.__proc: asyncio.subprocess.Process | None = None
        self.__task: asyncio.Task | None = None
        self.__cancelled = False
        # Throttling keys on the ATTEMPT, not the success. Keying on success
        # means an unreachable remote is never throttled at all, so every card
        # open pays the full fetch timeout again.
        self.__last_fetch_attempt: float | None = None
        self.__last_fetch_ms: int | None = None
        # Claimed synchronously by handle_apply before its first await, because
        # self.__job is not set until __run_job is actually scheduled and the
        # server dispatches every packet as its own task — so two applies would
        # otherwise both pass the "already running" guard.
        self.__starting = False
        self.__last_broadcast = 0.0
        # Serialises state rebuilds so two clients opening the card at once do
        # not run overlapping git queries against the same working tree.
        self.__lock = asyncio.Lock()

        # A restart during a checkout or a dependency sync is how a device gets
        # left half-updated, and the button that would do it sits three rows
        # below this card. ConfigService asks every registered veto before it
        # arms the exit.
        config_service.register_restart_veto("update", self.__veto_restart)

    @property
    def __repo(self) -> Path:
        '''
        The repository root, for paths already gated on availability.  Raising
        here rather than returning Optional keeps every call site free of a check
        that can only fail if the gating above it was skipped.
        '''
        if self.__root is None:
            raise RuntimeError("No git working tree resolved")
        return self.__root

    def __run_in_flight(self) -> bool:
        '''
        Whether a run is live — either already broadcasting a job, or claimed by
        a handle_apply that has not scheduled one yet.
        '''
        if self.__starting:
            return True
        return self.__job is not None and not self.__job.get("finished")

    def __veto_restart(self) -> str:
        '''
        Refuses a CONFIG_RESTART while a run is in flight, with the reason shown
        to whoever asked.  Empty string means "no objection".

        BOUNDED by a deadline.  A veto that can never lapse would turn a wedged
        job into a device that cannot be restarted at all — and restarting is the
        only recovery this screen has left at that point.  Past the longest a
        legitimate run could take, the veto stands down and says so in the log.
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
        UPDATE_GET_STATE handler: rebuilds the state document and replies to the
        requesting client.  A request may ask for a network fetch first; that is
        throttled, so a user tapping between sections cannot hammer the remote.

        Never rebuilds while a run is in progress — the working tree is being
        rewritten underneath us, so any answer would be a lie, and the job's own
        progress is already being broadcast.
        Arguments:
            payload (bytes): len(4B) + UTF-8 JSON {"fetch": <bool>}.
            writer (StreamWriter): The requesting client.
        '''
        body = self.__decode_json(payload, "UPDATE_GET_STATE")
        want_fetch = bool(body.get("fetch")) if body else False

        if self.__job is None or self.__job.get("finished"):
            await self.__refresh(fetch=want_fetch)
        await self.__server.send_to(writer, self.__state_frame())

    async def handle_apply(self, payload: bytes, _writer) -> None:
        '''
        UPDATE_APPLY handler: validates the request and starts the run.  A
        refusal is reported by broadcasting a finished, failed job rather than by
        replying privately — the other dashboard has to learn why nothing
        happened too, and the card renders one thing either way.
        Arguments:
            payload (bytes): len(4B) + UTF-8 JSON {"channel": str, "commit": sha}.
            _writer (StreamWriter): Unused — the answer is a broadcast, not a reply.
        '''
        # The running-job test comes FIRST and claims the slot before any await.
        # self.__job is not assigned until __run_job is scheduled, and the server
        # dispatches every packet as its own task, so two applies arriving inside
        # the ~1 s __refresh below would both pass a test that only looked at
        # __job — and would each start a full run against one working tree.
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
        Validates one apply request and launches the run.  Split out of
        handle_apply so the slot claimed there is released on every exit path,
        including a raise, without a `finally` per refusal.
        Arguments:
            payload (bytes): The raw UPDATE_APPLY body.
        '''
        body = self.__decode_json(payload, "UPDATE_APPLY")
        if body is None:
            await self.__refuse("Virheellinen päivityspyyntö")
            return

        # Truncated before it is interpolated into a message that is broadcast and
        # then re-sent in every later state frame: the body may be up to
        # MAX_MSG_SIZE, and the server takes connections from the whole LAN.
        channel = str(body.get("channel", ""))[:32]
        commit = str(body.get("commit", "")).lower()

        if not self.__available or self.__root is None:
            await self.__refuse(self.__reason or "Päivitys ei ole käytettävissä")
            return
        if channel not in CHANNELS:
            await self.__refuse(f"Tuntematon päivityskanava: {channel!r}")
            return
        if not _FULL_SHA.match(commit):
            await self.__refuse("Virheellinen kohdeversio")
            return

        # Re-resolve from scratch: the state the user tapped on may be minutes
        # old, and everything below is decided from what is true now.
        await self.__refresh(fetch=False)
        if self.__state.get("dirty"):
            await self.__refuse("Työhakemistossa on paikallisia muutoksia")
            return

        blocker = self.__state.get("tools", {}).get("blocker", "")
        if blocker:
            await self.__refuse(blocker)
            return

        target = self.__state.get("channels", {}).get(channel, {})
        if target.get("commit") != commit:
            await self.__refuse(
                "Kohdeversio on muuttunut sitten tarkistuksen — tarkista uudelleen"
            )
            return
        if target.get("verdict") == "up_to_date":
            await self.__refuse("Tämä versio on jo käytössä")
            return
        if not target.get("eligible", False):
            await self.__refuse(target.get("eligibleReason")
                                or "Kohdeversioon ei voi siirtyä tästä näytöstä")
            return

        # Claim the slot in self.__job BEFORE creating the task. handle_apply's
        # `finally` clears __starting as soon as this returns, and the task has
        # not run yet at that point — so without this there is a window in which
        # neither fence holds and a second apply slips through.
        previous = self.__state.get("current", {}).get("commit", "")
        self.__cancelled = False
        self.__log.clear()
        self.__job = self.__new_job(channel, target, previous)
        self.__task = asyncio.create_task(self.__run_job(target, previous))
        # The loop holds only a weak reference to a task, so a bare create_task
        # can be collected mid-flight and take its exception with it.
        self.__task.add_done_callback(self.__on_job_done)

    async def handle_cancel(self, _payload: bytes, _writer) -> None:
        '''
        UPDATE_CANCEL handler: stops the run at the end of the current step.

        Refused during the checkout, which takes seconds and whose interruption
        is exactly the half-written state everything else here exists to avoid.
        During the dependency sync or the build a cancel is honoured and then
        rolled back like any other failure, so "cancel" means "put it back", not
        "abandon it wherever it got to".

        The step's process is killed by PROCESS GROUP, not by pid.  The build
        step is a shell that spawns cmake, which spawns ninja, which spawns a
        compiler per file — measured: terminating the shell alone leaves that
        whole tree running, and its inherited stdout pipe never closes, so the
        reader waits on it forever.
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
        On-connect snapshot: the last known state, including a run in progress.
        Deliberately does not re-probe git — a connect burst must stay cheap, and
        the card asks for a fresh state the moment it opens anyway.
        Arguments:
            writer (StreamWriter): The newly connected client.
        '''
        await self.__server.send_to(writer, self.__state_frame())

    # ── Health probe (the maintenance dashboard) ──────────────────

    def health(self) -> dict:
        '''
        Duck-typed probe for SystemStatusService: whether this deployment can
        update itself, and what it is running.
        '''
        if not self.__available:
            return {"state": "off", "detail": self.__reason}
        if self.__job is not None and not self.__job.get("finished"):
            return {"state": "warn", "detail": "Päivitys käynnissä"}
        if self.__job is not None and self.__job.get("ok") is False:
            return {"state": "warn", "detail": "Edellinen päivitys epäonnistui"}
        current = self.__state.get("current", {})
        return {"state": "ok", "detail": current.get("label", "")}

    # ── Run task ──────────────────────────────────────────────────

    async def run(self) -> None:
        '''
        Startup task: locates the checkout and publishes the first state.  A host
        with no git, or a copy of the source that is not a working tree, reports
        itself unavailable and every later request is refused — the same shape
        display_service uses for a missing wlopm.
        '''
        await self.__locate_repository()
        await self.__refresh(fetch=False)
        await self.__server.broadcast(self.__state_frame())

    def get_run_task(self):
        '''Returns the startup task for start_services to gather.'''
        return asyncio.create_task(self.run())

    # ── Repository discovery ──────────────────────────────────────

    async def __locate_repository(self) -> None:
        '''
        Resolves the checkout to operate on and records why it could not be, in
        the exact words the card shows.

        The starting point is this file's own location, so the service updates
        the tree it is running from rather than a path in a config file that may
        no longer be the one systemd launched.  `rev-parse --show-toplevel` does
        the resolving, which is what makes a LINKED WORKTREE (CLAUDE.md §8)
        resolve to that worktree — the right answer, since that is the tree the
        running backend was launched from.  --path-format=absolute matters: the
        related --git-common-dir is returned relative to cwd in a main worktree
        and absolute in a linked one.
        '''
        if shutil.which("git") is None:
            self.__available = False
            self.__reason = "Gitiä ei löydy tästä järjestelmästä"
            logger.warning("git not found; the app-update card will be inert")
            return

        start = self.__requested_root or Path(__file__).resolve().parent
        code, out, err = await self.__git(
            "rev-parse", "--path-format=absolute", "--show-toplevel", cwd=start
        )
        if code != 0 or not out.strip():
            self.__available = False
            self.__reason = "Sovellus ei ole git-työhakemistossa"
            logger.warning("Not a git working tree at %s: %s", start, err.strip())
            return

        self.__root = Path(out.strip())
        self.__available = True
        self.__reason = ""
        logger.info("App updates available from %s", self.__root)

    # ── State ─────────────────────────────────────────────────────

    async def __refresh(self, fetch: bool) -> None:
        '''
        Rebuilds the state document from the repository.
        Arguments:
            fetch (bool): Contact the remote first. Throttled to at most one
                fetch per _FETCH_MIN_INTERVAL regardless of how often asked.
        '''
        async with self.__lock:
            if not self.__available or self.__root is None:
                self.__state = self.__unavailable_state()
                return
            if fetch and self.__fetch_is_due():
                await self.__fetch()
            self.__state = await self.__build_state()

    def __fetch_is_due(self) -> bool:
        '''True when enough time has passed since the last fetch ATTEMPT.'''
        if self.__last_fetch_attempt is None:
            return True
        return (time.monotonic() - self.__last_fetch_attempt) >= _FETCH_MIN_INTERVAL

    async def __fetch(self) -> bool:
        '''
        Fetches refs and tags from the remote.  A failure is not fatal on the
        read path: the card still renders from what is already local, with the
        last fetch time showing how stale that is.

        --force is there for tags specifically: --tags uses a non-forced refspec,
        so a release tag that was MOVED on the remote is rejected with "would
        clobber existing tag" and the releases channel would silently keep
        pointing at the old commit. --prune-tags is deliberately NOT used: it
        deletes local tags the remote does not have, which is right for a
        deployment and wrong for the maintainer's own checkout.
        '''
        self.__last_fetch_attempt = time.monotonic()
        code, _out, err = await self.__git(
            "fetch", "--prune", "--tags", "--force", REMOTE, timeout=_FETCH_READ_TIMEOUT
        )
        if code != 0:
            logger.warning("git fetch failed: %s", err.strip()[:200])
            return False
        self.__last_fetch_ms = int(time.time() * 1000)
        return True

    def __unavailable_state(self) -> dict:
        '''The state document for a host that cannot update itself.'''
        return {
            "available": False,
            "reason": self.__reason,
            "repoPath": str(self.__root) if self.__root else "",
            "remoteUrl": "",
            "branch": "",
            "dirty": False,
            "dirtyFiles": [],
            "fetchedMs": self.__last_fetch_ms,
            "current": {},
            "channels": {},
            "tools": {"blocker": self.__reason},
            "job": self.__job,
        }

    async def __build_state(self) -> dict:
        '''
        Queries the repository and assembles the whole state document: what is
        checked out now, what each channel would move to, the verdict for each,
        and whether the host has what a run would need.  Both channels are
        reported every time — resolving them costs two extra rev-parses, and it
        means switching the channel in the card is instant instead of another
        round trip.
        '''
        current = await self.__describe_commit("HEAD")
        _c, branch_out, _e = await self.__git("rev-parse", "--abbrev-ref", "HEAD")
        branch = branch_out.strip()
        if branch == "HEAD":
            branch = ""  # detached; the label below carries the useful part

        _c, status_out, _e = await self.__git(
            "status", "--porcelain", "--untracked-files=no"
        )
        dirty_files = [line[3:] for line in status_out.splitlines() if line.strip()]

        _c, remote_out, _e = await self.__git("remote", "get-url", REMOTE)

        channels = {
            CHANNEL_DEVELOPMENT: await self.__resolve_development(current),
            CHANNEL_RELEASES: await self.__resolve_releases(current),
        }

        return {
            "available": True,
            "reason": "",
            "repoPath": str(self.__root),
            "remoteUrl": remote_out.strip(),
            "branch": branch,
            "dirty": bool(dirty_files),
            "dirtyFiles": dirty_files[:10],
            "fetchedMs": self.__last_fetch_ms,
            "current": current,
            "channels": channels,
            "tools": self.__probe_tools(),
            "job": self.__job,
        }

    def __probe_tools(self) -> dict:
        '''
        Checks everything a run needs BEFORE the button can be tapped: uv, the
        build script, a Qt kit and disk headroom.

        Every one of these is a failure that would otherwise land minutes into a
        run, after the tree had already been moved.  The Qt kit is the sharpest:
        a `systemd --user` unit inherits none of the user's shell environment, so
        QTDIR is unset there, and the build script's own kit glob only looked for
        an x86 "gcc_64" directory — the Pi's kit is "gcc_arm64".
        '''
        uv = self.__uv_path()
        script = self.__repo / _BUILD_SCRIPT
        qt = self.__qt_prefix()
        try:
            free = shutil.disk_usage(self.__repo).free
        except OSError:
            free = None

        blocker = ""
        if uv is None:
            blocker = "uv-työkalua ei löydy — riippuvuuksia ei voi päivittää"
        elif not script.exists():
            blocker = f"Käännösskripti puuttuu: {_BUILD_SCRIPT}"
        elif qt is None:
            blocker = ("Qt-käännösympäristöä ei löydy — aseta QTDIR palvelimen "
                       "ympäristöön")
        elif free is not None and free < _MIN_FREE_BYTES:
            blocker = "Levytilaa on liian vähän käännökseen"

        return {
            "uvPath": str(uv) if uv else "",
            "qtPrefix": str(qt) if qt else "",
            "buildScript": str(script) if script.exists() else "",
            "freeBytes": free,
            "blocker": blocker,
        }

    def __uv_path(self) -> Path | None:
        '''
        Locates uv.  PATH first, then the install location the README's unit
        hardcodes — a systemd user unit's PATH does not include ~/.local/bin, so
        which() alone finds nothing exactly where it matters most.
        '''
        found = shutil.which("uv")
        if found:
            return Path(found)
        fallback = Path.home() / ".local" / "bin" / "uv"
        return fallback if fallback.exists() else None

    def __qt_prefix(self) -> Path | None:
        '''
        Resolves the Qt kit to build against, in decreasing order of confidence:
        QTDIR, then the newest ~/Qt/*/gcc_64 or gcc_arm64, then whatever the
        existing build directory was configured with.

        That last source is the most reliable one on a device that has built
        before — it is by definition a prefix that worked here — and it is why a
        Pi whose kit lives somewhere unusual still updates without configuration.
        A kit is only accepted if it actually holds bin/qmake6.
        '''
        def usable(path: Path) -> bool:
            return (path / "bin" / "qmake6").exists()

        env_prefix = os.environ.get("QTDIR", "").strip()
        if env_prefix and usable(Path(env_prefix)):
            return Path(env_prefix)

        candidates: list[Path] = []
        for name in _QT_KIT_DIRS:
            candidates.extend(Path.home().glob(f"Qt/*/{name}"))
        for path in sorted((p for p in candidates if usable(p)),
                           key=_version_key, reverse=True):
            return path

        cache = self.__repo / _BUILD_CACHE
        if cache.exists():
            try:
                for line in cache.read_text(encoding="utf-8", errors="replace").splitlines():
                    if line.startswith("CMAKE_PREFIX_PATH:"):
                        _, _, value = line.partition("=")
                        path = Path(value.strip())
                        if value.strip() and usable(path):
                            return path
            except OSError:
                pass
        return None

    async def __resolve_development(self, current: dict) -> dict:
        '''
        Resolves the development channel: the tip of the remote's default branch.
        Arguments:
            current (dict): The described HEAD, for the verdict comparison.
        '''
        ref = f"{REMOTE}/{DEV_BRANCH}"
        code, out, _err = await self.__git("rev-parse", "--verify", f"{ref}^{{commit}}")
        if code != 0:
            return self.__unresolved_channel(
                ref, DEV_BRANCH, f"{ref} ei ole tiedossa — tarkista päivitykset"
            )
        described = await self.__describe_commit(out.strip())
        described["label"] = DEV_BRANCH
        described["ref"] = ref
        described.update(await self.__compare(current.get("commit", ""), described["commit"]))
        described.update(await self.__eligibility(described["commit"]))
        return described

    async def __resolve_releases(self, current: dict) -> dict:
        '''
        Resolves the releases channel: the newest v* tag.

        `--sort=-v:refname` is git's own version ordering, so v1.10.0 sorts above
        v1.9.0 where a lexical sort would not.  The tag is dereferenced with
        `^{commit}`, which matters for annotated tags: a bare `rev-parse v1.0.0`
        yields the TAG object, and comparing that against a commit finds no
        ancestry at all.
        Arguments:
            current (dict): The described HEAD, for the verdict comparison.
        '''
        code, out, _err = await self.__git(
            "tag", "--list", RELEASE_TAG_GLOB, "--sort=-v:refname"
        )
        tags = [line.strip() for line in out.splitlines() if line.strip()] if code == 0 else []
        if not tags:
            return self.__unresolved_channel("", "", "Julkaisuja ei löytynyt")

        latest = tags[0]
        code, sha_out, _err = await self.__git("rev-parse", "--verify", f"{latest}^{{commit}}")
        if code != 0:
            resolved = self.__unresolved_channel(
                latest, latest, f"Julkaisua {latest} ei voitu selvittää"
            )
            resolved["releases"] = tags
            return resolved

        described = await self.__describe_commit(sha_out.strip())
        described["label"] = latest
        described["ref"] = latest
        described["releases"] = tags
        described.update(await self.__compare(current.get("commit", ""), described["commit"]))
        described.update(await self.__eligibility(described["commit"]))
        return described

    @staticmethod
    def __unresolved_channel(ref: str, label: str, message: str) -> dict:
        '''
        The channel description used when no target could be resolved at all.
        Arguments:
            ref (str): The ref that was attempted, for display.
            label (str): Human-facing name of the target, if there is one.
            message (str): Finnish explanation shown in the card.
        '''
        return {
            "ref": ref,
            "label": label,
            "commit": "",
            "releases": [],
            "verdict": "unknown",
            "eligible": False,
            "eligibleReason": message,
            "message": message,
        }

    async def __eligibility(self, commit: str) -> dict:
        '''
        Decides whether this service is willing to move onto a commit at all.

        A target that does not contain the updater is a ONE-WAY TRAPDOOR: the
        panel that performed the update does not exist on the version it
        produced, and on a keyboard-less device the only way back is SSH.  This
        project's single release tag is exactly such a commit today, which is
        precisely why the check is here rather than left as a warning.
        Arguments:
            commit (str): The resolved target commit.
        '''
        if not commit:
            return {"eligible": False,
                    "eligibleReason": "Kohdeversiota ei voitu selvittää"}
        for path in _REQUIRED_PATHS:
            code, _out, _err = await self.__git("cat-file", "-e", f"{commit}:{path}")
            if code != 0:
                return {
                    "eligible": False,
                    "eligibleReason": ("Kohdeversiossa ei ole päivitystoimintoa, "
                                       "joten siihen ei voi siirtyä tästä näytöstä"),
                }
        return {"eligible": True, "eligibleReason": ""}

    async def __describe_commit(self, rev: str) -> dict:
        '''
        Reads the identity of one commit: sha, commit date, subject and the tag
        on it if there is one.

        %cI is the strict ISO-8601 form, which the frontend can hand straight to
        Date(); %ci would give a space-separated form it cannot parse. Fields are
        separated by %x1f (US), the one byte a commit subject cannot contain.
        Arguments:
            rev (str): Anything git can resolve to a commit.
        '''
        code, out, _err = await self.__git(
            "log", "-1", "--format=%H%x1f%cI%x1f%s", rev
        )
        if code != 0 or not out.strip():
            return {"commit": "", "short": "", "date": "", "subject": "", "tag": "",
                    "label": ""}

        sha, _, rest = out.strip().partition("\x1f")
        date, _, subject = rest.partition("\x1f")

        # --exact-match answers "is this commit released?", which is the question
        # the card asks; the nearest-tag form would label every dev commit with
        # the last release and read as if it were that release.
        code, tag_out, _err = await self.__git(
            "describe", "--tags", "--exact-match", sha
        )
        tag = tag_out.strip() if code == 0 else ""

        return {
            "commit": sha,
            "short": _short(sha),
            "date": date,
            "subject": subject,
            "tag": tag,
            "label": tag or _short(sha),
        }

    async def __compare(self, current: str, target: str) -> dict:
        '''
        Compares two commits into a verdict plus a commit distance.

        `merge-base --is-ancestor` exits 0 for "yes" and 1 for "no"; anything
        else is a broken repository or a missing object, which is reported as
        unknown rather than guessed at.
        Arguments:
            current (str): The checked-out commit.
            target (str): The commit the channel would move to.
        '''
        if not current or not target:
            return {"verdict": "unknown", "ahead": 0, "behind": 0, "message": ""}
        if current == target:
            return {"verdict": "up_to_date", "ahead": 0, "behind": 0, "message": ""}

        ahead = behind = 0
        code, counts, _err = await self.__git(
            "rev-list", "--left-right", "--count", f"{current}...{target}"
        )
        if code == 0:
            parts = counts.split()
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                # left = commits only on current, right = commits only on target
                behind, ahead = int(parts[0]), int(parts[1])

        forward = await self.__is_ancestor(current, target)
        backward = await self.__is_ancestor(target, current)
        if forward is None or backward is None:
            verdict = "unknown"
        elif forward:
            verdict = "update"
        elif backward:
            verdict = "downgrade"
        else:
            verdict = "switch"

        return {"verdict": verdict, "ahead": ahead, "behind": behind, "message": ""}

    async def __is_ancestor(self, ancestor: str, descendant: str) -> bool | None:
        '''
        True/False for the ancestry question, None when git could not answer it.
        Arguments:
            ancestor (str): Candidate ancestor commit.
            descendant (str): Candidate descendant commit.
        '''
        code, _out, _err = await self.__git(
            "merge-base", "--is-ancestor", ancestor, descendant
        )
        if code == 0:
            return True
        if code == 1:
            return False
        return None

    # ── The run ───────────────────────────────────────────────────

    def __new_job(self, channel: str, target: dict, previous: str) -> dict:
        '''
        Builds the job document for one run.  Synchronous on purpose — see the
        call site: it is what holds the slot between handle_apply returning and
        the run task first being scheduled.
        Arguments:
            channel (str): The validated channel this run targets.
            target (dict): The resolved target description for that channel.
            previous (str): The commit the run starts from.
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
            "channel": channel,
            "targetLabel": target.get("label", ""),
            "targetCommit": target.get("commit", ""),
            "previousCommit": previous,
            "verdict": target.get("verdict", ""),
            "startedMs": int(time.time() * 1000),
            "finishedMs": None,
            "message": "",
            "restartFrontend": False,
            "steps": [{"id": sid, "label": label, "state": "pending"}
                      for sid, label in _STEPS],
            "log": [],
        }

    async def __run_job(self, target: dict, previous: str) -> None:
        '''
        Executes the whole update, one step at a time, broadcasting after every
        transition.  Each step's failure ends the run, and anything that fails
        after the checkout rolls the tree back first.

        The whole body is wrapped so the job is ALWAYS closed out.  An exception
        escaping this coroutine would leave `running: True` forever, and every
        gate in the service reads that flag: no later update could start, the
        card would freeze on stale data, and the restart veto would refuse the
        one recovery a keyboard-less panel still has.
        Arguments:
            target (dict): The resolved target description for the channel.
            previous (str): The commit the run starts from.
        '''
        try:
            await self.__run_steps(target, previous)
        except Exception as e:  # noqa: BLE001 - the job must never stay open
            logger.error("Update run crashed: %s", e)
            self.__append_log(f"{type(e).__name__}: {e}")
            self.__finish(False, "Päivitys keskeytyi odottamattomaan virheeseen")
            await self.__broadcast(force=True)
        finally:
            if self.__job is not None and not self.__job.get("finished"):
                self.__finish(False, "Päivitys päättyi kesken")
                await self.__broadcast(force=True)

    async def __run_steps(self, target: dict, previous: str) -> None:
        '''
        The step loop itself.  Separated from __run_job only so that method can
        be a pure guarantee that the job is closed out.
        Arguments:
            target (dict): The resolved target description for the channel.
            previous (str): The commit the run starts from.
        '''
        logger.warning(
            "Updating %s -> %s (%s)",
            _short(previous), target.get("label"), _short(target.get("commit", "")),
        )
        await self.__broadcast(force=True)

        runners = {
            _STEP_FETCH: self.__run_fetch,
            _STEP_CHECKOUT: lambda: self.__run_checkout(target["commit"]),
            _STEP_DEPS: self.__run_deps,
            _STEP_BUILD: self.__run_build,
            _STEP_RESTART: self.__run_restart,
        }

        moved = False
        for index, (step_id, label) in enumerate(_STEPS):
            if self.__cancelled:
                await self.__fail(index, "Päivitys peruutettiin", previous, moved)
                return
            self.__set_step(index, "running")
            await self.__broadcast(force=True)

            try:
                ok = await runners[step_id]()
            except Exception as e:  # noqa: BLE001 - a broken step must not kill the loop
                logger.error("Update step %s crashed: %s", step_id, e)
                self.__append_log(f"{type(e).__name__}: {e}")
                ok = False

            if step_id == _STEP_CHECKOUT and ok:
                moved = True
            if self.__cancelled:
                await self.__fail(index, "Päivitys peruutettiin", previous, moved)
                return
            if not ok:
                await self.__fail(index, f"Vaihe epäonnistui: {label}", previous, moved)
                return
            self.__set_step(index, "done")
            await self.__broadcast(force=True)

        self.__finish(True, "Päivitys valmis")
        await self.__broadcast(force=True)

    async def __fail(self, index: int, message: str, previous: str, moved: bool) -> None:
        '''
        Ends a run that did not succeed, rolling the working tree back when it
        had already been moved.

        The rollback is what keeps a failure recoverable from the touchscreen.
        A new source tree beside an old virtualenv is the one genuinely
        unrecoverable state this feature can produce: the backend's service unit
        re-syncs on every start, so the next restart would fail, retry, and fail
        again — with the Options view gone along with the backend.

        The job is NOT closed out until the rollback has finished.  Everything
        the dashboard gates on a run being in flight — the "do not cut the power"
        banner, the suppressed screensaver and panel blackout, the disabled
        restart buttons — reads `finished`, and a rollback is a `uv sync` that
        must be protected exactly like the sync that failed.
        Arguments:
            index (int): The step that failed.
            message (str): Finnish summary for the card.
            previous (str): The commit the run started from.
            moved (bool): Whether the working tree was actually moved.
        '''
        self.__set_step(index, "failed")
        if self.__job is not None:
            self.__job["message"] = message
            self.__job["cancellable"] = False
        await self.__broadcast(force=True)

        suffix = ""
        if moved and previous:
            suffix = await self.__rollback(previous)
        self.__finish(False, message + suffix)
        await self.__broadcast(force=True)

    async def __rollback(self, previous: str) -> str:
        '''
        Puts the working tree and the virtualenv back where the run found them,
        and returns the sentence to append to the job's message.  Best effort and
        never fatal — a failed rollback is reported, because at that point the
        only useful thing left to do is tell the user exactly what state the
        device is in.
        Arguments:
            previous (str): The commit the run started from.
        '''
        if self.__job is None:
            return ""
        step = {"id": "rollback", "label": "Palautetaan edellinen versio",
                "state": "running"}
        self.__job["steps"].append(step)
        await self.__broadcast(force=True)

        ok = await self.__run_step_process(
            ["git", "-c", "advice.detachedHead=false", "checkout", "--detach", previous],
            cwd=self.__repo, timeout=_CHECKOUT_TIMEOUT, env=_GIT_ENV,
        )
        if ok:
            uv = self.__uv_path()
            if uv is not None:
                ok = await self.__run_step_process(
                    [str(uv), "sync", "--locked", "--no-progress"],
                    cwd=self.__repo / "backend", timeout=_ROLLBACK_TIMEOUT,
                    env=_BUILD_ENV,
                )

        step["state"] = "done" if ok else "failed"
        logger.warning("Rollback to %s %s", _short(previous), "ok" if ok else "FAILED")
        return (" · Palautettu versioon " + _short(previous)) if ok \
            else " · Palautus epäonnistui — laite on välitilassa"

    def __on_job_done(self, task: asyncio.Task) -> None:
        '''
        Retrieves a finished run task's exception so it is logged rather than
        surfacing as "Task exception was never retrieved" at shutdown.
        Arguments:
            task (Task): The completed run task.
        '''
        self.__task = None
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.error("Update task failed: %s", error)

    async def __run_fetch(self) -> bool:
        '''
        Fetch step: refresh refs and tags, ignoring the read-path throttle.

        Runs through __run_step_process rather than the __git helper the read
        path uses, and that is the point: only __run_step_process registers the
        child on self.__proc, so only through it can a cancel — or a timeout —
        actually reach the process group. It also streams git's own progress into
        the job log instead of swallowing it.
        '''
        self.__last_fetch_attempt = time.monotonic()
        ok = await self.__run_step_process(
            ["git", "fetch", "--prune", "--tags", "--force", REMOTE],
            cwd=self.__repo, timeout=_FETCH_TIMEOUT, env=_GIT_ENV,
        )
        if ok:
            self.__last_fetch_ms = int(time.time() * 1000)
        return ok

    async def __run_checkout(self, commit: str) -> bool:
        '''
        Checkout step: moves the working tree onto the target commit, DETACHED.

        Detaching is deliberate and uniform across both channels.  A release is a
        tag and can only be checked out detached anyway, so a branch-tracking
        development channel would mean two code paths; detaching also never
        discards a local branch, and — the case that decides it — a LINKED
        WORKTREE refuses `checkout main` outright when main is checked out
        elsewhere, while `checkout --detach <sha>` always works.  The cost is
        that `git status` reads "HEAD detached at …", which the card compensates
        for by naming the version itself.

        No -f. A checkout aborted because an untracked file collides with a path
        the target adds is a clean refusal, and forcing past it would delete
        whatever the user had put there.
        Arguments:
            commit (str): Validated 40-hex target commit.
        '''
        return await self.__run_step_process(
            ["git", "-c", "advice.detachedHead=false", "checkout", "--detach", commit],
            cwd=self.__repo,
            timeout=_CHECKOUT_TIMEOUT,
            env=_GIT_ENV,
        )

    async def __run_deps(self) -> bool:
        '''
        Dependency step: `uv sync` against the checked-out lockfile.

        `--locked` rather than a bare sync, and this is not a style choice.  A
        bare `uv sync` SILENTLY RE-RESOLVES and rewrites uv.lock when it drifts
        from pyproject.toml — and uv.lock is a TRACKED file, so that write makes
        the working tree dirty and every future run of this service refuses to
        start, pointing at a file the user never touched.  `--locked` turns the
        same drift into a loud, correct failure here.  (`--frozen` also avoids
        the rewrite but installs the stale lock silently, which is the drift you
        most want to hear about when moving to someone else's commit.)
        '''
        uv = self.__uv_path()
        if uv is None:
            self.__append_log("uv ei löydy — riippuvuuksia ei voitu päivittää")
            return False
        return await self.__run_step_process(
            [str(uv), "sync", "--locked", "--no-progress"],
            cwd=self.__repo / "backend",
            timeout=_DEPS_TIMEOUT,
            env=_BUILD_ENV,
        )

    async def __run_build(self) -> bool:
        '''
        Build step: rebuilds the frontend from the checked-out sources, then
        verifies that what came out is runnable.

        The Qt kit is passed explicitly rather than left to the script's own
        detection, because a `systemd --user` unit inherits none of the user's
        shell environment — QTDIR is simply not set there — and passing it as an
        argument puts the chosen kit in the streamed log, where it is visible
        when a build fails.

        The verification is the other half.  ld unlinks its output before writing
        it, so a build killed mid-link leaves either nothing or a truncated file
        at that path; the running dashboard is unaffected (it holds the old
        inode), but restarting it into a stub would leave a keyboard-less device
        with no dashboard at all.  So the artifact must exist, be executable, be
        newer than this run, and not be implausibly small before the restart step
        is allowed to signal anything.
        '''
        script = self.__repo / _BUILD_SCRIPT
        if not script.exists():
            self.__append_log(f"{_BUILD_SCRIPT} puuttuu tästä versiosta")
            return False
        qt = self.__qt_prefix()
        if qt is None:
            self.__append_log("Qt-käännösympäristöä ei löytynyt")
            return False

        exe = self.__repo / _FRONTEND_EXE
        bash = shutil.which("bash") or "/bin/bash"
        ok = await self.__run_step_process(
            [bash, str(script), "--config", "Release", "--qt-prefix", str(qt)],
            cwd=self.__repo,
            timeout=_BUILD_TIMEOUT,
            env=_BUILD_ENV,
        )
        if not ok:
            return False
        return self.__verify_artifact(exe)

    def __verify_artifact(self, exe: Path) -> bool:
        '''
        Checks that the build left a runnable binary behind.

        Deliberately NOT a freshness check, and deliberately an absolute floor
        rather than a ratio against the previous binary.  A build that exits 0
        having found nothing to relink is a success — a commit touching only
        backend files legitimately produces the same file — and the first in-app
        update replaces the build script's default DEBUG binary with a RELEASE
        one several times smaller, which any ratio test would reject as damage.
        What is worth testing is the shape of an interrupted link: ld unlinks its
        output before writing it, so a killed build leaves either nothing or a
        stub, and restarting a keyboard-less panel into a stub leaves no
        dashboard at all.
        Arguments:
            exe (Path): The expected frontend executable.
        '''
        if not exe.exists():
            self.__append_log(f"Käännös ei tuottanut binääriä: {exe.name}")
            return False
        if not os.access(exe, os.X_OK):
            self.__append_log("Käännetty binääri ei ole suoritettava")
            return False
        if exe.stat().st_size < _MIN_ARTIFACT_BYTES:
            self.__append_log("Käännetty binääri on epäilyttävän pieni — keskeytetään")
            return False
        return True

    async def __run_restart(self) -> bool:
        '''
        Restart step: tells the dashboard to restart itself, then restarts the
        backend.

        The order is forced by the link between them.  The dashboard is still
        running the binary that was just replaced — it holds the old inode, which
        ld unlinked rather than overwrote — and only a restart picks the new one
        up.  But the only way to tell it so is over the socket, which dies with
        the backend.  So the frontend is told first, given a moment to act, and
        the backend follows it out; both service units bring their process back.
        '''
        assert self.__job is not None
        self.__job["restartFrontend"] = True
        self.__append_log("Käynnistetään käyttöliittymä uudelleen")
        await self.__broadcast(force=True)
        await asyncio.sleep(_FRONTEND_RESTART_GRACE)
        self.__append_log("Käynnistetään palvelin uudelleen")
        self.__config_service.request_restart(force=True)
        return True

    # ── Subprocess plumbing ───────────────────────────────────────

    async def __run_step_process(self, argv: list[str], cwd: Path, timeout: float,
                                 env: dict | None = None) -> bool:
        '''
        Runs one step's command, streaming its output into the job log.

        start_new_session puts the child in its own process GROUP, which is what
        makes cancellation and timeouts actually work: the build step is a shell
        that spawns cmake, which spawns ninja, which spawns a compiler per file.
        Measured — killing the shell alone leaves that tree running AND leaves
        the inherited stdout pipe open, so the reader below never sees EOF and
        waits forever.
        Arguments:
            argv (list[str]): Command and arguments; never passed through a shell.
            cwd (Path): Working directory for the child.
            timeout (float): Seconds before the child's group is killed.
            env (dict | None): Overrides merged onto the inherited environment.
        '''
        self.__append_log("$ " + " ".join(argv))
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(cwd),
                env=self.__child_env(env),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as e:
            self.__append_log(f"Komentoa ei voitu käynnistää: {e}")
            return False

        self.__proc = process
        # A cancel that arrived between the guard and the spawn saw self.__proc
        # as None and signalled nothing, so honour it here instead of letting a
        # whole build run to completion before the step loop notices.
        if self.__cancelled:
            self.__kill_process()
        try:
            await asyncio.wait_for(self.__pump(process), timeout=timeout)
            code = process.returncode if process.returncode is not None else -1
        except asyncio.TimeoutError:
            self.__append_log(f"Aikakatkaisu {int(timeout)} s jälkeen")
            self.__kill_process()
            code = await self.__reap(process)
        except BaseException:
            # Anything else — CancelledError at loop teardown, an error escaping
            # the pump — must still take the process group down. The build is a
            # tree of compilers writing into the directory the rollback is about
            # to check out from underneath them; orphaning it produces a build
            # directory matching neither commit.
            self.__kill_process()
            await self.__reap(process)
            raise
        finally:
            self.__proc = None

        if code != 0:
            self.__append_log(f"Komento päättyi koodilla {code}")
        await self.__broadcast(force=True)
        return code == 0

    async def __pump(self, process) -> None:
        '''
        Reads the child's merged output and turns it into log lines.

        Read in chunks rather than with readline(): StreamReader.readline RAISES
        once a single line exceeds its 64 KiB buffer, and a deep C++ template
        diagnostic really does exceed that — an exception there would leave the
        job "running" forever, refusing every later request.  Splitting here also
        turns a \\r-updated progress line into a line, for any tool that still
        emits one on a pipe.
        Arguments:
            process (Process): The running child, with stdout piped.
        '''
        buffer = b""
        while True:
            chunk = await process.stdout.read(4096)
            if not chunk:
                break
            buffer += chunk
            buffer = buffer.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
            while b"\n" in buffer:
                line, _, buffer = buffer.partition(b"\n")
                self.__append_log(line.decode("utf-8", "replace"))
            if len(buffer) > _MAX_LINE_BYTES:
                self.__append_log(buffer.decode("utf-8", "replace"))
                buffer = b""
            await self.__broadcast()
        if buffer:
            self.__append_log(buffer.decode("utf-8", "replace"))
        await process.wait()

    def __kill_process(self) -> None:
        '''
        Kills the running step's whole process group, SIGTERM first.  Absent a
        process (the step is between commands) this is a no-op.
        '''
        process = self.__proc
        if process is None or process.returncode is not None:
            return
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError) as e:
            logger.warning("Could not signal the update step: %s", e)

    async def __reap(self, process) -> int:
        '''
        Waits for a killed child, escalating to SIGKILL if it ignores SIGTERM.
        Returns its exit code, or -1 when it could not be collected at all.
        Arguments:
            process (Process): The child that was signalled.
        '''
        try:
            return await asyncio.wait_for(process.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            try:
                return await asyncio.wait_for(process.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                return -1

    def __child_env(self, overrides: dict | None) -> dict:
        '''
        Builds a child environment: everything inherited, minus the variables
        that could redirect git at another repository, plus this step's own.
        Arguments:
            overrides (dict | None): Step-specific variables.
        '''
        env = {k: v for k, v in os.environ.items() if k not in _SCRUBBED}
        env.update(overrides or {})
        return env

    # ── git helper ────────────────────────────────────────────────

    async def __git(self, *args: str, cwd: Path | None = None,
                    timeout: float = _QUERY_TIMEOUT) -> tuple[int, str, str]:
        '''
        Runs one git command and captures it.  Returns (exit code, stdout,
        stderr); a command that could not run at all returns a negative code, so
        a caller checking `!= 0` treats it as a failure without special cases.

        The timeout is the ONLY bound on a network operation: git 2.43 has no
        http.connectTimeout, and the low-speed knobs do not cover the connect
        phase — measured, a fetch at a black-holed address sits there until
        something else kills it.  Same shape, same remedy as the FMI fetch in
        weather_service.  The kill is by process group because git forks
        git-remote-https, which inherits the pipe and outlives a plain kill.
        Arguments:
            *args (str): Arguments after "git".
            cwd (Path | None): Working directory; the repository root by default.
            timeout (float): Seconds before the command is killed.
        '''
        directory = cwd or self.__root
        try:
            process = await asyncio.create_subprocess_exec(
                "git", *args,
                cwd=str(directory) if directory else None,
                env=self.__child_env(_GIT_ENV),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        except OSError as e:
            return -1, "", str(e)

        try:
            out, err = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            await process.wait()
            return -1, "", f"git {' '.join(args)} timed out"

        code = process.returncode if process.returncode is not None else -1
        return code, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")

    # ── Job bookkeeping + framing ─────────────────────────────────

    def __set_step(self, index: int, state: str) -> None:
        '''
        Marks one step's state and points the job at it.
        Arguments:
            index (int): Index into _STEPS.
            state (str): "pending" | "running" | "done" | "failed".
        '''
        if self.__job is None or not (0 <= index < len(self.__job["steps"])):
            return
        step_id = _STEPS[index][0]
        self.__job["steps"][index]["state"] = state
        self.__job["stepIndex"] = index
        self.__job["stepId"] = step_id
        # Cancelling a checkout is how a half-written index happens, so the
        # frontend is told when the button is meaningless rather than being left
        # to send taps the backend silently drops.
        self.__job["cancellable"] = (state == "running"
                                     and step_id in _CANCELLABLE_STEPS)

    def __finish(self, ok: bool, message: str) -> None:
        '''
        Closes the job out.  Steps still pending are left pending rather than
        marked failed: they never ran, and saying otherwise would point the user
        at the wrong step.
        Arguments:
            ok (bool): Whether the run succeeded.
            message (str): Finnish summary shown in the card.
        '''
        if self.__job is None:
            return
        self.__job["running"] = False
        self.__job["finished"] = True
        self.__job["cancellable"] = False
        self.__job["ok"] = ok
        self.__job["message"] = message
        self.__job["finishedMs"] = int(time.time() * 1000)
        logger.warning("Update finished: ok=%s %s", ok, message)

    def __append_log(self, line: str) -> None:
        '''
        Adds one line to the capped job log.
        Arguments:
            line (str): Raw output line; truncated so one pathological line
                cannot dominate the state document.
        '''
        text = line.rstrip()
        if not text:
            return
        if len(text) > _LOG_LINE_CHARS:
            text = text[:_LOG_LINE_CHARS] + "…"
        self.__log.append(text)

    async def __refuse(self, message: str) -> None:
        '''
        Publishes a refusal as a finished, failed job so the card explains itself
        the same way a real failure does.
        Arguments:
            message (str): Finnish reason, shown verbatim.
        '''
        # A refusal must never overwrite a run that is happening. It replaces
        # self.__job wholesale, so doing that mid-run would erase the progress
        # the card is showing, make `busy` false (re-arming the restart button
        # this service vetoes for), leave the run uncancellable, and hand the
        # step loop an empty steps list to index into. The refusing client's own
        # card is already showing the live job, which IS the explanation for why
        # its tap did nothing.
        if self.__job is not None and not self.__job.get("finished"):
            logger.warning("Update refusal suppressed (run in flight): %s", message)
            return
        logger.warning("Update refused: %s", message)
        now = int(time.time() * 1000)
        self.__job_seq += 1
        self.__job = {
            "id": self.__job_seq,
            "running": False,
            "finished": True,
            "ok": False,
            "cancellable": False,
            "stepId": "",
            "stepIndex": 0,
            "channel": "",
            "targetLabel": "",
            "targetCommit": "",
            "previousCommit": "",
            "verdict": "",
            "startedMs": now,
            "finishedMs": now,
            "message": message,
            "restartFrontend": False,
            "steps": [],
            "log": [],
        }
        self.__log.clear()
        await self.__broadcast(force=True)

    async def __broadcast(self, force: bool = False) -> None:
        '''
        Broadcasts the current state, coalescing the stream of build output.
        Arguments:
            force (bool): Send regardless of the rate limit — used for every step
                transition and for the final result, which must never be the
                update that got throttled away.
        '''
        now = time.monotonic()
        if not force and (now - self.__last_broadcast) < _BROADCAST_MIN_INTERVAL:
            return
        self.__last_broadcast = now
        await self.__server.broadcast(self.__state_frame())

    def __state_frame(self) -> bytes:
        '''Builds an UPDATE_STATE packet from the current state and job.'''
        document = dict(self.__state) if self.__state else self.__unavailable_state()
        if self.__job is not None:
            job = dict(self.__job)
            job["log"] = list(self.__log)
            document["job"] = job
        else:
            document["job"] = None

        body = json.dumps(document, ensure_ascii=False).encode("utf-8")
        payload = bytes((protocol.CONFIG_STATUS_OK,)) + len(body).to_bytes(4, "big") + body
        return protocol.frame(protocol.UPDATE_STATE, payload)

    @staticmethod
    def __decode_json(payload: bytes, label: str) -> dict | None:
        '''
        Parses a len(4B) + UTF-8 JSON request body.
        Arguments:
            payload (bytes): The raw handler payload.
            label (str): Packet name, for the warning line.
        '''
        if len(payload) < 4:
            logger.warning("%s: payload too short (%d bytes)", label, len(payload))
            return None
        length = int.from_bytes(payload[:4], "big")
        if len(payload) < 4 + length:
            logger.warning("%s: truncated body", label)
            return None
        try:
            body = json.loads(payload[4:4 + length].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            logger.warning("%s: malformed JSON (%s)", label, e)
            return None
        return body if isinstance(body, dict) else None
