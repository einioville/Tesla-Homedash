'''
Tests for panel power and the recovery of a dropped output (#43, #89), run
against fake `wlopm` and `wlr-randr` commands that act out the wedge the
reference Pi shows: after a blank the output is gone from `wlopm --json`, a
native modeset fails with "failed to apply configuration", and a modeset
through 1920x1080 brings it back.

Runs under pytest, or standalone: `python backend/tests/test_display_service.py`.
'''
import asyncio
import json
import os
import sys
import tempfile

# Make `src` importable whether run via pytest or directly.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.display_service import display_service  # noqa: E402
from src.display_service.display_service import DisplayService  # noqa: E402

NATIVE = "1280x800@60.023998"
KICK = "1920x1080@60.000000"

# Both fakes keep the panel in one JSON file and log every call into it.
# `revive` is the mode that brings a dropped output back ("never" for none);
# `native_refused` makes the native modeset fail even on a present output.
_FAKE_WLOPM = '''
import json, os, sys
path = os.environ["FAKE_DISPLAY_STATE"]
with open(path) as f:
    s = json.load(f)
args = sys.argv[1:]
s["calls"].append(["wlopm"] + args)
out, code = "", 0
if args == ["--json"]:
    out = json.dumps([{"output": "HDMI-A-1", "power-mode": s["power"]}] if s["present"] else [])
elif args and args[0] in ("--on", "--off"):
    if s["present"]:
        s["power"] = "on" if args[0] == "--on" else "off"
        if args[0] == "--off" and s["wedge_on_off"]:
            s.update(present=False, enabled=False)
else:
    code = 2
with open(path, "w") as f:
    json.dump(s, f)
print(out)
sys.exit(code)
'''

_FAKE_RANDR = '''
import json, os, sys
path = os.environ["FAKE_DISPLAY_STATE"]
with open(path) as f:
    s = json.load(f)
args = sys.argv[1:]
s["calls"].append(["wlr-randr"] + args)
out, err, code = "", "", 0
if args == ["--json"]:
    modes = [{"width": 1920, "height": 1080, "refresh": 60.0, "preferred": False},
             {"width": 1280, "height": 800, "refresh": 60.023998, "preferred": False}]
    for m in modes:
        m["current"] = s["enabled"] and "%dx%d@%.6f" % (m["width"], m["height"], m["refresh"]) == s["mode"]
    out = json.dumps([{"name": "HDMI-A-1", "enabled": s["enabled"], "modes": modes}])
elif args[:2] == ["--output", "HDMI-A-1"] and "--mode" in args:
    mode = args[args.index("--mode") + 1]
    native = mode.startswith("1280x800")
    if s["present"] and not (native and s["native_refused"]):
        s["mode"] = mode
    elif not s["present"] and s["revive"] == mode:
        s.update(present=True, enabled=True, power="on", mode=mode)
    else:
        err, code = "failed to apply configuration", 1
else:
    code = 2
with open(path, "w") as f:
    json.dump(s, f)
print(out)
print(err, file=sys.stderr)
sys.exit(code)
'''


class FakeServer:
    '''Records what the service sends.'''

    def __init__(self):
        self.broadcasts = []

    async def broadcast(self, data):
        '''Arguments: data (bytes): a framed packet.'''
        self.broadcasts.append(data)

    async def send_to(self, writer, data):
        '''Arguments: writer: ignored. data (bytes): a framed packet.'''


class Panel:
    '''
    A fake host: the commands on a PATH of their own and the panel's state file.
    Arguments:
        randr (bool): Whether wlr-randr is installed.
        state: Overrides of the starting panel state.
    '''

    def __init__(self, randr=True, **state):
        self.dir = tempfile.TemporaryDirectory()
        bin_dir = os.path.join(self.dir.name, "bin")
        os.mkdir(bin_dir)
        fakes = [("wlopm", _FAKE_WLOPM)] + ([("wlr-randr", _FAKE_RANDR)] if randr else [])
        for name, body in fakes:
            path = os.path.join(bin_dir, name)
            with open(path, "w") as f:
                f.write(f"#!{sys.executable}\n{body}")
            os.chmod(path, 0o755)
        self.path = os.path.join(self.dir.name, "state.json")
        self.write(dict(dict(power="on", present=True, enabled=True, mode=NATIVE,
                             wedge_on_off=False, revive="never", native_refused=False,
                             calls=[]), **state))
        self.saved_env = {k: os.environ.get(k) for k in ("PATH", "FAKE_DISPLAY_STATE")}
        # Only the fakes: a real wlopm or wlr-randr on this host must not answer.
        os.environ["PATH"] = bin_dir
        os.environ["FAKE_DISPLAY_STATE"] = self.path

    def read(self):
        '''The panel's state now.'''
        with open(self.path) as f:
            return json.load(f)

    def write(self, state):
        '''Arguments: state (dict): the whole state to store.'''
        with open(self.path, "w") as f:
            json.dump(state, f)

    def update(self, **changes):
        '''Arguments: changes: state keys to change.'''
        self.write(dict(self.read(), **changes))

    def modesets(self):
        '''The modes wlr-randr was asked to set, in order.'''
        return [c[c.index("--mode") + 1] for c in self.read()["calls"]
                if c[0] == "wlr-randr" and "--mode" in c]

    def offs(self):
        '''How many times wlopm --off ran.'''
        return sum(1 for c in self.read()["calls"] if c[:2] == ["wlopm", "--off"])

    def close(self):
        '''Restores the environment and removes the fake host.'''
        for key, value in self.saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.dir.cleanup()


