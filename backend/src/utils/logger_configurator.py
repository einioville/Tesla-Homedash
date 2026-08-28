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
        # Do not propagate to the root logger — each service logger is self-contained.
        logger.propagate = False

    # Warn only now that the handlers exist, so the message is formatted like
    # every other log line instead of hitting logging's lastResort handler.
    if invalid is not None:
        logging.getLogger(UTILS).warning(
            "Invalid %s=%r; falling back to INFO (valid: %s)",
            _LOG_LEVEL_ENV, invalid, ", ".join(_LEVEL_NAMES),
        )
