'''
Runtime editing of config.json's `tesla data` table — the Options view's
Telemetriakentät card (issue #29).

Only the per-field flags that are pure display or logging concerns can change
here: `log` (written to InfluxDB, and so offered in the History dropdown),
`line_mode` and `zero_based` (History-graph render hints).  Everything else in
the table — stream_id, category, unit, formula, sleep_default — is mirrored by the
frontend's generated registry or by the Teslemetry field names, so changing it
at runtime would desync the two halves; the card shows those read-only, and
adding or removing a field stays a code change on both sides.

A change is written to config.json through the same Config.set + save as an
Options-view setting (a .bak snapshot, an atomic replace, the in-memory value
rolled back if the save fails) and applied to the live VehicleDataProperty, so
it takes effect from the next telemetry update with no restart.
'''

import json
import logging
import struct

from ..utils import protocol

logger = logging.getLogger("tesla_service.property_editor")

_LINE_MODES = ("step", "linear")

# Fields whose STORED history another view reads back, so their logging must
# not be switched off from here: the view would silently stop getting new data.
# Turning logging ON is always allowed.  Keep in step with the readers:
# trip_service/trip_loader.py, charging_service/charging_loader.py and
# charging_session.py; calculated-field sources are added from config.json.
_REQUIRED_LOGGED = {
    "Gear": "Matkat",
    "Location": "Matkat",
    "VehicleSpeed": "Matkat",
    "Odometer": "Matkat, Lataus",
    "DetailedChargeState": "Lataus",
    "ACChargingEnergyIn": "Lataus",
    "DCChargingEnergyIn": "Lataus",
    "EnergyRemaining": "Lataus",
    "BatteryLevel": "Lataus",
    "LifetimeEnergyUsed": "Lataus",
}


