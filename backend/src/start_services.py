import asyncio
import logging
import math
import os
import struct
from datetime import datetime, timezone

from .charging_service.charging_loader import ChargingLoader
from .influxdb_service.influxdb_handler import InfluxDBHandler
from .media_service.media_manager import MediaManager
from .myenergi_service.myenergi_service import MyEnergiService
from .server.server import Server
from .tesla_service.telemetry import TelemetryHandler
from .tesla_service.vehicle import Vehicle
from .trip_service.trip_loader import TripLoader
from .utils import protocol
from .utils.config_parser import Config, get_env
from .utils.logger_configurator import configure_logging
from .weather_service.weather_service import WeatherService

logger = logging.getLogger("start_services")

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


def _build_trip_list_frame(req_start_ms: int, req_end_ms: int, trips: list) -> bytes:
    '''
    Builds a TRIP_LIST response frame from detected trips. The requested
    [req_start_ms, req_end_ms] window is echoed first so the client can discard an
    out-of-order reply from a superseded week request (the list path's analogue of
    TRIP_DETAIL's trip_id echo). Each record is the trip's [start_ms, end_ms] window
    plus its distance (km) for the dropdown label; distance may be NaN (a trip whose
    distance could not be computed is still listed), which packs as an IEEE-754 NaN
    the frontend renders without a distance.
    Arguments:
        req_start_ms (int): The requested window start, echoed back.
        req_end_ms (int): The requested window end, echoed back.
        trips (list): [(start_ms, end_ms, distance_km), ...].
    '''
    body = struct.pack("!q", int(req_start_ms)) + struct.pack("!q", int(req_end_ms))
    body += struct.pack("!H", len(trips))
    for start_ms, end_ms, distance_km in trips:
        body += struct.pack("!q", int(start_ms))
        body += struct.pack("!q", int(end_ms))
        body += struct.pack("!d", float(distance_km))
    return protocol.frame(protocol.TRIP_LIST, body)


def _build_trip_detail_frame(trip_id: int, route: list) -> bytes:
    '''
    Builds a TRIP_DETAIL response frame. The echoed trip_id (== start_ms) lets the
    frontend drop a reply for a trip it has already switched away from; status is 0
    (no data) for an empty route, else 1. Points are raw (lat, lon, speed) — the
    frontend decimates by zoom and colours each segment by average speed.
    Arguments:
        trip_id (int): The requested trip's start_ms, echoed back.
        route (list): [(ts_ms, latitude, longitude, speed_kmh), ...], or empty.
    '''
    body = struct.pack("!q", int(trip_id))
    if not route:
        body += struct.pack("!B", 0) + struct.pack("!I", 0)
        return protocol.frame(protocol.TRIP_DETAIL, body)
    body += struct.pack("!B", 1) + struct.pack("!I", len(route))
    for ts_ms, latitude, longitude, speed in route:
        body += struct.pack("!q", int(ts_ms))
        body += struct.pack("!d", float(latitude))
        body += struct.pack("!d", float(longitude))
        body += struct.pack("!d", float(speed))
    return protocol.frame(protocol.TRIP_DETAIL, body)


def _build_week_counts_frame(weeks: list) -> bytes:
    '''
    Builds a TRIP_WEEK_COUNTS frame: per requested week, its start (echoed so the
    client matches counts back to its weeks) and the number of trips detected in it.
    Arguments:
        weeks (list): [(week_start_ms, count), ...] in the requested order.
    '''
    body = struct.pack("!H", len(weeks))
    for week_start_ms, count in weeks:
        body += struct.pack("!q", int(week_start_ms))
        body += struct.pack("!H", int(count))
    return protocol.frame(protocol.TRIP_WEEK_COUNTS, body)


# The summary fields packed (in order) after the echoed trip_id/status/window. Every
# value is an IEEE-754 double; a missing metric packs as NaN, which the frontend
# renders as "—". SoC used is derived on the frontend from start_soc − end_soc.
_TRIP_SUMMARY_FIELDS = (
    "distance_km", "avg_speed", "max_speed", "energy_wh", "wh_per_km",
    "start_soc", "end_soc",
)


