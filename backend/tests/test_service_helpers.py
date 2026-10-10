'''
Pins small helpers several services share in spirit: the XDG config folder both
config.json and the screensaver photos live under, the flow/scan epoch a request
carries, the job document an update refusal publishes, and the log-level choices
the Options view offers.

Runs under pytest, or standalone: `uv run python tests/test_service_helpers.py`.
'''
import asyncio
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.config_service.config_service import ConfigService  # noqa: E402
from src.update_service.update_service import UpdateService  # noqa: E402
from src.usb_import_service.usb_import_service import screensaver_dir  # noqa: E402
from src.utils import protocol  # noqa: E402
from src.utils.config_parser import Config, default_config_path  # noqa: E402

TEMPLATE = os.path.join(os.path.dirname(__file__), "..", "..", "config_template.json")


def test_config_folder_follows_xdg():
    saved = os.environ.pop("XDG_CONFIG_HOME", None)
    try:
        home = os.path.join(os.path.expanduser("~"), ".config", "Tesla-Homedash")
        assert default_config_path() == os.path.join(home, "backend_config.json")
        assert screensaver_dir() == os.path.join(home, "screensaver")
        os.environ["XDG_CONFIG_HOME"] = "/x/cfg"
        assert default_config_path() == "/x/cfg/Tesla-Homedash/backend_config.json"
        assert screensaver_dir() == "/x/cfg/Tesla-Homedash/screensaver"
    finally:
        os.environ.pop("XDG_CONFIG_HOME", None)
        if saved is not None:
            os.environ["XDG_CONFIG_HOME"] = saved


def test_request_epochs():
    for key in ("flowId", "scanId"):
        read = lambda value, key=key: protocol.request_epoch({key: value}, key)  # noqa: E731
        assert [read(v) for v in (7, 0, -1, True, "7", 2.0, None)] == [7, 0, 0, 0, 0, 0, 0]
        assert protocol.request_epoch({}, key) == 0


class _Server:
    async def broadcast(self, _data):
        '''Accepts a broadcast.'''


class _NoVetoes:
    def register_restart_veto(self, _name, _veto):
        '''Accepts the updater's restart veto.'''


def test_update_refusal_job():
    service = UpdateService(server=_Server(), config_service=_NoVetoes())
    asyncio.run(service._UpdateService__refuse("Ei käy"))
    job = service._UpdateService__job
    assert job["startedMs"] == job["finishedMs"] and isinstance(job["startedMs"], int)
    del job["startedMs"], job["finishedMs"]
    assert job == {
        "id": 1, "running": False, "finished": True, "ok": False, "cancellable": False,
        "stepId": "", "stepIndex": 0, "channel": "", "targetLabel": "", "targetCommit": "",
        "previousCommit": "", "verdict": "", "message": "Ei käy", "restartFrontend": False,
        "steps": [], "log": [],
    }


def test_log_level_choices():
    directory = tempfile.mkdtemp()
    path = os.path.join(directory, "backend_config.json")
    shutil.copyfile(TEMPLATE, path)
    service = ConfigService(config=Config(path), server=None)
    settings = [s for g in service.build_schema()["groups"] for sec in g["sections"]
                for s in sec["settings"]]
    level = next(s for s in settings if s["key"] == "logging.level")
    assert level["options"] == [{"value": v, "label": v.upper()}
                                for v in ("debug", "info", "warning", "error", "critical")]


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
