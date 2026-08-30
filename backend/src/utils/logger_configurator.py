import collections
import logging
import os

from dotenv import load_dotenv

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


class ErrorCounter(logging.Handler):
    '''
    Counts WARNING-and-worse records per top-level service logger and keeps the
    most recent few verbatim, so the Options view's status page can answer "has
    anything gone wrong since boot, and what".

    Attached to the same allow-listed loggers as the stdout handler, which is
    also what stops double counting: those loggers set propagate = False, so no
    record reaches a root handler as well.
    Arguments:
        keep (int): How many recent records to retain for display.
    '''

    def __init__(self, keep: int = 8):
        super().__init__(level=logging.WARNING)
        self.counts: collections.Counter = collections.Counter()
        self.recent: collections.deque = collections.deque(maxlen=keep)
        self.total = 0

    def emit(self, record: logging.LogRecord) -> None:
        '''
        Buckets one record by its top-level logger name and stores its text.
        Arguments:
            record (LogRecord): The record being logged.
        '''
        top = record.name.split(".", 1)[0]
        self.counts[top] += 1
        self.total += 1
        try:
            # Resolves lazy %s arguments, so the stored line is the finished text.
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        self.recent.append({
            "ts_ms": int(record.created * 1000),
            "level": record.levelname,
            "logger": top,
            "message": message[:200],
        })

    def snapshot(self) -> dict:
        '''Returns the tallies as a plain JSON-safe dict for the status document.'''
        return {
            "total": self.total,
            "by_logger": dict(self.counts),
            "recent": list(self.recent),
        }


# Shared by every allow-listed logger, and read by the system status service.
_error_counter = ErrorCounter()


def error_counter() -> ErrorCounter:
    '''Returns the shared WARNING+ counter for the system status service.'''
    return _error_counter


def configure_logging(level: int | None = None) -> None:
    '''
    Configures all service loggers with a shared StreamHandler and formatter.
    Must be called once at application startup before any service is initialised.
    Arguments:
        level (int): Minimum log level for all service loggers.  When None (the
            default) the level comes from TESLA_HOMEDASH_LOG_LEVEL, falling back
            to INFO.
    '''
    invalid: str | None = None
    if level is None:
        # `.env` is normally loaded lazily by config_parser.get_env, whose first
        # call happens *after* logging is configured — so load it here too.
        # load_dotenv is idempotent and does not override real env vars, which is
        # what lets systemd's Environment= win over a stale `.env` on the Pi.
        load_dotenv()
        level, invalid = _resolve_level()

    formatter = logging.Formatter(fmt=_LOG_FORMAT, datefmt=_DATE_FORMAT)
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    for name in _SERVICE_LOGGERS:
        logger = logging.getLogger(name)
        logger.setLevel(level)
        # Guard against duplicate handlers when configure_logging() is called
        # more than once (e.g. during tests).
        if not logger.handlers:
            logger.addHandler(handler)
        # The WARNING+ tally the status view reports. Added separately from the
        # stdout handler above because it must survive a re-configure that finds
        # handlers already attached.
        if not any(isinstance(h, ErrorCounter) for h in logger.handlers):
            logger.addHandler(_error_counter)
        # Do not propagate to the root logger — each service logger is self-contained.
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
    if not any(isinstance(h, ErrorCounter) for h in spotipy_logger.handlers):
        spotipy_logger.addHandler(_error_counter)
    spotipy_logger.propagate = False

    # Warn only now that the handlers exist, so the message is formatted like
    # every other log line instead of hitting logging's lastResort handler.
    if invalid is not None:
        logging.getLogger(UTILS).warning(
            "Invalid %s=%r; falling back to INFO (valid: %s)",
            _LOG_LEVEL_ENV, invalid, ", ".join(_LEVEL_NAMES),
        )