def _build_trip_summary_frame(
    trip_id: int, start_ms: int, end_ms: int, summary: dict | None
) -> bytes:
    '''
    Builds a TRIP_SUMMARY response frame from Trip.summary(). The echoed trip_id
    (== start_ms) lets the frontend drop a reply for a trip it has switched away from;
    status is 0 (no summary) when summary is None (an inverted window or a failed
    computation), else 1. The window is echoed and the fixed field block is always
    written (NaN-filled on status 0), so the payload is a constant size the client can
    parse without branching.
    Arguments:
        trip_id (int): The requested trip's start_ms, echoed back.
        start_ms (int): The trip window start, echoed for the frontend's time stats.
        end_ms (int): The trip window end, echoed for the frontend's time stats.
        summary (dict | None): Trip.summary()'s dict, or None.
    '''
    status = 0 if summary is None else 1
    body = struct.pack("!q", int(trip_id))
    body += struct.pack("!B", status)
    body += struct.pack("!q", int(start_ms))
    body += struct.pack("!q", int(end_ms))
    for field in _TRIP_SUMMARY_FIELDS:
        value = summary.get(field, float("nan")) if summary else float("nan")
        body += struct.pack("!d", float(value))
    return protocol.frame(protocol.TRIP_SUMMARY, body)


def _build_trip_series_frame(trip_id: int, data_property_id: str, result) -> bytes:
    '''
    Builds a TRIP_SERIES response frame: one numeric property's raw time series over
    the trip window (from get_data_history, the same read the History graph uses). The
    trip_id and the property id are both echoed so the frontend can drop a reply after
    the user switches trip or property. status is 0 (no data) when result is None, else 1.
    Arguments:
        trip_id (int): The requested trip's start_ms, echoed back.
        data_property_id (str): The requested property id, echoed back.
        result: (count, timestamps_ms, values) from get_data_history, or None.
    '''
    id_bytes = data_property_id.encode("utf-8")
    body = struct.pack("!q", int(trip_id))
    body += struct.pack("!H", len(id_bytes)) + id_bytes
    if result is None:
        body += struct.pack("!B", 0) + struct.pack("!I", 0)
        return protocol.frame(protocol.TRIP_SERIES, body)
    count, timestamps, values = result
    body += struct.pack("!B", 1) + struct.pack("!I", int(count))
    for timestamp, value in zip(timestamps, values):
        body += struct.pack("!q", int(timestamp)) + struct.pack("!d", float(value))
    return protocol.frame(protocol.TRIP_SERIES, body)


# The charging-loss summary fields packed (in order) after the echoed
# session_id/status/window. Every value is an IEEE-754 double; a missing metric packs
# as NaN, which the frontend renders as "—". Mirrors _TRIP_SUMMARY_FIELDS.
_CHARGING_SUMMARY_FIELDS = (
    "charger_kwh", "ac_in_kwh", "battery_kwh",
    "loss_cable_kwh", "loss_conversion_kwh", "loss_total_kwh", "loss_total_pct",
    "start_soc", "end_soc",
)


def _build_charging_list_frame(req_start_ms: int, req_end_ms: int, sessions: list) -> bytes:
    '''
    Builds a CHARGING_LIST response frame from detected charging sessions. The requested
    [req_start_ms, req_end_ms] window is echoed first so the client can discard an
    out-of-order reply (the list path's analogue of CHARGING_SUMMARY's session_id echo).
    Each record is the session's [start_ms, end_ms] window plus the charger energy it
    delivered (kWh) for the dropdown label; the loader has already dropped sessions with
    no comparable charger energy, so charger_kwh is always a real number here.
    Arguments:
        req_start_ms (int): The requested window start, echoed back.
        req_end_ms (int): The requested window end, echoed back.
        sessions (list): [(start_ms, end_ms, charger_kwh), ...].
    '''
    body = struct.pack("!q", int(req_start_ms)) + struct.pack("!q", int(req_end_ms))
    body += struct.pack("!H", len(sessions))
    for start_ms, end_ms, charger_kwh in sessions:
        body += struct.pack("!q", int(start_ms))
        body += struct.pack("!q", int(end_ms))
        body += struct.pack("!d", float(charger_kwh))
    return protocol.frame(protocol.CHARGING_LIST, body)


