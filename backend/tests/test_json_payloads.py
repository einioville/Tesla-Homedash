'''
Pins the wire behaviour of the len(4B)+JSON request bodies and the
status(1B)+len(4B)+JSON replies the Options-view services exchange with the
frontend: what each parser accepts, the Finnish message each refusal carries,
and the exact bytes each reply frame puts on the wire.

Runs under pytest, or standalone: `uv run python tests/test_json_payloads.py`.
'''
import asyncio
import json
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.config_service.config_service import ConfigService  # noqa: E402
from src.system_service.log_files import LogFiles  # noqa: E402
from src.system_service.system_history import SystemHistory  # noqa: E402
from src.system_service.system_status_service import SystemStatusService  # noqa: E402
from src.update_service.update_service import UpdateService  # noqa: E402
from src.usb_import_service.usb_import_service import UsbImportService  # noqa: E402
from src.utils import protocol  # noqa: E402


class FakeServer:
    '''Records what a service sends instead of writing to a socket.'''

    def __init__(self):
        self.sent = []
        self.broadcasts = []

    async def send_to(self, _writer, data: bytes) -> None:
        '''Records a reply to one client.'''
        self.sent.append(data)

    async def broadcast(self, data: bytes) -> None:
        '''Records a message to every client.'''
        self.broadcasts.append(data)


def body(document) -> bytes:
    '''A len(4B) + UTF-8 JSON request body, as the frontend sends it.'''
    raw = json.dumps(document).encode("utf-8")
    return struct.pack("!I", len(raw)) + raw


def raw_body(raw: bytes, length: int | None = None) -> bytes:
    '''A request body with an arbitrary (possibly lying) length prefix.'''
    return struct.pack("!I", len(raw) if length is None else length) + raw


def unframe(data: bytes) -> tuple[int, int, dict]:
    '''Splits a framed status+JSON reply into (type, status, document).'''
    (length,) = struct.unpack("!I", data[:4])
    assert len(data) == 4 + length, "frame length prefix does not cover the frame"
    msg_type, status = data[4], data[5]
    (json_len,) = struct.unpack("!I", data[6:10])
    assert len(data) == 10 + json_len, "JSON length prefix does not cover the body"
    return msg_type, status, json.loads(data[10:].decode("utf-8"))


# Inputs every request parser sees, and what the raising parsers make of them.
REQUESTS = [
    ("empty", b"", ValueError("Vaillinainen pyyntö")),
    ("short prefix", b"\x00\x00", ValueError("Vaillinainen pyyntö")),
    ("body shorter than its prefix", raw_body(b"{}", length=10), ValueError("Vaillinainen pyyntö")),
    ("not UTF-8", raw_body(b"\xff\xfe"), ValueError("Virheellinen JSON")),
    ("not JSON", raw_body(b"nope"), ValueError("Virheellinen JSON")),
    ("JSON array", body([1, 2]), ValueError("Virheellinen pyyntö")),
    ("object", body({"key": "a", "value": "ä"}), {"key": "a", "value": "ä"}),
    ("trailing bytes ignored", body({"key": "b"}) + b"xx", {"key": "b"}),
]


def _raises(parse, payload) -> str | None:
    try:
        parse(payload)
    except ValueError as e:
        return str(e)
    return None


def test_parse_json_body():
    parse = protocol.parse_json_body
    for name, payload, expected in REQUESTS:
        if isinstance(expected, ValueError):
            assert _raises(parse, payload) == str(expected), name
        else:
            assert parse(payload) == expected, name


def test_config_set_parser_requires_a_key():
    parse = ConfigService._ConfigService__parse_set_payload
    for name, payload, expected in REQUESTS:
        # A JSON array used to answer "Pyynnöstä puuttuu avain"; it now gets the
        # shared parser's "Virheellinen pyyntö" like every other request.
        if isinstance(expected, ValueError):
            assert _raises(parse, payload) == str(expected), name
        else:
            assert parse(payload) == (expected["key"], expected.get("value")), name
    assert _raises(parse, body({"value": 1})) == "Pyynnöstä puuttuu avain"
    assert parse(body({"key": 5, "value": None})) == ("5", None)


def test_none_returning_parsers():
    parsers = [
        lambda p: UpdateService._UpdateService__decode_json(p, "TEST"),
        lambda p: UsbImportService._UsbImportService__decode(p, "TEST"),
    ]
    for parse in parsers:
        for name, payload, expected in REQUESTS:
            want = None if isinstance(expected, ValueError) else expected
            assert parse(payload) == want, name


def test_system_log_request():
    async def run(payload):
        server = FakeServer()
        service = SystemStatusService(server, error_log=None)
        await service.handle_get_log(payload, None)
        return unframe(server.sent[0])

    msg_type, status, document = asyncio.run(run(body({"service": "nobody"})))
    assert msg_type == protocol.SYSTEM_LOG
    assert status == protocol.CONFIG_STATUS_ERROR
    assert document == {"service": "nobody", "label": "", "entries": []}
    for name, payload in [("empty", b""), ("not JSON", raw_body(b"nope")),
                          ("JSON array", body([1]))]:
        assert asyncio.run(run(payload))[2]["service"] == "", name
    # A body shorter than its length prefix is refused, even when what is there
    # happens to be a whole document (it used to be parsed).
    assert asyncio.run(run(raw_body(b'{"service": "x"}', length=40)))[2]["service"] == ""


def test_log_clear_refuses_a_malformed_request():
    async def run(payload):
        server = FakeServer()
        await LogFiles(server).handle_clear(payload, None)
        return unframe(server.sent[0])

    for name, payload in [("empty", b""), ("not JSON", raw_body(b"nope")),
                          ("JSON array", body([1]))]:
        msg_type, status, document = asyncio.run(run(payload))
        assert msg_type == protocol.LOG_CLEAR_RESULT, name
        assert status == protocol.CONFIG_STATUS_ERROR, name
        assert document == {"ok": False, "freedBytes": 0, "message": "Virheellinen pyyntö"}, name


DOC = {"message": "Ääni ei käytössä", "n": 1}


def test_status_json_frames():
    raw = json.dumps(DOC, ensure_ascii=False).encode("utf-8")
    expected = protocol.frame(0x42, bytes((1,)) + struct.pack("!I", len(raw)) + raw)
    assert protocol.json_frame(0x42, 1, DOC) == expected


def test_config_set_result_frame():
    frame = ConfigService._ConfigService__result_frame(
        protocol.CONFIG_STATUS_OK, "a.b", "ä", "hook", "")
    assert unframe(frame) == (protocol.CONFIG_SET_RESULT, protocol.CONFIG_STATUS_OK,
                              {"key": "a.b", "value": "ä", "applied": "hook", "message": ""})
    assert "ä".encode("utf-8") in frame


def test_usb_import_state_frame():
    frame = UsbImportService._UsbImportService__frame(DOC)
    assert unframe(frame) == (protocol.USB_IMPORT_STATE, 1, DOC)
    # Raw UTF-8 now, like every other reply; it used to be \\u-escaped.
    assert "Ä".encode("utf-8") in frame


def test_system_history_frame_is_compact():
    async def run():
        server = FakeServer()
        await SystemHistory(server).handle_get_history(b"", None)
        return server.sent[0]

    frame = asyncio.run(run())
    msg_type, status, document = unframe(frame)
    assert (msg_type, status) == (protocol.SYSTEM_HISTORY, protocol.CONFIG_STATUS_OK)
    assert document["reset"] is True and document["samples"] == []
    assert b'", "' not in frame and b'": ' not in frame


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
