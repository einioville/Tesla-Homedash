import logging

# ── Logger name constants ─────────────────────────────────────────────────────

TESLA_SERVICE = "tesla_service"
MEDIA_SERVICE = "media_service"
WEATHER_SERVICE = "weather_service"
INFLUXDB_SERVICE = "influxdb_service"
UTILS = "utils"

# ── Format ────────────────────────────────────────────────────────────────────

_LOG_FORMAT = "%(levelname)s | %(asctime)s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d | %H:%M:%S"

_SERVICE_LOGGERS = (
    TESLA_SERVICE,
    MEDIA_SERVICE,
    WEATHER_SERVICE,
    INFLUXDB_SERVICE,
    UTILS,
)


def configure_logging(level: int = logging.DEBUG) -> None:
    '''
    Configures all service loggers with a shared StreamHandler and formatter.
    Must be called once at application startup before any service is initialised.
    Arguments:
        level (int): Minimum log level for all service loggers (default: DEBUG).
    '''
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
