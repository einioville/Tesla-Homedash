'''
The backend's own log files: their size, and clearing them (Ylläpito > Lokit).

The files are utils.logger_configurator's — a size-capped backend.log with its
rotated backups, and the structured WARNING+ store behind the Järjestelmän tila
error lists.  Clearing comes in two strengths: everything, or everything but the
warnings and errors, which are what a later look at a problem needs.  The
journal is never touched; it is the host's, holds everything else running there,
and deletes nothing selectively.

The frontend clears its own files itself (they are local to wherever it runs);
this only answers for the backend's.
'''

import asyncio
import glob
import logging
import os

from ..utils import logger_configurator as logs
from ..utils import protocol
from ..utils.atomic_write import write_atomic

logger = logging.getLogger("system_service.log_files")

# The level column every line of the formatter starts with ("WARNING | …"). A
# line without one continues the record above it — a traceback.
_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
_KEPT_LEVELS = ("WARNING", "ERROR", "CRITICAL")


def _record_level(line: str) -> str | None:
    '''
    The level a log line starts with, or None for a continuation line.
    Arguments:
        line (str): One line of a log file.
    '''
    head = line.split(" | ", 1)[0]
    return head if head in _LEVELS else None


def filter_warnings(lines) -> list[str]:
    '''
    The lines of the records at WARNING or above, each with its continuation
    lines (a traceback stays with the record that logged it).
    Arguments:
        lines (Iterable[str]): A log file's lines, newlines included.
    '''
    kept = []
    keeping = False
    for line in lines:
        level = _record_level(line)
        if level is not None:
            keeping = level in _KEPT_LEVELS
        if keeping:
            kept.append(line)
    return kept


class LogFiles:
    '''
    Serves LOG_CLEAR and reports the log files' size and place for the Loki
    card.
    Arguments:
        server (Server): TCP server, used only to reply to the requesting client.
    '''

    def __init__(self, server):
        self.__server = server
        self.__directory = logs.log_dir()

    @property
    def directory(self) -> str:
        '''Where the files live.'''
        return self.__directory

    def size_bytes(self) -> int:
        '''The backend's log files' combined size on disk.'''
        total = 0
        for path in self.__paths() + [os.path.join(self.__directory, logs.ERROR_LOG_NAME)]:
            try:
                total += os.path.getsize(path)
            except OSError:
                pass
        return total

    async def handle_clear(self, payload: bytes, writer) -> None:
        '''
        LOG_CLEAR handler.  The file work runs in a worker thread: a rewrite of
        a few megabytes is not something to do on the event loop.
        Arguments:
            payload (bytes): len(4B) + JSON {"keep": "warnings" | "none"}.
            writer (StreamWriter): The requesting client.
        '''
        try:
            keep_warnings = protocol.parse_json_body(payload).get("keep") == "warnings"
        except ValueError:
            await self.__reply(writer, False, 0, "Virheellinen pyyntö")
            return
        try:
            freed = await asyncio.to_thread(self.__clear, keep_warnings)
        except OSError as e:
            logger.error("Could not clear the log files: %s", e)
            await self.__reply(writer, False, 0, f"Lokien tyhjennys epäonnistui: {e}")
            return
        logger.info("Log files cleared from the Options view (%s), %d bytes freed",
                       "warnings kept" if keep_warnings else "everything", freed)
        await self.__reply(writer, True, freed, "")

    # ── Internals ─────────────────────────────────────────────────

    def __paths(self) -> list[str]:
        '''backend.log and its rotated backups.'''
        active = os.path.join(self.__directory, logs.LOG_FILE_NAME)
        return [active] + sorted(glob.glob(active + ".*"))

    def __clear(self, keep_warnings: bool) -> int:
        '''
        Clears the files; returns the bytes freed.  The active file is rewritten
        IN PLACE under the handler's lock rather than replaced: the handler holds
        it open in append mode, so it keeps writing to the same file afterwards
        instead of to a deleted one.
        Arguments:
            keep_warnings (bool): Keep the WARNING+ records instead of everything.
        '''
        before = self.size_bytes()
        active, *backups = self.__paths()
        handler = logs.log_file_handler()

        if handler is not None:
            handler.acquire()
        try:
            self.__rewrite_in_place(active, keep_warnings)
        finally:
            if handler is not None:
                handler.release()

        for path in backups:
            if keep_warnings:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    kept = filter_warnings(fh)
                if kept:
                    write_atomic(path, "".join(kept))
                    continue
            os.remove(path)

        # The structured store IS the warnings and errors, so keeping them
        # means leaving it be.
        if not keep_warnings:
            logs.error_log().clear()
        return max(0, before - self.size_bytes())

    @staticmethod
    def __rewrite_in_place(path: str, keep_warnings: bool) -> None:
        '''
        Truncates a file to its kept lines without changing its inode.
        Arguments:
            path (str): The file.
            keep_warnings (bool): Keep the WARNING+ records instead of nothing.
        '''
        try:
            with open(path, "r+", encoding="utf-8", errors="replace") as fh:
                kept = filter_warnings(fh) if keep_warnings else []
                fh.seek(0)
                fh.truncate()
                fh.writelines(kept)
        except FileNotFoundError:
            pass

    async def __reply(self, writer, ok: bool, freed: int, message: str) -> None:
        '''Sends LOG_CLEAR_RESULT to the requesting client.'''
        status = protocol.CONFIG_STATUS_OK if ok else protocol.CONFIG_STATUS_ERROR
        await self.__server.send_to(writer, protocol.json_frame(
            protocol.LOG_CLEAR_RESULT, status,
            {"ok": ok, "freedBytes": freed, "message": message}))
