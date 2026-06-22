import asyncio
import logging
import os
import struct
from datetime import datetime, timezone

from .telemetry import TelemetryHandler
from .vehicle import Vehicle
from ..influxdb_service.influxdb_handler import InfluxDBHandler
from ..media_service.media_manager import MediaManager
from ..server.server import Server
from ..utils import protocol
from ..utils.config_parser import Config, get_env
from ..utils.logger_configurator import configure_logging
from ..weather_service.weather_service import WeatherService

logger = logging.getLogger("tesla_service.start_tesla_services")

# Env vars required before any service is constructed.  Missing any of these
# produces surprising mid-startup failures (spotipy NoneType errors, Influx
# auth 401s), so we fail fast with one clear message instead.
REQUIRED_ENV_VARS = (
    "CONFIG_PATH",
    "VIN",
    "API_KEY",
    "INFLUX_TOKEN",
    "SPOTIFY_CLIENT_ID",
    "SPOTIFY_CLIENT_SECRET",
)


# History request range codes (mirrors the frontend RangeSelector).
_RANGE_1H = 0
_RANGE_1D = 1
_RANGE_1M = 2
_RANGE_CUSTOM = 3
_RANGE_1W = 4

def _history_range(range_code: int, start_ms: int, end_ms: int) -> tuple:
    '''
    Maps a request range code to a Flux (time_start, time_end) pair. Presets use
    relative ranges; a custom range converts the epoch-ms bounds to RFC3339 UTC.
    History is returned raw (no downsampling) — the frontend step-renders the
    points so a value held between records still displays as held.
    Arguments:
        range_code (int): One of the _RANGE_* codes.
        start_ms (int): Custom-range start (epoch ms); ignored for presets.
        end_ms (int): Custom-range end (epoch ms); ignored for presets.
    Returns:
        tuple[str, str]: (time_start, time_end).
    '''
    if range_code == _RANGE_1H:
        return "-1h", "now()"
    if range_code == _RANGE_1D:
        return "-1d", "now()"
    if range_code == _RANGE_1W:
        return "-7d", "now()"
    if range_code == _RANGE_1M:
        return "-30d", "now()"
    # Custom range: convert the epoch-ms bounds to RFC3339 UTC. Guard first against
    # an unknown preset code (a newer frontend / version skew) or an empty/inverted
    # custom window — either would otherwise convert epoch 0 to a 1970 range and
    # silently return no data. Degrade to the last hour and log so the skew is loud.
    if range_code != _RANGE_CUSTOM or start_ms <= 0 or end_ms <= 0 or end_ms <= start_ms:
        logger.warning(
            "History range fallback (range_code=%d, start_ms=%d, end_ms=%d) -> -1h",
            range_code, start_ms, end_ms,
        )
        return "-1h", "now()"
    time_start = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    time_end = datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    return time_start, time_end


# Preset window widths in milliseconds, kept beside the _history_range strings so
# the empty-window boundary-fill spans exactly the same range the query asked for.
_PRESET_WINDOW_MS = {
    _RANGE_1H: 60 * 60 * 1000,
    _RANGE_1D: 24 * 60 * 60 * 1000,
    _RANGE_1W: 7 * 24 * 60 * 60 * 1000,
    _RANGE_1M: 30 * 24 * 60 * 60 * 1000,
}


def _history_bounds_ms(range_code: int, start_ms: int, end_ms: int) -> tuple:
    '''
    Returns the requested window's [start, end] as epoch-ms — the absolute
    counterpart to _history_range's Flux strings. Used only to position the two
    synthetic boundary points when a window logged nothing, so the flat held line
    spans the whole selected range. Presets end at "now"; a custom range echoes its
    bounds; anything malformed falls back to the last hour (matching _history_range).
    Arguments:
        range_code (int): One of the _RANGE_* codes.
        start_ms (int): Custom-range start (epoch ms); ignored for presets.
        end_ms (int): Custom-range end (epoch ms); ignored for presets.
    Returns:
        tuple[int, int]: (start_ms, end_ms) in epoch milliseconds.
    '''
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    if range_code in _PRESET_WINDOW_MS:
        return now_ms - _PRESET_WINDOW_MS[range_code], now_ms
    if range_code == _RANGE_CUSTOM and start_ms > 0 and end_ms > start_ms:
        return start_ms, end_ms
    return now_ms - _PRESET_WINDOW_MS[_RANGE_1H], now_ms


