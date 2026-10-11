'''
The log level, chosen in the Options view (Ylläpito > Lokit).

`logging.level` in config.json sets every backend service logger and the log file;
the frontend reads the same key out of the schema and follows it, so one dropdown
covers both halves.  The journal follows it too but never below INFO
(utils/logger_configurator.set_log_level), so DEBUG detail goes to the app's
size-capped log files only.

DEBUG is TEMPORARY by design: it logs a line per telemetry property, which fills
the log file fast enough to rotate away the warnings that came before.  After
logging.debugMinutes (0 = *toistaiseksi*, no end) this service writes the level
DEBUG came from (logging.levelBeforeDebug) back through ConfigService.  See
CLAUDE.md beside this file.
'''
import asyncio
import logging
import time

from ..utils.logger_configurator import default_level_name, set_log_level

logger = logging.getLogger("system_service.log_level")


class LogLevel:
    '''
    Applies logging.level / logging.debugMinutes and returns from DEBUG to the
    previous level once the duration has passed.

    The countdown starts when DEBUG is chosen AND when a backend process starts
    with it — a restart does not end it, because debugging a startup problem
    needs exactly that, but it cannot make a timed DEBUG permanent either. Only
    choosing *toistaiseksi* (minutes 0) does that, on purpose.
    Arguments:
        config (Config): Shared configuration (the logging block).
        config_service (ConfigService): Writes the level back on expiry.
        log_files (LogFiles): The log files' size and place, for the status card.
    '''

    def __init__(self, config, config_service, log_files):
        self.__config = config
        self.__config_service = config_service
        self.__log_files = log_files
        # The level in force; None until the first apply_config().
        self.__level: str | None = None
        self.__timer: asyncio.Task | None = None
        # When the DEBUG countdown ends (epoch ms), None while not at DEBUG or
        # while at DEBUG with no end (toistaiseksi).
        self.__until_ms: int | None = None
        self.__indefinite = False

    def apply_config(self) -> None:
        '''
        Re-reads the logging block, sets the level to match and (re)arms the
        DEBUG expiry.  Registered as the "logging" config hook, and called once
        from start_services (the class docstring has why).  A duration change
        while at DEBUG restarts the countdown from now.  Must run on the event
        loop.
        '''
        block = self.__config.logging_config
        level = block["level"]
        # 0 is toistaiseksi: DEBUG until the level is changed.
        raw = block.get("debugMinutes")
        minutes = 30 if raw is None else max(0, int(raw))

        if level != self.__level:
            # Remember where DEBUG came from — but not on the first apply, where
            # the level being "left" is only the environment's: a DEBUG kept
            # across a restart still returns to what was chosen before it.
            if level == "debug" and self.__level is not None:
                self.__remember_return_level(self.__level)
            # Logged after the switch on the way to DEBUG and before it on the way
            # back, so the line lands in the log file either way. INFO, not
            # WARNING: a deliberate change is no problem, and the Järjestelmän
            # tila cards count every warning as one.
            if level == "debug":
                set_log_level(level)
                logger.info("Log level %s -> debug %s (Options view)", self.__level,
                            f"for {minutes} min" if minutes else "until changed")
            else:
                logger.info("Log level %s -> %s (Options view)", self.__level, level)
                set_log_level(level)
            self.__level = level

        self.__cancel_timer()
        self.__until_ms = None
        self.__indefinite = level == "debug" and minutes == 0
        if level == "debug" and minutes > 0:
            self.__until_ms = int(time.time() * 1000) + minutes * 60 * 1000
            self.__timer = asyncio.create_task(self.__expire_after(minutes * 60))

    def __remember_return_level(self, level: str) -> None:
        '''
        Stores the level DEBUG returns to.  State rather than a setting, so it
        goes straight through Config — like the radio's last station — and is in
        no schema.
        Arguments:
            level (str): The level being left for DEBUG.
        '''
        self.__config.set("logging.levelBeforeDebug", level)
        try:
            self.__config.save()
        except OSError as e:
            logger.warning("Could not save the level to return to: %s", e)

    def __return_level(self) -> str:
        '''The level DEBUG returns to: the remembered one, else the startup level.'''
        level = self.__config.logging_config.get("levelBeforeDebug") or default_level_name()
        return "info" if level == "debug" else level

    def __cancel_timer(self) -> None:
        '''Stops a pending expiry, if any.'''
        if self.__timer is not None:
            self.__timer.cancel()
            self.__timer = None

    async def __expire_after(self, seconds: float) -> None:
        '''
        Sleeps out the duration, then writes the previous level back through
        ConfigService.  The write's own hook call is what changes the level, so
        the level, config.json and every open Options view change together.
        Arguments:
            seconds (float): How long DEBUG lasts.
        '''
        try:
            await asyncio.sleep(seconds)
        except asyncio.CancelledError:
            return
        # Dropped first: the write re-enters apply_config(), which would
        # otherwise cancel this very task mid-write.
        self.__timer = None
        target = self.__return_level()
        logger.info("DEBUG duration elapsed; returning to %s", target)
        result = await self.__config_service.apply_write("logging.level", target)
        if not result.get("ok"):
            # The file could not be written. Change the level anyway: the point
            # of the timer is the log file, not the dropdown.
            logger.error("Could not write logging.level back: %s", result.get("message"))
            set_log_level(target)
            self.__level = target
            self.__until_ms = None

    def runtime_info(self) -> dict:
        '''
        What the logging.level row shows beside its value while at DEBUG: when it
        returns, and to which level — or that it does not (toistaiseksi).  Merged
        into the schema entry by ConfigService.
        '''
        if self.__indefinite:
            return {"indefinite": True}
        if self.__until_ms is None:
            return {}
        return {"until": self.__until_ms, "returnTo": self.__return_level()}

    def health(self) -> dict:
        '''Reports the level in force and the log files, for the Loki card.'''
        config = [["Taso", (self.__level or default_level_name()).upper()]]
        if self.__indefinite:
            config.append(["Kesto", "Toistaiseksi"])
        if self.__until_ms is not None:
            config.append(["Palautuu", {"time": self.__until_ms}])
            config.append(["Palautuu tasolle", self.__return_level().upper()])
        config.append(["Lokitiedostot", {"bytes": self.__log_files.size_bytes()}])
        config.append(["Kansio", self.__log_files.directory])
        if self.__level == "debug":
            return {"state": "warn", "detail": "DEBUG-taso päällä", "config": config}
        return {"state": "ok", "detail": "Normaali", "config": config}
