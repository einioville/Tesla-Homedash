'''
Pins what the backend's whole-file rewrites leave on disk: the content, the
permission bits and that no temp file is left behind.  Covers config.json
(Config.save), the Spotify grant record, the ErrorLog compaction and the
rotated log backups that "keep warnings" rewrites.

Runs under pytest, or standalone: `uv run python tests/test_atomic_write.py`.
'''
import json
import logging
import os
import shutil
import stat
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.media_service import spotify_oauth  # noqa: E402
from src.system_service.log_files import LogFiles  # noqa: E402
from src.utils import logger_configurator as logs  # noqa: E402
from src.utils.config_parser import Config  # noqa: E402

TEMPLATE = os.path.join(os.path.dirname(__file__), "..", "..", "config_template.json")


def _mode(path: str) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


def _leftovers(directory: str, keep: set) -> list:
    return sorted(set(os.listdir(directory)) - keep)


def test_config_save():
    directory = tempfile.mkdtemp()
    path = os.path.join(directory, "backend_config.json")
    shutil.copyfile(TEMPLATE, path)
    os.chmod(path, 0o644)
    with open(path, encoding="utf-8") as fh:
        original = fh.read()

    config = Config(path)
    config.set("weatherPlace", "Äänekoski")
    config.save()

    with open(path, encoding="utf-8") as fh:
        written = fh.read()
    with open(path + ".bak", encoding="utf-8") as fh:
        assert fh.read() == original
    expected = json.loads(original)
    expected["weatherPlace"] = "Äänekoski"
    assert written == json.dumps(expected, indent=4, ensure_ascii=False) + "\n"
    assert _mode(path) == 0o600
    assert _leftovers(directory, {"backend_config.json", "backend_config.json.bak"}) == []


def test_grant_record():
    directory = tempfile.mkdtemp()
    cache = os.path.join(directory, ".spotify-cache")
    config = SimpleNamespace(spotify_cache_path=cache)
    spotify_oauth.write_grant_record(config, {"email": "a@b.fi", "displayName": "Ö", "id": "u1"})
    path = cache + ".grant.json"
    with open(path, encoding="utf-8") as fh:
        record = json.loads(fh.read())
    assert set(record) == {"authorizedAt", "email", "displayName", "userId"}
    assert (record["email"], record["displayName"], record["userId"]) == ("a@b.fi", "Ö", "u1")
    assert _mode(path) == 0o600
    assert _leftovers(directory, {".spotify-cache.grant.json"}) == []


def test_error_log_compaction():
    directory = tempfile.mkdtemp()
    path = os.path.join(directory, "backend-errors.jsonl")
    store = logs.ErrorLog()
    store.MAX_ENTRIES = 3
    store._ErrorLog__entries = __import__("collections").deque(maxlen=3)
    store.attach_file(path)
    for n in range(7):
        store.emit(logging.LogRecord("svc", logging.WARNING, __file__, 1, f"w{n}ä", None, None))
    with open(path, encoding="utf-8") as fh:
        lines = [json.loads(line) for line in fh]
    # Compacted to the three newest at the seventh entry, which is then kept too.
    assert [entry["message"] for entry in lines] == ["w4ä", "w5ä", "w6ä"]
    assert _leftovers(directory, {"backend-errors.jsonl"}) == []


def test_log_backups_keep_warnings():
    directory = tempfile.mkdtemp()
    os.environ["TESLA_HOMEDASH_LOG_DIR"] = directory
    try:
        active = os.path.join(directory, logs.LOG_FILE_NAME)
        record = "{} | 2026-10-10 | 12:00:00 | svc | {}\n"
        with open(active, "w", encoding="utf-8") as fh:
            fh.write(record.format("INFO", "a"))
        with open(active + ".1", "w", encoding="utf-8") as fh:
            fh.write(record.format("INFO", "b") + record.format("WARNING", "c") + "  trace\n")
        with open(active + ".2", "w", encoding="utf-8") as fh:
            fh.write(record.format("INFO", "d"))
        LogFiles(server=None)._LogFiles__clear(True)
        with open(active + ".1", encoding="utf-8") as fh:
            assert fh.read() == record.format("WARNING", "c") + "  trace\n"
        assert not os.path.exists(active + ".2")
        assert _leftovers(directory, {logs.LOG_FILE_NAME, logs.LOG_FILE_NAME + ".1"}) == []
    finally:
        del os.environ["TESLA_HOMEDASH_LOG_DIR"]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS  {test.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL  {test.__name__}: {e}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(1 if failures else 0)