def _build_history_frame(data_property_id: str, result) -> bytes:
    '''
    Builds a TESLA_HISTORY response frame. The echoed id lets the frontend drop
    stale responses; status is 0 (no data) when result is None, else 1.
    Arguments:
        data_property_id (str): The requested property id, echoed back.
        result: (count, timestamps_ms, values) from get_data_history, or None.
    '''
    id_bytes = data_property_id.encode("utf-8")
    body = struct.pack("!H", len(id_bytes)) + id_bytes
    if result is None:
        body += struct.pack("!B", 0) + struct.pack("!I", 0)
        return protocol.frame(protocol.TESLA_HISTORY, body)
    count, timestamps, values = result
    body += struct.pack("!B", 1) + struct.pack("!I", int(count))
    for timestamp, value in zip(timestamps, values):
        body += struct.pack("!q", int(timestamp)) + struct.pack("!d", float(value))
    return protocol.frame(protocol.TESLA_HISTORY, body)


def _register_handlers(
    server: Server, mm: MediaManager, vehicle: Vehicle
) -> None:
    '''
    Maps every frontend->backend message type to the service method that
    handles it.  The server itself is opaque to protocol semantics — these
    bindings are the single place where message codes meet service calls.
    '''
    async def _set_progress(payload: bytes, _writer) -> None:
        if len(payload) < 4:
            logger.warning("MEDIA_SET_PROGRESS: payload too short (%d bytes)", len(payload))
            return
        await mm.set_progress(struct.unpack("!I", payload[:4])[0])

    async def _get_graph_properties(_payload: bytes, writer) -> None:
        '''Replies to the requesting client with the graphable-property list.'''
        properties = await vehicle.get_graphable_properties()
        body = struct.pack("!H", len(properties))
        for entry in properties:
            for field in (entry["id"], entry["unit"] or "", entry["category"] or ""):
                encoded = field.encode("utf-8")
                body += struct.pack("!H", len(encoded)) + encoded
        await server.send_to(
            writer, protocol.frame(protocol.TESLA_GRAPH_PROPERTIES, body)
        )

    async def _get_history(payload: bytes, writer) -> None:
        '''
        Reads a property's downsampled history for the requested range and replies
        to the requesting client only.  A bad id or unreachable InfluxDB yields a
        status=0 (no data) frame rather than no reply, so the UI never hangs.
        '''
        if len(payload) < 3:
            logger.warning("TESLA_GET_HISTORY: payload too short (%d bytes)", len(payload))
            return
        range_code = payload[0]
        id_len = struct.unpack("!H", payload[1:3])[0]
        if len(payload) < 3 + id_len + 16:
            logger.warning(
                "TESLA_GET_HISTORY: payload too short for id_len=%d (%d bytes)",
                id_len, len(payload),
            )
            return
        data_property_id = payload[3:3 + id_len].decode("utf-8")
        start_ms, end_ms = struct.unpack("!qq", payload[3 + id_len:3 + id_len + 16])

        time_start, time_end = _history_range(range_code, start_ms, end_ms)
        result = None
        try:
            result = await vehicle.get_data_history(
                data_property_id, time_start, time_end
            )
            if result is None:
                # Genuinely-empty window (the value stayed constant, so nothing was
                # logged in range): draw a flat held line spanning the whole selected
                # range from the last value before the window. If there is no prior
                # value — or InfluxDB is down, where this query also returns None —
                # we fall through to a status=0 "no data" frame and never fabricate.
                window_start_ms, window_end_ms = _history_bounds_ms(
                    range_code, start_ms, end_ms
                )
                window_start_rfc = (
                    datetime.fromtimestamp(window_start_ms / 1000, tz=timezone.utc)
                    .isoformat().replace("+00:00", "Z")
                )
                held = await vehicle.get_value_before(
                    data_property_id, window_start_rfc
                )
                if held is not None:
                    result = (2, [window_start_ms, window_end_ms], [held, held])
        except ValueError as e:
            # Malformed id / window — reply empty rather than dropping the request.
            logger.warning("TESLA_GET_HISTORY rejected: %s", e)
        await server.send_to(writer, _build_history_frame(data_property_id, result))

    # Handlers receive (payload, writer); fire-and-forget commands ignore the
    # writer, request/response handlers (below) reply to it via server.send_to.
    server.register_handler(protocol.MEDIA_SKIP,                 lambda _p, _w: mm.skip_forward())
    server.register_handler(protocol.MEDIA_SKIP_BACKWARD,        lambda _p, _w: mm.skip_backward())
    server.register_handler(protocol.MEDIA_PAUSE_PLAY,           lambda _p, _w: mm.pause_play())
    server.register_handler(protocol.MEDIA_SET_PROGRESS,         _set_progress)
    server.register_handler(protocol.TESLA_SWITCH_CLIMATE_STATE, lambda _p, _w: vehicle.switch_climate_state())
    server.register_handler(protocol.TESLA_MINUS_TARGET_TEMP,    lambda _p, _w: vehicle.minus_temp())
    server.register_handler(protocol.TESLA_PLUS_TARGET_TEMP,     lambda _p, _w: vehicle.plus_temp())
    server.register_handler(protocol.TESLA_GET_GRAPH_PROPERTIES, _get_graph_properties)
    server.register_handler(protocol.TESLA_GET_HISTORY,          _get_history)