def _state(service):
    '''(available, on, fault) from the service's state frame.'''
    frame = service._DisplayService__state_frame()
    return frame[5], frame[6], frame[7]


def _config(service):
    '''The status card's rows as a dict.'''
    return dict(service.health()["config"])


def _scenario(flow, randr=True, **state):
    '''
    Runs one async flow against a fresh fake panel, with no settle time.
    Arguments:
        flow: async callable(service, panel).
        randr (bool): Whether wlr-randr is installed.
        state: Overrides of the starting panel state.
    '''
    panel = Panel(randr=randr, **state)
    settle = display_service._SETTLE_SECONDS
    display_service._SETTLE_SECONDS = 0
    try:
        service = DisplayService(FakeServer())
        asyncio.run(flow(service, panel))
    finally:
        display_service._SETTLE_SECONDS = settle
        panel.close()


def test_blank_and_wake_learns_the_output():
    async def flow(service, panel):
        await service.run()
        assert _state(service) == (1, 1, 0)
        assert _config(service)["Näyttö"] == "HDMI-A-1 · 1280×800"
        await service.set_power(False)
        assert panel.read()["power"] == "off" and _state(service) == (1, 0, 0)
        await service.set_power(True)
        assert panel.read()["power"] == "on" and _state(service) == (1, 1, 0)
        assert panel.modesets() == []
        assert _config(service)["Palautuksia"] == "0"
    _scenario(flow)


def test_wedge_recovered_through_the_kick_mode():
    async def flow(service, panel):
        await service.run()
        await service.set_power(False)
        await service.set_power(True)
        assert _state(service) == (1, 1, 0)
        assert panel.modesets() == [NATIVE, KICK, NATIVE]
        assert panel.read()["mode"] == NATIVE
        config = _config(service)
        assert config["Palautuksia"] == "1"
        assert config["Palautuskeino"] == "Tilanvaihto (1920×1080)"
        assert "time" in config["Viimeisin palautus"]
        assert service.health()["state"] == "ok"
        # Screen-off keeps working after a recovery.
        await service.set_power(False)
        assert panel.offs() == 2
    _scenario(flow, wedge_on_off=True, revive=KICK)


def test_wedge_recovered_by_the_native_mode():
    async def flow(service, panel):
        await service.run()
        await service.set_power(False)
        await service.set_power(True)
        assert _state(service) == (1, 1, 0)
        assert panel.modesets() == [NATIVE]
        assert _config(service)["Palautuskeino"] == "Näyttötila uudelleen"
    _scenario(flow, wedge_on_off=True, revive=NATIVE)


def test_unrecovered_wedge_suspends_screen_off_until_a_recovery_works():
    async def flow(service, panel):
        await service.run()
        await service.set_power(False)
        await service.set_power(True)
        assert _state(service) == (1, 0, 2)
        assert service.health()["state"] == "error"
        await service.set_power(False)
        assert panel.offs() == 1
        # The next wake tries again, and this time the kick works.
        panel.update(revive=KICK)
        await service.set_power(True)
        assert _state(service) == (1, 1, 0)
        await service.set_power(False)
        assert panel.offs() == 2
    _scenario(flow, wedge_on_off=True)


def test_lit_at_the_kick_mode_is_on_but_still_a_fault():
    async def flow(service, panel):
        await service.run()
        await service.set_power(False)
        await service.set_power(True)
        assert panel.read()["mode"] == KICK
        assert _state(service) == (1, 1, 2)
    _scenario(flow, wedge_on_off=True, revive=KICK, native_refused=True)


def test_no_randr_reports_the_wedge_only():
    async def flow(service, panel):
        await service.run()
        await service.set_power(False)
        await service.set_power(True)
        assert _state(service) == (1, 0, 2)
        config = _config(service)
        assert config["Palautus"] == "wlr-randr puuttuu"
        assert config["Näyttö"] == "Kaikki"
    _scenario(flow, randr=False, wedge_on_off=True, revive=KICK)


def test_started_while_wedged_has_no_mode_to_restore():
    async def flow(service, panel):
        await service.run()
        assert _state(service) == (1, 0, 2)
        assert panel.modesets() == []
    _scenario(flow, present=False, enabled=False, power="off", revive=KICK)


def test_wakes_during_a_recovery_run_it_once():
    async def flow(service, panel):
        await service.run()
        await service.set_power(False)
        await asyncio.gather(*(service.set_power(True) for _ in range(3)))
        assert _state(service) == (1, 1, 0)
        assert panel.modesets() == [NATIVE, KICK, NATIVE]
    _scenario(flow, wedge_on_off=True, revive=KICK)


if __name__ == "__main__":
    # Standalone runner so the suite works without pytest installed.
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
