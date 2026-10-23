import collections
import json
import logging
import logging.handlers
import os
import threading

from dotenv import load_dotenv

from .atomic_write import write_atomic

# ── Logger name constants ─────────────────────────────────────────────────────

TESLA_SERVICE = "tesla_service"
MEDIA_SERVICE = "media_service"
WEATHER_SERVICE = "weather_service"
INFLUXDB_SERVICE = "influxdb_service"
CHARGING_SERVICE = "charging_service"
MYENERGI_SERVICE = "myenergi_service"
TRIP_SERVICE = "trip_service"
CONFIG_SERVICE = "config_service"
AUDIO_SERVICE = "audio_service"
DISPLAY_SERVICE = "display_service"
SYSTEM_SERVICE = "system_service"
UPDATE_SERVICE = "update_service"
USB_IMPORT_SERVICE = "usb_import_service"
AUTH_SERVICE = "auth_service"
SERVER = "server"
START_SERVICES = "start_services"
UTILS = "utils"

# ── Format ────────────────────────────────────────────────────────────────────

_LOG_FORMAT = "%(levelname)s | %(asctime)s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d | %H:%M:%S"

_SERVICE_LOGGERS = (
    TESLA_SERVICE,
    MEDIA_SERVICE,
    WEATHER_SERVICE,
    INFLUXDB_SERVICE,
    CHARGING_SERVICE,
    MYENERGI_SERVICE,
    TRIP_SERVICE,
    CONFIG_SERVICE,
    AUDIO_SERVICE,
    DISPLAY_SERVICE,
    SYSTEM_SERVICE,
    UPDATE_SERVICE,
    USB_IMPORT_SERVICE,
    AUTH_SERVICE,
    SERVER,
    START_SERVICES,
    UTILS,
)


_LOG_LEVEL_ENV = "TESLA_HOMEDASH_LOG_LEVEL"

_LEVEL_NAMES = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}

_DEFAULT_LEVEL = logging.INFO

# The Options view's level choices, as stored in config.json (logging.level).
LEVEL_CHOICES = tuple(_LEVEL_NAMES)


def _resolve_level() -> tuple[int, str | None]:
    '''
    Reads the log level from TESLA_HOMEDASH_LOG_LEVEL, mirroring the frontend's
    variable of the same name.  Returns the level plus the offending string when
    the value was unrecognised, so the caller can warn once handlers exist.
    Unset or invalid falls back to INFO — DEBUG emits a line per telemetry
    property, which on the embedded deployment rotates the systemd journal fast
    enough to destroy incident history.
    '''
    raw = os.getenv(_LOG_LEVEL_ENV)
    if raw is None:
        return _DEFAULT_LEVEL, None
    level = _LEVEL_NAMES.get(raw.strip().lower())
    if level is None:
        return _DEFAULT_LEVEL, raw
    return level, None


# ── The app's own log files ───────────────────────────────────────────────────
#
# Beside stdout (the journal), every record at the loggers' level goes to a
# size-capped file in the app's state directory, and every WARNING+ record to a
# structured error log there.  stdout follows the chosen level but never below
# INFO unless the process was started at DEBUG, so the Options view's DEBUG detail
# lands only in the file — which the Options view can clear
# (system_service/log_files.py), unlike journald, which holds everything on the
# host and deletes nothing selectively.

_LOG_DIR_ENV = "TESLA_HOMEDASH_LOG_DIR"

LOG_FILE_NAME = "backend.log"
ERROR_LOG_NAME = "backend-errors.jsonl"
# 4 × 5 MB: room for hours of DEBUG on the Pi without a disk to worry about.
LOG_FILE_MAX_BYTES = 5 * 1024 * 1024
LOG_FILE_BACKUPS = 3