def _build_charging_summary_frame(
    session_id: int, start_ms: int, end_ms: int, summary: dict | None
) -> bytes:
    '''
    Builds a CHARGING_SUMMARY response frame from ChargingSession.summary(). The echoed
    session_id (== start_ms) lets the frontend drop a reply for a session it has switched
    away from; status is 0 (no summary) when summary is None (an inverted window), else 1.
    The window is echoed and the fixed field block is always written (NaN-filled on status
    0), so the payload is a constant size the client parses without branching. Mirrors
    _build_trip_summary_frame.
    Arguments:
        session_id (int): The requested session's start_ms, echoed back.
        start_ms (int): The session window start, echoed for the frontend's time stats.
        end_ms (int): The session window end, echoed for the frontend's time stats.
        summary (dict | None): ChargingSession.summary()'s dict, or None.
    '''
    status = 0 if summary is None else 1
    body = struct.pack("!q", int(session_id))
    body += struct.pack("!B", status)
    body += struct.pack("!q", int(start_ms))
    body += struct.pack("!q", int(end_ms))
    for field in _CHARGING_SUMMARY_FIELDS:
        value = summary.get(field, float("nan")) if summary else float("nan")
        body += struct.pack("!d", float(value))
    return protocol.frame(protocol.CHARGING_SUMMARY, body)


# The month-to-date charging aggregate fields packed (in order) after the status byte.
# Every value is an IEEE-754 double; a missing metric packs as NaN, rendered "—".
# charging_cost_eur is filled by the handler from the configured tariff. Unlike the
# per-session frames there is no echoed window — the month is derived server-side.
_CHARGING_MONTH_FIELDS = (
    "charger_kwh", "car_kwh", "wasted_kwh", "efficiency_pct",
    "car_wh_per_km", "charger_wh_per_km", "driving_kwh", "km_month",
    "session_count", "total_charge_s", "charging_cost_eur", "home_grid_kwh",
)


def _build_charging_month_frame(summary: dict | None) -> bytes:
    '''
    Builds a CHARGING_MONTH response frame from ChargingLoader.month_summary() plus the
    handler-computed charging_cost_eur. status is 0 when summary is None (a failed
    computation), else 1; the fixed field block is always written (NaN-filled on status 0)
    so the payload is a constant size the client parses without branching. Mirrors
    _build_charging_summary_frame.
    Arguments:
        summary (dict | None): The month aggregate dict, or None.
    '''
    status = 0 if summary is None else 1
    body = struct.pack("!B", status)
    for field in _CHARGING_MONTH_FIELDS:
        value = summary.get(field, float("nan")) if summary else float("nan")
        body += struct.pack("!d", float(value))
    return protocol.frame(protocol.CHARGING_MONTH, body)


def _build_charger_history_frame(data_property_id: str, result) -> bytes:
    '''
    Builds a CHARGER_HISTORY response frame — one charger power property's raw time series
    over the requested window (from read_charger_data_property, "myenergi_data"). The
    echoed id lets the frontend drop a stale reply; status is 0 (no data) when result is
    None, else 1. Identical shape to _build_history_frame (TESLA_HISTORY), just a
    different measurement + message type.
    Arguments:
        data_property_id (str): The requested charger property id, echoed back.
        result: (count, timestamps_ms, values) from get_power_history, or None.
    '''
    id_bytes = data_property_id.encode("utf-8")
    body = struct.pack("!H", len(id_bytes)) + id_bytes
    if result is None:
        body += struct.pack("!B", 0) + struct.pack("!I", 0)
        return protocol.frame(protocol.CHARGER_HISTORY, body)
    count, timestamps, values = result
    body += struct.pack("!B", 1) + struct.pack("!I", int(count))
    for timestamp, value in zip(timestamps, values):
        body += struct.pack("!q", int(timestamp)) + struct.pack("!d", float(value))
    return protocol.frame(protocol.CHARGER_HISTORY, body)


