import asyncio
import logging
import os
import struct
from datetime import datetime, timezone

from .audio_service.audio_service import AudioService
from .audio_service.spectrum import AudioSpectrum
from .auth_service.auth_service import AuthService
from .charging_service.charging_loader import ChargingLoader
from .config_service.config_service import ConfigService
from .display_service.display_service import DisplayService
from .charging_service.spot_price import SpotPriceProvider
from .charging_service.spot_price_service import SpotPriceService
from .influxdb_service.influxdb_handler import InfluxDBHandler, to_flux_time
from .media_service.media_manager import MediaManager
from .media_service.spotify_auth_service import SpotifyAuthService
from .media_service.spotify_device_service import SpotifyDeviceService
from .myenergi_service.myenergi_service import MyEnergiService
from .server.server import Server
from .system_service.log_level import LogLevel
from .system_service.log_files import LogFiles
from .system_service import system_metrics
from .system_service.system_history import SystemHistory
from .system_service.system_status_service import SystemStatusService
from .usb_import_service.usb_import_service import UsbImportService
from .update_service.update_service import UpdateService
from .tesla_service.property_editor import TeslaPropertyEditor
from .tesla_service.telemetry import TelemetryHandler
from .tesla_service.vehicle import Vehicle
from .trip_service.trip_loader import TripLoader
from .utils import protocol
from .utils.config_parser import Config, default_config_path, get_env
from .utils.logger_configurator import configure_logging, error_log
from .weather_service.weather_service import WeatherService

logger = logging.getLogger("start_services")

# Env vars required before any service is constructed.  Missing any of these
# produces surprising mid-startup failures (spotipy NoneType errors, Influx
# auth 401s), so we fail fast with one clear message instead.
# CONFIG_PATH is not required: it defaults to default_config_path().
REQUIRED_ENV_VARS = (
    "VIN",
    "API_KEY",
    "INFLUX_TOKEN",
    "SPOTIFY_CLIENT_ID",
    "SPOTIFY_CLIENT_SECRET",
)


# range_code -> (Flux range start, window width in ms) for the presets, which all
# end at now(). The query and the empty-window boundary fill both read this, so
# the held line always spans exactly the range that was queried.
_PRESET_RANGES = {
    protocol.HISTORY_RANGE_1H: ("-1h", 60 * 60 * 1000),
    protocol.HISTORY_RANGE_1D: ("-1d", 24 * 60 * 60 * 1000),
    protocol.HISTORY_RANGE_1W: ("-7d", 7 * 24 * 60 * 60 * 1000),
    protocol.HISTORY_RANGE_1M: ("-30d", 30 * 24 * 60 * 60 * 1000),
}


def _is_custom_window(range_code: int, start_ms: int, end_ms: int) -> bool:
    '''
    True for a usable custom range: the custom code and a non-empty window
    after the epoch.
    Arguments:
        range_code (int): One of the protocol.HISTORY_RANGE_* codes.
        start_ms (int): Custom-range start (epoch ms).
        end_ms (int): Custom-range end (epoch ms).
    '''
    return range_code == protocol.HISTORY_RANGE_CUSTOM and 0 < start_ms < end_ms


def _history_range(range_code: int, start_ms: int, end_ms: int) -> tuple:
    '''
    Maps a request range code to a Flux (time_start, time_end) pair. Presets use
    relative ranges; a custom range converts the epoch-ms bounds to RFC3339 UTC.
    History is returned raw (no downsampling) — the frontend step-renders the
    points so a value held between records still displays as held.
    Arguments:
        range_code (int): One of the protocol.HISTORY_RANGE_* codes.
        start_ms (int): Custom-range start (epoch ms); ignored for presets.
        end_ms (int): Custom-range end (epoch ms); ignored for presets.
    Returns:
        tuple[str, str]: (time_start, time_end).
    '''
    if range_code in _PRESET_RANGES:
        return _PRESET_RANGES[range_code][0], "now()"
    # An unknown preset code (a newer frontend / version skew) or an empty/inverted
    # custom window would otherwise convert epoch 0 to a 1970 range and silently
    # return no data. Degrade to the last hour and log so the skew is loud.
    if not _is_custom_window(range_code, start_ms, end_ms):
        logger.warning(
            "History range fallback (range_code=%d, start_ms=%d, end_ms=%d) -> -1h",
            range_code, start_ms, end_ms,
        )
        return _PRESET_RANGES[protocol.HISTORY_RANGE_1H][0], "now()"
    return to_flux_time(start_ms), to_flux_time(end_ms)


