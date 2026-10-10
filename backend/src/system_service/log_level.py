'''
Temporary DEBUG logging, switched from the Options view (Ylläpito > Vianetsintä).

`logging.debugEnabled` in config.json turns DEBUG on for every backend service
logger; the frontend reads the same key out of the schema and follows it, so one
switch covers both halves.  It is TEMPORARY by design: at DEBUG the backend logs a
line per telemetry property, which rotates the Pi's journal fast enough to destroy
the incident history the log was turned on to collect.  So this service arms a
timer and, when it fires, writes the key back to false through ConfigService —
the same validated path a tap takes, so the write is saved atomically and the
fresh schema is broadcast, which is what switches the frontend back too.
'''
import asyncio
import logging

from ..utils.logger_configurator import set_debug_logging

logger = logging.getLogger("system_service.debug_logging")


class DebugLogging:
    '''
    Applies logging.debugEnabled / logging.debugMinutes and switches the debug
    log off again once the duration has passed.

    The countdown starts when the log is switched on AND when a backend process
    starts with it on — a restart does not end debug mode, because debugging a
    startup problem needs exactly that, but it cannot make it permanent either.
    Arguments:
        config (Config): Shared configuration (the logging block).
        config_service (ConfigService): Writes the key back to false on expiry.
    '''

    def __init__(self, config, config_service):
        self.__config = config
        self.__config_service = config_service
        self.__enabled = False
        self.__timer: asyncio.Task | None = None

    def apply_config(self) -> None:
        '''
        Re-reads the logging block, sets the log level to match and (re)arms the
        expiry.  Registered as the "logging" config hook, and called once from
        start_services so a debug log left on survives a restart for at most one
        more duration.  A duration change while the log is on restarts the
        countdown from now.  Must run on the event loop.
        '''
        block = self.__config.logging_config
        enabled = bool(block.get("debugEnabled"))
        minutes = max(1, int(block.get("debugMinutes") or 30))

        if enabled != self.__enabled:
            # Logged at WARNING on the way in so the line survives any level,
            # and before the switch on the way out for the same reason.
            if enabled:
                set_debug_logging(True)
                logger.warning("Debug logging ON for %d min (Options view)", minutes)
            else:
                logger.warning("Debug logging OFF")
                set_debug_logging(False)
            self.__enabled = enabled

        self.__cancel_timer()
        if enabled:
            self.__timer = asyncio.create_task(self.__expire_after(minutes * 60))

    def __cancel_timer(self) -> None:
        '''Stops a pending expiry, if any.'''
        if self.__timer is not None:
            self.__timer.cancel()
            self.__timer = None

    async def __expire_after(self, seconds: float) -> None:
        '''
        Sleeps out the duration, then clears logging.debugEnabled through
        ConfigService.  The write's own hook call is what lowers the level, so
        the level, config.json and every open Options view change together.
        Arguments:
            seconds (float): How long the debug log stays on.
        '''
        try:
            await asyncio.sleep(seconds)
        except asyncio.CancelledError:
            return
        # Dropped first: the write re-enters apply_config(), which would
        # otherwise cancel this very task mid-write.
        self.__timer = None
        logger.info("Debug logging duration elapsed; switching it off")
        result = await self.__config_service.apply_write("logging.debugEnabled", False)
        if not result.get("ok"):
            # The file could not be written. Lower the level anyway: the point
            # of the timer is the journal, not the checkbox.
            logger.error("Could not clear logging.debugEnabled: %s", result.get("message"))
            set_debug_logging(False)
            self.__enabled = False

    def health(self) -> dict:
        '''Reports whether the temporary debug log is currently on.'''
        if self.__enabled:
            return {"state": "warn", "detail": "Vianetsintäloki päällä"}
        return {"state": "ok", "detail": "Normaali"}