def log_dir() -> str:
    '''
    The directory both halves keep their log files in: TESLA_HOMEDASH_LOG_DIR,
    else $XDG_STATE_HOME (or ~/.local/state) /Tesla-Homedash/logs.  The
    frontend resolves the same path, so the files sit side by side.
    '''
    override = os.getenv(_LOG_DIR_ENV)
    if override:
        return override
    state = os.getenv("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return os.path.join(state, "Tesla-Homedash", "logs")


class ErrorLog(logging.Handler):
    '''
    Keeps every WARNING-and-worse record — level, time, full logger name and
    text — in memory and in a JSON-lines file, so the Järjestelmän tila cards
    can count each service's problems and list them, across restarts.

    Attached to the same allow-listed loggers as the stdout handler, which is
    also what stops double counting: those loggers set propagate = False, so no
    record reaches a root handler as well.  Bounded to MAX_ENTRIES, oldest
    first out; the file is compacted back to that once it holds twice as many.
    '''

    MAX_ENTRIES = 2000
    # A traceback can run to pages; the list shows the gist.
    _MAX_MESSAGE = 4000

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.__entries: collections.deque = collections.deque(maxlen=self.MAX_ENTRIES)
        self.__path: str | None = None
        self.__lines_on_disk = 0
        # Guards the deque and the file against readers on the event loop while
        # a worker thread (spotipy runs in executors) is emitting.
        self.__mutex = threading.Lock()

    def attach_file(self, path: str) -> None:
        '''
        Loads what an earlier run recorded and appends to the same file from
        now on.  A line that does not parse (a write cut short by a power cut)
        is skipped rather than failing startup.
        Arguments:
            path (str): The JSON-lines file.
        '''
        loaded = []
        lines = 0
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    lines += 1
                    try:
                        entry = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(entry, dict) and "t" in entry:
                        loaded.append(entry)
        except FileNotFoundError:
            pass
        with self.__mutex:
            self.__entries.extend(loaded[-self.MAX_ENTRIES:])
            self.__lines_on_disk = lines
            self.__path = path

    def emit(self, record: logging.LogRecord) -> None:
        '''
        Stores one record.
        Arguments:
            record (LogRecord): The record being logged.
        '''
        try:
            # Resolves lazy %s arguments, so the stored line is the finished text.
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        if record.exc_info:
            message += "\n" + logging.Formatter().formatException(record.exc_info)
        entry = {
            "t": int(record.created * 1000),
            "level": record.levelname,
            "logger": record.name,
            "message": message[:self._MAX_MESSAGE],
        }
        with self.__mutex:
            self.__entries.append(entry)
            self.__append_to_file(entry)

    def __append_to_file(self, entry: dict) -> None:
        '''Appends one entry, compacting the file when it has grown past twice the cap.'''
        if self.__path is None:
            return
        try:
            if self.__lines_on_disk >= 2 * self.MAX_ENTRIES:
                self.__rewrite()
            else:
                with open(self.__path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
                self.__lines_on_disk += 1
        except OSError:
            # A full or read-only disk must not turn every warning into an
            # exception inside logging; the in-memory list still works.
            pass

    def __rewrite(self) -> None:
        '''Writes the in-memory entries back as the whole file, atomically.'''
        write_atomic(self.__path, "".join(
            json.dumps(entry, ensure_ascii=False) + "\n" for entry in self.__entries))
        self.__lines_on_disk = len(self.__entries)

    def entries(self, match=None) -> list[dict]:
        '''
        The stored entries, newest first.
        Arguments:
            match (Callable | None): Keeps an entry when match(logger_name) is true.
        '''
        with self.__mutex:
            entries = list(self.__entries)
        if match is not None:
            entries = [entry for entry in entries if match(entry["logger"])]
        entries.reverse()
        return entries

    def counts(self, match, open_since: int | None, past_since: int) -> dict:
        '''
        One card's tallies over the entries whose logger matches:
        {"warnings": n, "errors": m} over the open ones, logged at or after
        open_since, and "past": how many earlier ones were logged at or after
        past_since.  An error is ERROR or CRITICAL.
        Arguments:
            match (Callable): match(logger_name) -> bool.
            open_since (int | None): Epoch ms where the open entries begin; None
                when nothing is open.
            past_since (int): Epoch ms where the past count begins.
        '''
        warnings = errors = past = 0
        with self.__mutex:
            for entry in self.__entries:
                if not match(entry["logger"]):
                    continue
                if open_since is not None and entry["t"] >= open_since:
                    if entry["level"] in ("ERROR", "CRITICAL"):
                        errors += 1
                    else:
                        warnings += 1
                elif entry["t"] >= past_since:
                    past += 1
        return {"warnings": warnings, "errors": errors, "past": past}

    def clear(self) -> int:
        '''
        Forgets every entry and empties the file.  Returns the bytes freed.
        '''
        with self.__mutex:
            self.__entries.clear()
            freed = 0
            if self.__path is not None:
                try:
                    freed = os.path.getsize(self.__path)
                    with open(self.__path, "w", encoding="utf-8"):
                        pass
                except OSError:
                    freed = 0
            self.__lines_on_disk = 0
        return freed


# Shared by every allow-listed logger, and read by the system status service.
_error_log = ErrorLog()
# The size-capped file every allow-listed logger writes; None when the log
# directory could not be created (the journal still gets everything).
_file_handler: logging.handlers.RotatingFileHandler | None = None

# The level configure_logging() applied — what the process was started with.
_base_level = _DEFAULT_LEVEL
# The journal's handler, whose level set_log_level() keeps at INFO or above.
_stdout_handler: logging.Handler | None = None


def error_log() -> ErrorLog:
    '''Returns the shared WARNING+ store for the system status service.'''
    return _error_log


def default_level_name() -> str:
    '''
    The level TESLA_HOMEDASH_LOG_LEVEL names ("info" when unset or invalid) —
    the default of the Options view's logging.level, so a deployment keeps the
    level it was started with until the dropdown is used.
    '''
    load_dotenv()
    return logging.getLevelName(_resolve_level()[0]).lower()


def log_file_handler() -> logging.handlers.RotatingFileHandler | None:
    '''Returns the backend's log-file handler, for clearing its file in place.'''
    return _file_handler


def configure_logging() -> None:
    '''
    Configures all service loggers with a shared StreamHandler and formatter, at
    the level TESLA_HOMEDASH_LOG_LEVEL names (INFO when unset or invalid).
    Must be called once at application startup before any service is initialised.
    '''
    global _base_level
    # `.env` is normally loaded lazily by config_parser.get_env, whose first
    # call happens *after* logging is configured — so load it here too.
    # load_dotenv is idempotent and does not override real env vars, which is
    # what lets systemd's Environment= win over a stale `.env` on the Pi.
    load_dotenv()
    level, invalid = _resolve_level()

    global _file_handler, _stdout_handler
    _base_level = level
    formatter = logging.Formatter(fmt=_LOG_FORMAT, datefmt=_DATE_FORMAT)
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    handler.setLevel(level)
    if _stdout_handler is None:
        _stdout_handler = handler

    file_error: OSError | None = None
    if _file_handler is None:
        try:
            directory = log_dir()
            os.makedirs(directory, exist_ok=True)
            _file_handler = logging.handlers.RotatingFileHandler(
                os.path.join(directory, LOG_FILE_NAME), maxBytes=LOG_FILE_MAX_BYTES,
                backupCount=LOG_FILE_BACKUPS, encoding="utf-8")
            _file_handler.setFormatter(formatter)
            _error_log.attach_file(os.path.join(directory, ERROR_LOG_NAME))
        except OSError as e:
            file_error = e
            _file_handler = None

    for name in _SERVICE_LOGGERS:
        logger = logging.getLogger(name)
        logger.setLevel(level)
        # A second call must not stack a second stdout handler.
        if not logger.handlers:
            logger.addHandler(handler)
        # The file and the WARNING+ store. Added separately from the stdout
        # handler above because they must survive a re-configure that finds
        # handlers already attached.
        if _file_handler is not None and _file_handler not in logger.handlers:
            logger.addHandler(_file_handler)
        if _error_log not in logger.handlers:
            logger.addHandler(_error_log)
        logger.propagate = False

    # spotipy logs its own diagnostics — notably "Couldn't write token to cache",
    # the only evidence that a re-authorization silently lost the grant — and as a
    # third-party name it is not in _SERVICE_LOGGERS, so those records fall to a
    # handler-less root and vanish. Attach the same handlers, but PIN the level:
    # at DEBUG spotipy prints the token POST body and the base64 Authorization
    # header carrying SPOTIFY_CLIENT_ID:SPOTIFY_CLIENT_SECRET, the authorization
    # code and the refresh token — straight into the Pi's journal.
    spotipy_logger = logging.getLogger("spotipy")
    spotipy_logger.setLevel(max(level, logging.INFO))
    if not any(h is handler for h in spotipy_logger.handlers):
        spotipy_logger.addHandler(handler)
    if _file_handler is not None and _file_handler not in spotipy_logger.handlers:
        spotipy_logger.addHandler(_file_handler)
    if _error_log not in spotipy_logger.handlers:
        spotipy_logger.addHandler(_error_log)
    spotipy_logger.propagate = False

    # Warn only now that the handlers exist, so the message is formatted like
    # every other log line instead of hitting logging's lastResort handler.
    if invalid is not None:
        logging.getLogger(UTILS).warning(
            "Invalid %s=%r; falling back to INFO (valid: %s)",
            _LOG_LEVEL_ENV, invalid, ", ".join(_LEVEL_NAMES),
        )
    if file_error is not None:
        logging.getLogger(UTILS).warning(
            "No log file (%s); logging to stdout only", file_error)


def set_log_level(name: str) -> None:
    '''
    Applies the Options view's log level (logging.level) to every allow-listed
    service logger and the log file.  The journal follows it too, but never below
    INFO — unless the process was started at DEBUG — so the temporary DEBUG level
    lands in the size-capped file only (system_service/log_level.py owns the
    timer that ends it).

    spotipy stays pinned at INFO or above: at DEBUG it prints the client secret,
    the authorization code and the refresh token (see configure_logging).
    Arguments:
        name (str): One of LEVEL_CHOICES; anything else is ignored with a warning.
    '''
    level = _LEVEL_NAMES.get(name)
    if level is None:
        logging.getLogger(UTILS).warning("Unknown log level %r ignored", name)
        return
    for logger_name in _SERVICE_LOGGERS:
        logging.getLogger(logger_name).setLevel(level)
    logging.getLogger("spotipy").setLevel(max(level, logging.INFO))
    if _stdout_handler is not None:
        _stdout_handler.setLevel(max(level, min(_base_level, logging.INFO)))