def _history_bounds_ms(range_code: int, start_ms: int, end_ms: int) -> tuple:
    '''
    Returns the requested window's [start, end] as epoch-ms — the absolute
    counterpart to _history_range's Flux strings. Used only to position the two
    synthetic boundary points when a window logged nothing, so the flat held line
    spans the whole selected range. Presets end at "now"; a custom range echoes its
    bounds; anything malformed falls back to the last hour (matching _history_range).
    Arguments:
        range_code (int): One of the protocol.HISTORY_RANGE_* codes.
        start_ms (int): Custom-range start (epoch ms); ignored for presets.
        end_ms (int): Custom-range end (epoch ms); ignored for presets.
    Returns:
        tuple[int, int]: (start_ms, end_ms) in epoch milliseconds.
    '''
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    if range_code in _PRESET_RANGES:
        return now_ms - _PRESET_RANGES[range_code][1], now_ms
    if _is_custom_window(range_code, start_ms, end_ms):
        return start_ms, end_ms
    return now_ms - _PRESET_RANGES[protocol.HISTORY_RANGE_1H][1], now_ms


def _parse_history_request(payload: bytes, label: str) -> tuple | None:
    '''
    Unpacks a TESLA_GET_HISTORY / CHARGER_GET_HISTORY request: range_code(1B) +
    id(len(2B)+UTF-8) + start_ms(8B) + end_ms(8B). A truncated request is logged
    and returns None; it gets no reply.
    Arguments:
        payload (bytes): The raw payload after the message-type byte.
        label (str): Packet name, for the warning line.
    Returns:
        tuple | None: (range_code, data_property_id, start_ms, end_ms).
    '''
    if len(payload) < 3:
        logger.warning("%s: payload too short (%d bytes)", label, len(payload))
        return None
    range_code = payload[0]
    id_len = struct.unpack("!H", payload[1:3])[0]
    if len(payload) < 3 + id_len + 16:
        logger.warning(
            "%s: payload too short for id_len=%d (%d bytes)", label, id_len, len(payload),
        )
        return None
    data_property_id = payload[3:3 + id_len].decode("utf-8")
    start_ms, end_ms = struct.unpack("!qq", payload[3 + id_len:3 + id_len + 16])
    return range_code, data_property_id, start_ms, end_ms


def _parse_window(payload: bytes, label: str) -> tuple | None:
    '''
    Unpacks the start_ms(8B) + end_ms(8B) window a trip or charging request
    carries. A truncated request is logged and returns None; it gets no reply.
    Arguments:
        payload (bytes): The raw payload after the message-type byte.
        label (str): Packet name, for the warning line.
    '''
    if len(payload) < 16:
        logger.warning("%s: payload too short (%d bytes)", label, len(payload))
        return None
    return struct.unpack("!qq", payload[:16])


def _pack_id(text: str) -> bytes:
    '''
    Packs a len(2B) + UTF-8 string, the shape of every echoed property id.
    Arguments:
        text (str): The id.
    '''
    raw = text.encode("utf-8")
    return struct.pack("!H", len(raw)) + raw


def _pack_series(result) -> bytes:
    '''
    Packs status(1B) + count(4B) + count*(ts_ms(8B) + value(8B double)), the series
    block of TESLA_HISTORY, CHARGER_HISTORY and TRIP_SERIES. status is 0 (no data)
    with no points when result is None, else 1.
    Arguments:
        result: (count, timestamps_ms, values) from a history read, or None.
    '''
    if result is None:
        return struct.pack("!B", 0) + struct.pack("!I", 0)
    count, timestamps, values = result
    body = struct.pack("!B", 1) + struct.pack("!I", int(count))
    for timestamp, value in zip(timestamps, values):
        body += struct.pack("!q", int(timestamp)) + struct.pack("!d", float(value))
    return body


def _pack_doubles(fields: tuple, summary: dict | None) -> bytes:
    '''
    Packs one IEEE-754 double per field, in order. A field missing from summary
    — every field when summary is None — packs as NaN, which the frontend renders
    as "—".
    Arguments:
        fields (tuple): The field names, in wire order.
        summary (dict | None): The computed values.
    '''
    body = b""
    for field in fields:
        value = summary.get(field, float("nan")) if summary else float("nan")
        body += struct.pack("!d", float(value))
    return body


def _build_history_frame(msg_type: int, data_property_id: str, result) -> bytes:
    '''
    Builds a TESLA_HISTORY or CHARGER_HISTORY reply: the echoed id, which lets the
    frontend drop a stale reply, then the series.
    Arguments:
        msg_type (int): protocol.TESLA_HISTORY or protocol.CHARGER_HISTORY.
        data_property_id (str): The requested property id, echoed back.
        result: (count, timestamps_ms, values) from the history read, or None.
    '''
    return protocol.frame(msg_type, _pack_id(data_property_id) + _pack_series(result))