def _register_handlers(
    server: Server,
    mm: MediaManager,
    vehicle: Vehicle,
    trip_loader: TripLoader,
    charging_loader: ChargingLoader,
    config: Config,
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

    async def _get_trip_list(payload: bytes, writer) -> None:
        '''
        Detects the trips in the requested window (a week) and replies to the
        requesting client only. A malformed request or an unreachable InfluxDB yields
        an empty list rather than no reply, so the Trips dropdown never hangs.
        '''
        if len(payload) < 16:
            logger.warning("TRIP_GET_LIST: payload too short (%d bytes)", len(payload))
            return
        start_ms, end_ms = struct.unpack("!qq", payload[:16])
        records = []
        try:
            trips = await trip_loader.list_trips(start_ms, end_ms)
            for trip in trips:
                # distance_km() is cached from list_trips' own distance filter, so
                # this reuses the value rather than re-reading Odometer.
                records.append((trip.start_ms, trip.end_ms, await trip.distance_km()))
        except Exception as e:
            logger.warning("TRIP_GET_LIST failed: %s: %s", type(e).__name__, e)
        # Echo the requested window so the client can drop an out-of-order reply.
        await server.send_to(writer, _build_trip_list_frame(start_ms, end_ms, records))

    async def _get_trip_detail(payload: bytes, writer) -> None:
        '''
        Loads the selected trip's GPS + speed route and replies to the requesting
        client only. The trip's [start_ms, end_ms] window is echoed by the client
        (known from the prior TRIP_LIST), so no re-detection is needed. A window that
        logged no fixes replies status=0 (no data) rather than no reply.
        '''
        if len(payload) < 16:
            logger.warning("TRIP_GET_DETAIL: payload too short (%d bytes)", len(payload))
            return
        start_ms, end_ms = struct.unpack("!qq", payload[:16])
        route = []
        try:
            route = await trip_loader.load_route(start_ms, end_ms)
        except Exception as e:
            logger.warning("TRIP_GET_DETAIL failed: %s: %s", type(e).__name__, e)
        await server.send_to(writer, _build_trip_detail_frame(start_ms, route))

    async def _get_week_counts(payload: bytes, writer) -> None:
        '''
        Counts the trips per requested week for the week-selector dropdown. Detects
        trips over the whole span [min start, max end] in a single scan (one Gear read
        + one Odometer read, thanks to list_trips' in-memory distance), then buckets
        each trip by which week window contains its start. Replies to the requesting
        client only; a malformed request or an unreachable InfluxDB yields all-zero
        counts rather than no reply.
        '''
        if len(payload) < 2:
            logger.warning("TRIP_GET_WEEK_COUNTS: payload too short (%d bytes)", len(payload))
            return
        num_weeks = struct.unpack("!H", payload[:2])[0]
        if len(payload) < 2 + num_weeks * 16:
            logger.warning(
                "TRIP_GET_WEEK_COUNTS: payload too short for %d weeks (%d bytes)",
                num_weeks, len(payload),
            )
            return
        weeks = []
        offset = 2
        for _ in range(num_weeks):
            week_start, week_end = struct.unpack("!qq", payload[offset:offset + 16])
            weeks.append((week_start, week_end))
            offset += 16

        counts = [0] * num_weeks
        if num_weeks > 0:
            span_start = min(w[0] for w in weeks)
            span_end = max(w[1] for w in weeks)
            try:
                trips = await trip_loader.list_trips(span_start, span_end)
                for trip in trips:
                    for index, (week_start, week_end) in enumerate(weeks):
                        if week_start <= trip.start_ms < week_end:
                            counts[index] += 1
                            break
            except Exception as e:
                logger.warning("TRIP_GET_WEEK_COUNTS failed: %s: %s", type(e).__name__, e)

        records = [(weeks[index][0], counts[index]) for index in range(num_weeks)]
        await server.send_to(writer, _build_week_counts_frame(records))

    async def _get_trip_summary(payload: bytes, writer) -> None:
        '''
        Computes the selected trip's summary stats and replies to the requesting client
        only. The trip's [start_ms, end_ms] window is echoed by the client (known from
        the prior TRIP_LIST), so no re-detection is needed. A malformed request or a
        failed computation replies status=0 rather than no reply, so the stats panel
        never hangs.
        '''
        if len(payload) < 16:
            logger.warning("TRIP_GET_SUMMARY: payload too short (%d bytes)", len(payload))
            return
        start_ms, end_ms = struct.unpack("!qq", payload[:16])
        summary = None
        try:
            summary = await trip_loader.load_summary(start_ms, end_ms)
        except Exception as e:
            logger.warning("TRIP_GET_SUMMARY failed: %s: %s", type(e).__name__, e)
        await server.send_to(
            writer, _build_trip_summary_frame(start_ms, start_ms, end_ms, summary)
        )

    async def _get_trip_series(payload: bytes, writer) -> None:
        '''
        Reads one numeric property's raw history over the trip window for the detail
        graph, and replies to the requesting client only. Reuses the History read path
        (_history_range's custom-window conversion + get_data_history), so a trip graph
        needs no new read logic. A bad id or unreachable InfluxDB replies status=0.
        '''
        if len(payload) < 18:  # start_ms(8) + end_ms(8) + id_len(2)
            logger.warning("TRIP_GET_SERIES: payload too short (%d bytes)", len(payload))
            return
        start_ms, end_ms = struct.unpack("!qq", payload[:16])
        id_len = struct.unpack("!H", payload[16:18])[0]
        if len(payload) < 18 + id_len:
            logger.warning(
                "TRIP_GET_SERIES: payload too short for id_len=%d (%d bytes)",
                id_len, len(payload),
            )
            return
        data_property_id = payload[18:18 + id_len].decode("utf-8")
        result = None
        try:
            time_start, time_end = _history_range(_RANGE_CUSTOM, start_ms, end_ms)
            result = await vehicle.get_data_history(data_property_id, time_start, time_end)
        except Exception as e:
            # Any read/parse failure replies status=0 rather than no reply, so the graph
            # never hangs on "Ladataan…" (matches the other trip handlers). ValueError is
            # a bad id/window; other exceptions are an InfluxDB hiccup.
            logger.warning("TRIP_GET_SERIES failed: %s: %s", type(e).__name__, e)
        await server.send_to(
            writer, _build_trip_series_frame(start_ms, data_property_id, result)
        )

    async def _get_charging_list(payload: bytes, writer) -> None:
        '''
        Detects the charging sessions in the requested window and replies to the
        requesting client only. A malformed request or an unreachable InfluxDB yields an
        empty list rather than no reply, so the sessions dropdown never hangs. Mirrors
        _get_trip_list.
        '''
        if len(payload) < 16:
            logger.warning("CHARGING_GET_LIST: payload too short (%d bytes)", len(payload))
            return
        start_ms, end_ms = struct.unpack("!qq", payload[:16])
        records = []
        try:
            sessions = await charging_loader.list_sessions(start_ms, end_ms)
            for session in sessions:
                # charger_kwh() is cached from list_sessions' own energy filter, so this
                # reuses the value rather than re-reading the charger series.
                records.append((session.start_ms, session.end_ms, await session.charger_kwh()))
        except Exception as e:
            logger.warning("CHARGING_GET_LIST failed: %s: %s", type(e).__name__, e)
        # Echo the requested window so the client can drop an out-of-order reply.
        await server.send_to(writer, _build_charging_list_frame(start_ms, end_ms, records))

    async def _get_charging_summary(payload: bytes, writer) -> None:
        '''
        Computes the selected session's loss breakdown and replies to the requesting
        client only. The session's [start_ms, end_ms] window is echoed by the client
        (known from the prior CHARGING_LIST), so no re-detection is needed. A malformed
        request or a failed computation replies status=0 rather than no reply, so the
        panel never hangs. Mirrors _get_trip_summary.
        '''
        if len(payload) < 16:
            logger.warning("CHARGING_GET_SUMMARY: payload too short (%d bytes)", len(payload))
            return
        start_ms, end_ms = struct.unpack("!qq", payload[:16])
        summary = None
        try:
            summary = await charging_loader.load_summary(start_ms, end_ms)
        except Exception as e:
            logger.warning("CHARGING_GET_SUMMARY failed: %s: %s", type(e).__name__, e)
        await server.send_to(
            writer, _build_charging_summary_frame(start_ms, start_ms, end_ms, summary)
        )

    async def _get_charging_month(_payload: bytes, writer) -> None:
        '''
        Computes the month-to-date charging aggregate (energy, waste, efficiency,
        consumption/km, sessions, cost, home import) and replies to the requesting client
        only. The month runs from the 1st (00:00 in the configured timezone) to now. A
        failed computation replies status=0 rather than no reply, so the stats grid never
        hangs. The flat tariff (€/kWh from config, or None) turns charger energy into a
        cost estimate here, keeping pricing out of the loader.
        '''
        summary = None
        try:
            now = datetime.now(config.zone_info)
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            now_ms = int(now.timestamp() * 1000)
            month_start_ms = int(month_start.timestamp() * 1000)
            summary = await charging_loader.month_summary(month_start_ms, now_ms)
            tariff = config.electricity_price_eur_per_kwh
            charger_kwh = summary.get("charger_kwh", float("nan"))
            summary["charging_cost_eur"] = (
                charger_kwh * tariff
                if (tariff is not None and not math.isnan(charger_kwh))
                else float("nan")
            )
        except Exception as e:
            logger.warning("CHARGING_GET_MONTH failed: %s: %s", type(e).__name__, e)
        await server.send_to(writer, _build_charging_month_frame(summary))

    async def _get_charger_history(payload: bytes, writer) -> None:
        '''
        Reads a charger (myenergi) power property's raw history for the requested range
        and replies to the requesting client only — the Charging view's past-hour graphs.
        Mirrors _get_history but reads the "myenergi_data" measurement (GridPower /
        ChargePower, logged every poll). A bad id or unreachable InfluxDB replies status=0
        (no data) rather than no reply, so the graph never hangs.
        '''
        if len(payload) < 3:
            logger.warning("CHARGER_GET_HISTORY: payload too short (%d bytes)", len(payload))
            return
        range_code = payload[0]
        id_len = struct.unpack("!H", payload[1:3])[0]
        if len(payload) < 3 + id_len + 16:
            logger.warning(
                "CHARGER_GET_HISTORY: payload too short for id_len=%d (%d bytes)",
                id_len, len(payload),
            )
            return
        data_property_id = payload[3:3 + id_len].decode("utf-8")
        start_ms, end_ms = struct.unpack("!qq", payload[3 + id_len:3 + id_len + 16])

        time_start, time_end = _history_range(range_code, start_ms, end_ms)
        result = None
        try:
            result = await charging_loader.get_power_history(
                data_property_id, time_start, time_end
            )
        except ValueError as e:
            # Malformed id — reply empty rather than dropping the request.
            logger.warning("CHARGER_GET_HISTORY rejected: %s", e)
        await server.send_to(writer, _build_charger_history_frame(data_property_id, result))

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
    server.register_handler(protocol.TRIP_GET_LIST,              _get_trip_list)
    server.register_handler(protocol.TRIP_GET_DETAIL,            _get_trip_detail)
    server.register_handler(protocol.TRIP_GET_WEEK_COUNTS,       _get_week_counts)
    server.register_handler(protocol.TRIP_GET_SUMMARY,           _get_trip_summary)
    server.register_handler(protocol.TRIP_GET_SERIES,            _get_trip_series)
    server.register_handler(protocol.CHARGING_GET_LIST,          _get_charging_list)
    server.register_handler(protocol.CHARGING_GET_SUMMARY,       _get_charging_summary)
    server.register_handler(protocol.CHARGING_GET_MONTH,         _get_charging_month)
    server.register_handler(protocol.CHARGER_GET_HISTORY,        _get_charger_history)


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

    # Trip detection (issue #5/#6): reads Gear/Location/VehicleSpeed history out of
    # InfluxDB on demand to serve the Trips view. Stateless — no run task, purely
    # request/response via the handlers below.
    trip_loader = TripLoader(influx_handler, config)
    logger.debug("Trip loader initialized")

    # Charging-loss analysis (myenergi): stateless, reads DetailedChargeState +
    # myenergi_data history from InfluxDB on demand. Constructed unconditionally so the
    # charging handlers always answer (an empty list when no charger data exists).
    charging_loader = ChargingLoader(influx_handler, config)
    logger.debug("Charging loader initialized")

    # MyEnergi (Zappi) charger streaming + logging: optional. Absent credentials -> the
    # service is not started (a deployment without a charger still runs), while the
    # charging handlers above stay registered so the frontend view degrades to an empty
    # list instead of an unhandled message.
    myenergi = None
    myenergi_hub_serial = get_env("MYENERGI_HUB_SERIAL")
    myenergi_api_key = get_env("MYENERGI_API_KEY")
    if myenergi_hub_serial and myenergi_api_key:
        myenergi = MyEnergiService(
            server=server,
            config=config,
            influx_handler=influx_handler,
            hub_serial=myenergi_hub_serial,
            api_key=myenergi_api_key,
        )
        logger.debug("MyEnergi service initialized")
    else:
        logger.warning(
            "MyEnergi credentials not set (MYENERGI_HUB_SERIAL / MYENERGI_API_KEY); "
            "charger streaming + logging disabled"
        )

    # Wire incoming-message dispatch and on-connect snapshot before start().
    _register_handlers(server, mm, vehicle, trip_loader, charging_loader, config)
    services = [vehicle, mm, weather]
    if myenergi is not None:
        services.append(myenergi)
    for service in services:
        server.register_service(service)

    await vehicle.init_async_dependent()

    telemetry = TelemetryHandler(
        access_token=api_key, server="eu.teslemetry.com", vehicle=vehicle
    )

    t1 = asyncio.create_task(telemetry.start())
    t2 = asyncio.create_task(server.start())
    t3 = mm.get_run_task()
    t4 = weather.get_run_task()

    tasks = [t1, t2, t3, t4]
    if myenergi is not None:
        tasks.append(myenergi.get_run_task())

    logger.info("All services started, gathering tasks")
    await asyncio.gather(*tasks)


def main_sync():
    asyncio.run(main())


if __name__ == "__main__":
    main_sync()