async def main():
    configure_logging()
    logger.info("Tesla Homedash services starting")

    missing = [key for key in REQUIRED_ENV_VARS if not get_env(key)]
    if missing:
        raise RuntimeError(
            f"Required environment variables not set: {', '.join(missing)}"
        )

    # Load and validate config.json once; every service receives this instance.
    config = Config(get_env("CONFIG_PATH"))

    vin = get_env("VIN")
    api_key = get_env("API_KEY")

    influx_handler = InfluxDBHandler(
        url=os.getenv("INFLUX_URL", "http://localhost:8086"),
        org=os.getenv("INFLUX_ORG", "Tesla-Homedash"),
        zone_info=config.zone_info,
    )
    logger.debug("InfluxDB handler initialized")

    server = Server()
    logger.debug("TCP server initialized")

    mm = MediaManager(server=server, config=config)
    logger.debug("Media manager initialized")

    weather = WeatherService(server=server, config=config)
    logger.debug("Weather service initialized")

    vehicle = Vehicle(
        vin,
        influx_db_handler=influx_handler,
        server=server,
        access_token=api_key,
        config=config,
    )
    logger.debug("Vehicle initialized")

    # Wire incoming-message dispatch and on-connect snapshot before start().
    _register_handlers(server, mm, vehicle)
    for service in (vehicle, mm, weather):
        server.register_service(service)

    await vehicle.init_async_dependent()

    telemetry = TelemetryHandler(
        access_token=api_key, server="eu.teslemetry.com", vehicle=vehicle
    )

    t1 = asyncio.create_task(telemetry.start())
    t2 = asyncio.create_task(server.start())
    t3 = mm.get_run_task()
    t4 = weather.get_run_task()

    logger.info("All services started, gathering tasks")
    await asyncio.gather(t1, t2, t3, t4)


def main_sync():
    asyncio.run(main())


if __name__ == "__main__":
    main_sync()