def _build_window_list_frame(msg_type: int, req_start_ms: int, req_end_ms: int,
                             records: list) -> bytes:
    '''
    Builds a TRIP_LIST or CHARGING_LIST reply. The requested [req_start_ms,
    req_end_ms] window is echoed first so the client can discard an out-of-order
    reply from a superseded request. Each record is a [start_ms, end_ms] window
    plus one double for the dropdown label: a trip's distance (km; NaN when it
    could not be computed, and the trip is still listed) or a session's charger
    energy (kWh; the loader has already dropped sessions without one).
    Arguments:
        msg_type (int): protocol.TRIP_LIST or protocol.CHARGING_LIST.
        req_start_ms (int): The requested window start, echoed back.
        req_end_ms (int): The requested window end, echoed back.
        records (list): [(start_ms, end_ms, value), ...].
    '''
    body = struct.pack("!q", int(req_start_ms)) + struct.pack("!q", int(req_end_ms))
    body += struct.pack("!H", len(records))
    for start_ms, end_ms, value in records:
        body += struct.pack("!q", int(start_ms))
        body += struct.pack("!q", int(end_ms))
        body += struct.pack("!d", float(value))
    return protocol.frame(msg_type, body)


def _build_route_frame(msg_type: int, trip_id: int, route: list) -> bytes:
    '''
    Builds a TRIP_DETAIL or TRIP_CURRENT response frame. The trip_id (== start_ms) lets
    the frontend drop a reply for a trip it has already switched away from, and is 0 in
    a TRIP_CURRENT with no drive under way; status is 0 (no data) for an empty route,
    else 1. Points are raw (lat, lon, speed) — the frontend decimates by zoom and
    colours each segment by average speed.
    Arguments:
        msg_type (int): protocol.TRIP_DETAIL or protocol.TRIP_CURRENT.
        trip_id (int): The trip's start_ms.
        route (list): [(ts_ms, latitude, longitude, speed_kmh), ...], or empty.
    '''
    body = struct.pack("!q", int(trip_id))
    if not route:
        body += struct.pack("!B", 0) + struct.pack("!I", 0)
        return protocol.frame(msg_type, body)
    body += struct.pack("!B", 1) + struct.pack("!I", len(route))
    for ts_ms, latitude, longitude, speed in route:
        body += struct.pack("!q", int(ts_ms))
        body += struct.pack("!d", float(latitude))
        body += struct.pack("!d", float(longitude))
        body += struct.pack("!d", float(speed))
    return protocol.frame(msg_type, body)


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


# TRIP_SUMMARY's fields, in wire order. SoC used is derived on the frontend from
# start_soc − end_soc.
_TRIP_SUMMARY_FIELDS = (
    "distance_km", "avg_speed", "max_speed", "energy_wh", "wh_per_km",
    "start_soc", "end_soc",
)

# CHARGING_SUMMARY's fields, in wire order. cost_eur / avg_price_eur_per_kwh are the
# session's spot-priced cost and its average €/kWh (NaN when spot pricing is off and
# no flat tariff is set).
_CHARGING_SUMMARY_FIELDS = (
    "charger_kwh", "ac_in_kwh", "battery_kwh",
    "loss_cable_kwh", "loss_conversion_kwh", "loss_total_kwh", "loss_total_pct",
    "start_soc", "end_soc", "cost_eur", "avg_price_eur_per_kwh",
)

# CHARGING_MONTH's fields, in wire order. Both cost fields are computed inside
# ChargingLoader.month_summary(). Unlike the per-session frames there is no echoed
# window: the month is derived server-side.
_CHARGING_MONTH_FIELDS = (
    "charger_kwh", "car_kwh", "wasted_kwh", "efficiency_pct",
    "car_wh_per_km", "charger_wh_per_km", "driving_kwh", "km_month",
    "session_count", "total_charge_s", "charging_cost_eur", "home_grid_kwh",
    "home_cost_eur",
)


def _build_summary_frame(msg_type: int, fields: tuple, item_id: int,
                         start_ms: int, end_ms: int, summary: dict | None) -> bytes:
    '''
    Builds a TRIP_SUMMARY or CHARGING_SUMMARY reply. The echoed id (== start_ms)
    lets the frontend drop a reply for a trip or session it has switched away
    from; status is 0 (no summary) when summary is None (an inverted window or a
    failed computation), else 1. The window is echoed and the field block is
    always written (NaN-filled on status 0), so the payload is a constant size the
    client parses without branching.
    Arguments:
        msg_type (int): protocol.TRIP_SUMMARY or protocol.CHARGING_SUMMARY.
        fields (tuple): _TRIP_SUMMARY_FIELDS or _CHARGING_SUMMARY_FIELDS.
        item_id (int): The requested trip's or session's start_ms, echoed back.
        start_ms (int): The window start, echoed for the frontend's time stats.
        end_ms (int): The window end, echoed for the frontend's time stats.
        summary (dict | None): The computed summary, or None.
    '''
    body = struct.pack("!q", int(item_id))
    body += struct.pack("!B", 0 if summary is None else 1)
    body += struct.pack("!q", int(start_ms))
    body += struct.pack("!q", int(end_ms))
    return protocol.frame(msg_type, body + _pack_doubles(fields, summary))