class TeslaPropertyEditor:
    '''
    Serves TESLA_GET_PROPERTY_TABLE and TESLA_SET_PROPERTY.

    Arguments:
        config (Config): Shared configuration; `tesla data` is read and written here.
        vehicle (Vehicle): Owner of the live VehicleDataProperty objects.
        server (Server): TCP server used to reply to and broadcast at clients.
    '''

    def __init__(self, config, vehicle, server):
        self.__config = config
        self.__vehicle = vehicle
        self.__server = server

    # ── Protocol handlers ─────────────────────────────────────────

    async def handle_get(self, _payload: bytes, writer) -> None:
        '''
        TESLA_GET_PROPERTY_TABLE handler: replies with the table to the
        requesting client only.
        Arguments:
            _payload (bytes): Unused; the request carries no body.
            writer (StreamWriter): The requesting client.
        '''
        await self.__server.send_to(writer, await self.__table_frame())

    async def handle_set(self, payload: bytes, writer) -> None:
        '''
        TESLA_SET_PROPERTY handler: validates, persists and applies one flag,
        replies with the outcome, and broadcasts the fresh table after an
        accepted change so every open card shows the truth.
        Arguments:
            payload (bytes): len(4B) + UTF-8 JSON {"id", "field", "value"}.
            writer (StreamWriter): The requesting client, which gets the result.
        '''
        request = {}
        try:
            request = self.__parse(payload)
            changed = await self.__write(request)
        except ValueError as e:
            logger.info("TESLA_SET_PROPERTY rejected: %s", e)
            await self.__reply(writer, False, request, str(e))
            return
        await self.__reply(writer, True, request, "")
        if changed:
            await self.__server.broadcast(await self.__table_frame())

    # ── Internals ─────────────────────────────────────────────────

    async def __write(self, request: dict) -> bool:
        '''
        Validates one change, writes it to config.json and applies it to the
        live property.  Returns False when the value was already set.  Raises
        ValueError with a Finnish message shown to the user verbatim.
        Arguments:
            request (dict): {"id", "field", "value"}.
        '''
        prop_id = request.get("id")
        field = request.get("field")
        value = request.get("value")
        table = self.__config.tesla_data
        if not isinstance(prop_id, str) or prop_id not in table:
            raise ValueError(f"Tuntematon kenttä: {prop_id}")

        if field in ("log", "zero_based"):
            if not isinstance(value, bool):
                raise ValueError("Odotettiin kyllä/ei-arvoa")
        elif field == "line_mode":
            if value not in _LINE_MODES:
                raise ValueError(f"Tuntematon piirtotapa: {value}")
        else:
            raise ValueError(f"Kenttää {field} ei voi muuttaa ajon aikana")

        if field == "log" and value is False:
            required_by = self.__required_by(prop_id)
            if required_by:
                raise ValueError(
                    f"{prop_id} tarvitaan näkymille {required_by}; "
                    "tallennusta ei voi poistaa käytöstä"
                )

        entry = table[prop_id]
        previous = entry.get(field)
        if self.__effective(field, previous) == value:
            return False

        key = f"tesla data.{prop_id}.{field}"
        self.__config.set(key, value)
        try:
            self.__config.save()
        except OSError as e:
            # Put the in-memory document back so the running service and the
            # file on disk never disagree.
            if previous is None and field != "log":
                entry.pop(field, None)
            else:
                self.__config.set(key, previous)
            logger.error("Could not save config after setting %s: %s", key, e)
            raise ValueError("Asetuksen tallennus epäonnistui") from e

        data_property = await self.__vehicle.get_data_property(prop_id)
        if field == "log":
            await data_property.set_logging(value)
        elif field == "line_mode":
            await data_property.set_line_mode(value)
        else:
            await data_property.set_zero_based(value)
        logger.info("Tesla data %s.%s = %r", prop_id, field, value)
        return True

    @staticmethod
    def __effective(field: str, value):
        '''
        The value a key means when it is absent, so writing the default over an
        absent key counts as "unchanged" rather than a pointless save.
        Arguments:
            field (str): The flag's name.
            value: The stored value, or None when absent.
        '''
        if field == "line_mode":
            return value or "step"
        return bool(value)

    def __required_by(self, prop_id: str) -> str:
        '''
        Names the views that read this field's stored history, or "" when none
        does.  Calculated fields (DrivenToday, DrivenThisMonth) read their
        source's history for their period baselines, so their sources count too.
        Arguments:
            prop_id (str): A `tesla data` field id.
        '''
        views = [_REQUIRED_LOGGED[prop_id]] if prop_id in _REQUIRED_LOGGED else []
        for calculated in self.__config.calculated_tesla_data.values():
            if calculated.get("source_data_property_id") == prop_id:
                views.append("Ajettu tänään / tässä kuussa")
                break
        return ", ".join(views)

    async def __table(self) -> list[dict]:
        '''
        One row per `tesla data` field, in config order.  `numeric` is True once
        the field has streamed a number (only those can be graphed), False once
        it has streamed anything else, and None until it has streamed at all.
        '''
        rows = []
        for prop_id, entry in self.__config.tesla_data.items():
            try:
                data_property = await self.__vehicle.get_data_property(prop_id)
                value_type = await data_property.get_value_type()
            except KeyError:
                value_type = None
            rows.append({
                "id": prop_id,
                "category": entry.get("category") or "",
                "unit": entry.get("unit") or "",
                "log": bool(entry.get("log")),
                "line_mode": entry.get("line_mode") or "step",
                "zero_based": bool(entry.get("zero_based")),
                "numeric": None if value_type is None else value_type == "value_float",
                "requiredBy": self.__required_by(prop_id),
            })
        return rows

    async def __table_frame(self) -> bytes:
        '''Builds a TESLA_PROPERTY_TABLE packet.'''
        try:
            document = {"properties": await self.__table()}
            status = protocol.CONFIG_STATUS_OK
        except Exception as e:
            logger.error("Could not build the tesla property table: %s", e)
            document = {"properties": []}
            status = protocol.CONFIG_STATUS_ERROR
        return self.__json_frame(protocol.TESLA_PROPERTY_TABLE, status, document)

    async def __reply(self, writer, ok: bool, request: dict, message: str) -> None:
        '''
        Sends TESLA_SET_PROPERTY_RESULT to the requesting client.
        Arguments:
            writer (StreamWriter): The requesting client.
            ok (bool): Whether the change was accepted.
            request (dict): The parsed request, echoed back so the card can
                match the result to its row.
            message (str): Finnish reason for a refusal; "" on success.
        '''
        document = {
            "ok": ok,
            "id": request.get("id"),
            "field": request.get("field"),
            "value": request.get("value"),
            "message": message,
        }
        status = protocol.CONFIG_STATUS_OK if ok else protocol.CONFIG_STATUS_ERROR
        await self.__server.send_to(
            writer, self.__json_frame(protocol.TESLA_SET_PROPERTY_RESULT, status, document)
        )

    @staticmethod
    def __json_frame(msg_type: int, status: int, document: dict) -> bytes:
        '''
        Frames status(1B) + len(4B) + UTF-8 JSON.
        Arguments:
            msg_type (int): The protocol message type.
            status (int): CONFIG_STATUS_OK or CONFIG_STATUS_ERROR.
            document (dict): The JSON body.
        '''
        body = json.dumps(document, ensure_ascii=False).encode("utf-8")
        return protocol.frame(msg_type, bytes((status,)) + struct.pack("!I", len(body)) + body)

    @staticmethod
    def __parse(payload: bytes) -> dict:
        '''
        Unpacks a len(4B) + UTF-8 JSON request body.  Raises ValueError with a
        Finnish message shown to the user verbatim.
        Arguments:
            payload (bytes): The raw payload after the message-type byte.
        '''
        if len(payload) < 4:
            raise ValueError("Vaillinainen pyyntö")
        (length,) = struct.unpack("!I", payload[:4])
        body = payload[4:4 + length]
        if len(body) != length:
            raise ValueError("Vaillinainen pyyntö")
        try:
            request = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ValueError("Virheellinen JSON") from e
        if not isinstance(request, dict):
            raise ValueError("Virheellinen pyyntö")
        return request