def _build_trip_series_frame(trip_id: int, data_property_id: str, result) -> bytes:
    '''
    Builds a TRIP_SERIES response frame: one numeric property's raw time series over
    the trip window (from get_data_history, the same read the History graph uses). The
    trip_id and the property id are both echoed so the frontend can drop a reply after
    the user switches trip or property.
    Arguments:
        trip_id (int): The requested trip's start_ms, echoed back.
        data_property_id (str): The requested property id, echoed back.
        result: (count, timestamps_ms, values) from get_data_history, or None.
    '''
    body = struct.pack("!q", int(trip_id)) + _pack_id(data_property_id) + _pack_series(result)
    return protocol.frame(protocol.TRIP_SERIES, body)


def _build_charging_month_frame(summary: dict | None) -> bytes:
    '''
    Builds a CHARGING_MONTH response frame from ChargingLoader.month_summary().
    status is 0 when summary is None (a failed computation), else 1; the field
    block is always written (NaN-filled on status 0), so the payload is a constant
    size the client parses without branching.
    Arguments:
        summary (dict | None): The month aggregate dict, or None.
    '''
    status = 0 if summary is None else 1
    return protocol.frame(
        protocol.CHARGING_MONTH,
        struct.pack("!B", status) + _pack_doubles(_CHARGING_MONTH_FIELDS, summary),
    )


def _register_handlers(
    server: Server,
    mm: MediaManager,
    vehicle: Vehicle,
    trip_loader: TripLoader,
    charging_loader: ChargingLoader,
    config: Config,
    config_service: ConfigService,
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
            for field in (
                entry["id"],
                entry["unit"] or "",
                entry["category"] or "",
                entry["line_mode"] or "step",
            ):
                encoded = field.encode("utf-8")
                body += struct.pack("!H", len(encoded)) + encoded
            body += struct.pack("!B", 1 if entry["zero_based"] else 0)
        await server.send_to(
            writer, protocol.frame(protocol.TESLA_GRAPH_PROPERTIES, body)
        )

    async def _get_history(payload: bytes, writer) -> None:
        '''
        Reads a property's raw history for the requested range and replies
        to the requesting client only.  A bad id or unreachable InfluxDB yields a
        status=0 (no data) frame rather than no reply, so the UI never hangs.
        '''
        request = _parse_history_request(payload, "TESLA_GET_HISTORY")
        if request is None:
            return
        range_code, data_property_id, start_ms, end_ms = request

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
                held = await vehicle.get_value_before(
                    data_property_id, to_flux_time(window_start_ms)
                )
                if held is not None:
                    result = (2, [window_start_ms, window_end_ms], [held, held])
        except ValueError as e:
            # Malformed id / window — reply empty rather than dropping the request.
            logger.warning("TESLA_GET_HISTORY rejected: %s", e)
        await server.send_to(
            writer, _build_history_frame(protocol.TESLA_HISTORY, data_property_id, result))

    async def _get_trip_list(payload: bytes, writer) -> None:
        '''
        Detects the trips in the requested window (a week) and replies to the
        requesting client only. A malformed request or an unreachable InfluxDB yields
        an empty list rather than no reply, so the Trips dropdown never hangs.
        '''
        window = _parse_window(payload, "TRIP_GET_LIST")
        if window is None:
            return
        start_ms, end_ms = window
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
        await server.send_to(
            writer, _build_window_list_frame(protocol.TRIP_LIST, start_ms, end_ms, records))

    async def _get_trip_detail(payload: bytes, writer) -> None:
        '''
        Loads the selected trip's GPS + speed route and replies to the requesting
        client only. The trip's [start_ms, end_ms] window is echoed by the client
        (known from the prior TRIP_LIST), so no re-detection is needed. A window that
        logged no fixes replies status=0 (no data) rather than no reply.
        '''
        window = _parse_window(payload, "TRIP_GET_DETAIL")
        if window is None:
            return
        start_ms, end_ms = window
        route = []
        try:
            route = await trip_loader.load_route(start_ms, end_ms)
        except Exception as e:
            logger.warning("TRIP_GET_DETAIL failed: %s: %s", type(e).__name__, e)
        await server.send_to(writer, _build_route_frame(protocol.TRIP_DETAIL, start_ms, route))

    async def _get_current_trip(_payload: bytes, writer) -> None:
        '''
        Finds the drive under way and replies with its route so far, to the requesting
        client only. No drive, or an unreachable InfluxDB, replies trip_id 0 rather
        than no reply, so the map's route layer clears instead of holding a stale drive.
        '''
        trip_id = 0
        route = []
        try:
            now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            trip = await trip_loader.current_trip(now_ms)
            if trip is not None:
                trip_id = trip.start_ms
                route = await trip_loader.load_route(trip.start_ms, now_ms)
        except Exception as e:
            logger.warning("TRIP_GET_CURRENT failed: %s: %s", type(e).__name__, e)
        await server.send_to(writer, _build_route_frame(protocol.TRIP_CURRENT, trip_id, route))

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
        window = _parse_window(payload, "TRIP_GET_SUMMARY")
        if window is None:
            return
        start_ms, end_ms = window
        summary = None
        try:
            summary = await trip_loader.load_summary(start_ms, end_ms)
        except Exception as e:
            logger.warning("TRIP_GET_SUMMARY failed: %s: %s", type(e).__name__, e)
        await server.send_to(
            writer, _build_summary_frame(protocol.TRIP_SUMMARY, _TRIP_SUMMARY_FIELDS,
                                         start_ms, start_ms, end_ms, summary)
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
            time_start, time_end = _history_range(protocol.HISTORY_RANGE_CUSTOM, start_ms, end_ms)
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
        window = _parse_window(payload, "CHARGING_GET_LIST")
        if window is None:
            return
        start_ms, end_ms = window
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
        await server.send_to(
            writer, _build_window_list_frame(protocol.CHARGING_LIST, start_ms, end_ms, records))

    async def _get_charging_summary(payload: bytes, writer) -> None:
        '''
        Computes the selected session's loss breakdown and replies to the requesting
        client only. The session's [start_ms, end_ms] window is echoed by the client
        (known from the prior CHARGING_LIST), so no re-detection is needed. A malformed
        request or a failed computation replies status=0 rather than no reply, so the
        panel never hangs. Mirrors _get_trip_summary.
        '''
        window = _parse_window(payload, "CHARGING_GET_SUMMARY")
        if window is None:
            return
        start_ms, end_ms = window
        summary = None
        try:
            summary = await charging_loader.load_summary(start_ms, end_ms)
        except Exception as e:
            logger.warning("CHARGING_GET_SUMMARY failed: %s: %s", type(e).__name__, e)
        await server.send_to(
            writer, _build_summary_frame(protocol.CHARGING_SUMMARY, _CHARGING_SUMMARY_FIELDS,
                                         start_ms, start_ms, end_ms, summary)
        )

    async def _get_charging_month(_payload: bytes, writer) -> None:
        '''
        Computes the month-to-date charging aggregate (energy, waste, efficiency,
        consumption/km, sessions, spot-priced cost, home import + cost) and replies to the
        requesting client only. The month runs from the 1st (00:00 in the configured
        timezone) to now. Both cost fields are computed inside month_summary (the loader
        owns the spot provider + flat tariff), so this handler just derives the window and
        packs. A failed computation replies status=0 rather than no reply, so the stats
        grid never hangs.
        '''
        summary = None
        try:
            now = datetime.now(config.zone_info)
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            now_ms = int(now.timestamp() * 1000)
            month_start_ms = int(month_start.timestamp() * 1000)
            summary = await charging_loader.month_summary(month_start_ms, now_ms)
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
        request = _parse_history_request(payload, "CHARGER_GET_HISTORY")
        if request is None:
            return
        range_code, data_property_id, start_ms, end_ms = request

        time_start, time_end = _history_range(range_code, start_ms, end_ms)
        result = None
        try:
            result = await charging_loader.get_power_history(
                data_property_id, time_start, time_end
            )
        except ValueError as e:
            # Malformed id — reply empty rather than dropping the request.
            logger.warning("CHARGER_GET_HISTORY rejected: %s", e)
        await server.send_to(
            writer, _build_history_frame(protocol.CHARGER_HISTORY, data_property_id, result))

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
    server.register_handler(protocol.TRIP_GET_CURRENT,           _get_current_trip)
    server.register_handler(protocol.CHARGING_GET_LIST,          _get_charging_list)
    server.register_handler(protocol.CHARGING_GET_SUMMARY,       _get_charging_summary)
    server.register_handler(protocol.CHARGING_GET_MONTH,         _get_charging_month)
    server.register_handler(protocol.CHARGER_GET_HISTORY,        _get_charger_history)
    # Options view: schema request / one-setting write / restart request. The
    # write handler replies to this client and broadcasts the new schema itself.
    server.register_handler(protocol.CONFIG_GET_SCHEMA,          config_service.handle_get_schema)
    server.register_handler(protocol.CONFIG_SET,                 config_service.handle_set)
    server.register_handler(protocol.CONFIG_RESTART,             config_service.handle_restart)


async def main():
    configure_logging()
    logger.info("Tesla Homedash services starting")

    missing = [key for key in REQUIRED_ENV_VARS if not get_env(key)]
    if missing:
        raise RuntimeError(
            f"Required environment variables not set: {', '.join(missing)}"
        )

    # Load and validate config.json once; every service receives this instance.
    config = Config(get_env("CONFIG_PATH") or default_config_path())

    vin = get_env("VIN")
    api_key = get_env("API_KEY")

    influx_handler = InfluxDBHandler(
        url=os.getenv("INFLUX_URL", "http://localhost:8086"),
        org=os.getenv("INFLUX_ORG", "Tesla-Homedash"),
        zone_info=config.zone_info,
    )
    logger.debug("InfluxDB handler initialized")

    # The login gate and the TLS certificate (issue #64). Built before the server,
    # which needs both; it needs the server back for its broadcasts. No password
    # in .env leaves the backend running but every display refused.
    auth = AuthService(config=config, password=get_env("TESLA_HOMEDASH_PASSWORD"))
    server = Server(ssl_context=auth.ssl_context, authenticator=auth, host=config.listen_host)
    auth.attach_server(server)
    logger.debug("TLS server initialized")

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

    # Trip detection (issue #5/#6): stateless request/response, so no run task and
    # no snapshot.
    trip_loader = TripLoader(influx_handler, config)
    logger.debug("Trip loader initialized")

    # Spot pricing (issue #12). Constructed whether or not there is a charger: the live
    # price tile and the on-demand cost path both use it, and when it is disabled every
    # method no-ops and cost falls back to the flat tariff.
    spot_provider = SpotPriceProvider(config)
    logger.debug("Spot price provider initialized")

    # Charging-loss analysis: stateless, and constructed unconditionally so the charging
    # handlers always answer (an empty list when no charger data exists).
    charging_loader = ChargingLoader(influx_handler, config, spot_provider=spot_provider)
    logger.debug("Charging loader initialized")

    # The Charging view's live price tile; works without a Zappi, and run() no-ops when
    # spot pricing is disabled.
    spot_price_service = SpotPriceService(server=server, config=config, provider=spot_provider)
    logger.debug("Spot price service initialized")

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

    # Spotify re-authorization from the Options view. The client secret, the
    # redirect listener and every token stay in the backend.
    spotify_auth = SpotifyAuthService(config=config, server=server, media_manager=mm)
    # Let the player announce a dead or renewed grant immediately, instead of the
    # dashboard finding out at its next reconnect.
    mm.set_spotify_auth_listener(spotify_auth.notify_auth_state_changed)
    logger.debug("Spotify auth service initialized")

    # The spectrum of what is playing: records only while a display watches.
    spectrum = AudioSpectrum(server=server)
    # Host audio (system volume + output device). Always constructed: detection is
    # at most three cheap subprocess probes and needs no credentials, and a host with no
    # controllable audio stack must be able to SAY so rather than silently accept
    # writes that do nothing.
    audio = AudioService(config=config, spectrum=spectrum)
    logger.debug("Audio service initialized")

    display = DisplayService(server=server)
    logger.debug("Display service initialized")

    # Screensaver photos from a USB stick. On demand only, no snapshot: the
    # Options view's import dialog asks for everything it shows.
    usb_import = UsbImportService(server=server)
    logger.debug("USB import service initialized")

    # The Options view's maintenance dashboard and the Järjestelmän tila cards.
    # Request/response and registered with no snapshot: a status page nobody has
    # opened is not worth sampling /proc for on every connect. Each probe claims
    # the loggers whose warnings and errors its card counts; the server card
    # takes every logger nobody else claims, so no warning goes unlisted. The
    # order here is the cards' order.
    log_files = LogFiles(server=server)
    system_status = SystemStatusService(server=server, error_log=error_log())
    started_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    def _server_health() -> dict:
        '''The backend process, what it runs and the frontends connected to it.
        `updater` is built further down, like `telemetry` below.'''
        count = server.client_count
        return {
            "state": "ok" if count else "warn",
            "detail": "1 näyttö yhdistetty" if count == 1 else f"{count} näyttöä yhdistetty",
            "config": [
                ["Versio", updater.version_label() or "—"],
                ["Portti", str(server.PORT)],
                ["Käynnistetty", {"time": started_ms}],
                ["Muisti", {"bytes": system_metrics.read_process_rss_bytes()}],
                ["Asetukset", config.path],
            ],
            "items": server.clients(),
        }

    system_status.register_probe(
        "server", "Palvelin", _server_health, catch_all=True,
        loggers=("server", "start_services", "utils", "config_service", "system_service",
                 "usb_import_service", "update_service"))

    async def _tesla_health() -> dict:
        '''The Teslemetry stream. `telemetry` is built further down, before the
        server starts — and nothing can ask for a probe before that.'''
        return await telemetry.health()

    system_status.register_probe("tesla", "Tesla", _tesla_health, loggers=("tesla_service",))
    system_status.register_probe("influx", "InfluxDB", influx_handler.health,
                                 loggers=("influxdb_service",))
    system_status.register_probe("radio", "Radio", mm.radio_health,
                                 loggers=("media_service.radio_player", "media_service.media_manager"))

    def _spotify_health() -> dict:
        '''The Spotify grant, the device it plays on and the player's polling.'''
        status = spotify_auth.build_status()
        player = mm.spotify_state()
        device = config.get("spotifyDeviceName") or config.spotify_device_id
        config_rows = [
            ["Tili", status.get("email") or status.get("displayName") or "—"],
            ["Laite", device or "Ei valittu"],
            ["Kyselyväli", f"{player['poll_s']} s"],
        ]
        if status.get("validUntil"):
            config_rows.append(["Tunnistus voimassa", {"time": int(status["validUntil"]) * 1000}])
        if not status["authorized"]:
            return {"state": "error" if status.get("needsReauth") else "warn",
                    "detail": status["reason"], "config": config_rows}
        if not device:
            return {"state": "warn", "detail": "Laitetta ei ole valittu", "config": config_rows}
        detail = ("Soittaa" if player["playing"] else "Ohjaa toistoa") if player["active"] \
            else "Odottaa toistoa laitteella"
        return {"state": "ok", "detail": detail, "config": config_rows}

    system_status.register_probe("spotify", "Spotify", _spotify_health,
                                 loggers=("media_service.spotify_player", "media_service.spotify_auth",
                                          "media_service.spotify_device", "media_service.spotify_oauth",
                                          "spotipy"))
    system_status.register_probe("weather", "Sää", weather.health, loggers=("weather_service",))

    def _charger_health() -> dict:
        '''Charging in one card, as in the Options view's Sähkö › Laturi: the
        Zappi poll's standing, then the Charging view's session detection, which
        reads InfluxDB on request and works with or without a Zappi.'''
        if myenergi is not None:
            result = myenergi.health()
        else:
            result = {"state": "off", "detail": "myenergi-tunnukset puuttuvat (.env)", "config": []}
        block = config.myenergi_config
        result["config"] = result.get("config", []) + [
            ["Latauksen vähimmäisenergia", f"{float(block['minSessionEnergyKwh']):.1f} kWh"],
            ["Istuntojen yhdistysväli", f"{int(block['sessionMergeMinutes'])} min"],
        ]
        return result

    system_status.register_probe("charger", "Laturi", _charger_health,
                                 loggers=("myenergi_service", "charging_service.charging_loader",
                                          "charging_service.charging_session"))
    system_status.register_probe("spot_price", "Pörssisähkö", spot_price_service.health,
                                 loggers=("charging_service.spot_price", "charging_service.spot_price_service"))

    def _trips_health() -> dict:
        '''The Trips view's detection settings (Tesla › Matkojen tunnistus); it
        reads InfluxDB on request and keeps no running state of its own.'''
        trip = config.trip_config
        return {"state": "ok", "detail": "Haetaan tietokannasta pyydettäessä", "config": [
            ["Pysähdyksen vähimmäiskesto", f"{trip['min_stop_minutes']} min"],
            ["Matkan vähimmäispituus", f"{float(trip['min_trip_distance_km']):g} km"],
        ]}

    system_status.register_probe("trips", "Matkat", _trips_health, loggers=("trip_service",))
    system_status.register_probe("auth", "Kirjautuminen", auth.health, loggers=("auth_service",))
    system_status.register_probe("audio", "Ääni", audio.health, loggers=("audio_service",))
    system_status.register_probe("display", "Näyttö", display.health, loggers=("display_service",))
    logger.debug("System status service initialized")

    # The Järjestelmän tila graphs: unlike the status document, sampled all the
    # time, because a graph needs the minutes before anyone opened it.
    system_history = SystemHistory(server=server)

    # Runtime configuration (the Options view). Every service snapshots its
    # config at construction and never re-reads it, so applying a change means
    # calling that service's apply_config(); a setting whose hook is missing
    # (e.g. no Zappi -> no MyEnergiService) is reported to the frontend as
    # restart-tier instead of silently doing nothing.
    config_service = ConfigService(config=config, server=server)
    config_service.register_hook("weather", weather.apply_config)
    config_service.register_hook("trip", trip_loader.apply_config)
    config_service.register_hook("charging", charging_loader.apply_config)
    config_service.register_hook("spot_price", spot_provider.apply_config)
    config_service.register_hook("spotify", mm.apply_config_spotify)
    config_service.register_hook("media", mm.apply_config_media)
    config_service.register_hook("audio", audio.apply_config)
    config_service.register_hook("auth", auth.apply_config)
    # The audio stack owns its own enum choices and its own "this host cannot do
    # that" veto, so config_service needs to know nothing about audio.
    config_service.register_options("audio.outputDevice", audio.device_options)
    config_service.register_guard("audio", audio.guard_write)
    # The equalizer: its own hook (a band write must not re-push the volume and
    # output), its own veto (it needs PipeWire, not merely some audio stack) and
    # its state, on the bass row — the card's one entry the frontend does not
    # strip as hidden, so the card's widget can read it.
    config_service.register_hook("equalizer", audio.apply_equalizer)
    config_service.register_guard("equalizer", audio.guard_equalizer)
    config_service.register_runtime("audio.bassBoost", audio.equalizer_runtime)
    # Wired back the other way too: on a first start with no stored volume, audio
    # stores the host's current level through config_service rather than pushing
    # the schema default over it.
    audio.attach_config_service(config_service)
    if myenergi is not None:
        config_service.register_hook("myenergi", myenergi.apply_config)
    logger.debug("Config service initialized")

    # The log level (Ylläpito › Lokit). Applied once now, so a DEBUG left on
    # across a restart comes back on — for one more duration only.
    log_level = LogLevel(config=config, config_service=config_service, log_files=log_files)
    config_service.register_hook("logging", log_level.apply_config)
    config_service.register_runtime("logging.level", log_level.runtime_info)
    log_level.apply_config()
    system_status.register_probe("logging", "Loki", log_level.health)

    # The Options view's "Tunnista laite" scan. Constructed AFTER config_service
    # because it writes spotifyDeviceId through it: the id is in SETTINGS_SCHEMA,
    # so the scan's write gets the same validation, atomic save and apply hook a
    # CONFIG_SET does. Not in the services list below — a scan is user-initiated,
    # and the device status costs a Spotify call, so both are served on request.
    spotify_devices = SpotifyDeviceService(
        config=config, server=server, media_manager=mm,
        config_service=config_service,
    )
    logger.debug("Spotify device service initialized")

    # In-place app updates (the Options view's "Päivitys" card). Constructed
    # after config_service because that owns the only way out of this process:
    # the updater rewrites the checkout underneath us and then has to come back
    # on the new code, which is the same exit CONFIG_RESTART performs.
    updater = UpdateService(server=server, config_service=config_service)
    logger.debug("Update service initialized")

    # The Options view's telemetry-field table: log / line_mode / zero_based per
    # `tesla data` field, written to config.json and applied to the live vehicle.
    # Request/response only, so it is not in the services list below.
    property_editor = TeslaPropertyEditor(config=config, vehicle=vehicle, server=server)

    # Wire incoming-message dispatch and on-connect snapshot before start().
    _register_handlers(
        server, mm, vehicle, trip_loader, charging_loader, config, config_service
    )
    server.register_handler(protocol.DISPLAY_SET_POWER, display.handle_set_power)
    server.register_handler(protocol.MEDIA_SPECTRUM_WATCH, spectrum.handle_watch)
    server.register_handler(protocol.SPOTIFY_AUTH_GET_URL, spotify_auth.handle_get_url)
    server.register_handler(protocol.SPOTIFY_DEVICE_SCAN_START, spotify_devices.handle_scan_start)
    server.register_handler(protocol.SPOTIFY_DEVICE_SCAN_STOP, spotify_devices.handle_scan_stop)
    server.register_handler(protocol.SPOTIFY_DEVICE_SELECT, spotify_devices.handle_select)
    server.register_handler(protocol.SPOTIFY_DEVICE_GET_STATUS, spotify_devices.handle_get_status)
    server.register_handler(protocol.SYSTEM_GET_STATUS, system_status.handle_get_status)
    server.register_handler(protocol.SYSTEM_GET_HISTORY, system_history.handle_get_history)
    server.register_handler(protocol.SYSTEM_GET_LOG, system_status.handle_get_log)
    server.register_handler(protocol.LOG_CLEAR, log_files.handle_clear)
    server.register_handler(protocol.UPDATE_GET_STATE, updater.handle_get_state)
    server.register_handler(protocol.UPDATE_APPLY, updater.handle_apply)
    server.register_handler(protocol.UPDATE_CANCEL, updater.handle_cancel)
    server.register_handler(protocol.HOST_REBOOT, config_service.handle_reboot)
    server.register_handler(protocol.TESLA_GET_PROPERTY_TABLE, property_editor.handle_get)
    server.register_handler(protocol.TESLA_SET_PROPERTY, property_editor.handle_set)
    server.register_handler(protocol.USB_IMPORT_LIST, usb_import.handle_list)
    server.register_handler(protocol.USB_IMPORT_SCAN, usb_import.handle_scan)
    server.register_handler(protocol.USB_IMPORT_START, usb_import.handle_start)
    server.register_handler(protocol.USB_IMPORT_CLOSE, usb_import.handle_close)
    server.register_handler(protocol.AUTH_GET_DISPLAYS, auth.handle_get_displays)
    server.register_handler(protocol.AUTH_REVOKE, auth.handle_revoke)
    services = [vehicle, mm, weather, spot_price_service, config_service, display,
                spotify_auth, updater]
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
    t5 = spot_price_service.get_run_task()

    # Ends only by exiting the process (os._exit) after a CONFIG_RESTART, so
    # gathering it unconditionally is harmless.
    t6 = config_service.get_run_task()

    # Audio detects its stack then refreshes the device list forever; display
    # makes its assumed-on state true and returns.
    # The updater's run task only locates the checkout and publishes the first
    # state; the runs themselves are started by a client and own their own task.
    # The system history samples forever and swallows its own failures.
    tasks = [t1, t2, t3, t4, t5, t6, audio.get_run_task(), display.get_run_task(),
             updater.get_run_task(), system_history.get_run_task()]
    if myenergi is not None:
        tasks.append(myenergi.get_run_task())

    logger.info("All services started, gathering tasks")
    await asyncio.gather(*tasks)


def main_sync():
    asyncio.run(main())


if __name__ == "__main__":
    main_sync()
