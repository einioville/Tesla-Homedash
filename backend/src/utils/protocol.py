'''
Shared binary protocol constants used by the TCP server and the media layer.
Keeping these in a single module prevents silent divergence between the
backend's outgoing byte values and the ones the frontend expects.  All
values are single bytes unless noted otherwise.  See CLAUDE.md
"Binary Protocol Reference" for the authoritative specification.
'''

import struct


# Frontend-to-backend and backend-to-frontend Tesla-data framing
MSG_JSON = 0x01
MSG_LIST = 0x02
MSG_TERMINATE = 0x03
MSG_STREAM = 0x04

# Media stream and control bytes
MEDIA_STREAM_IMAGE = 0x14
MEDIA_STREAM_NAME = 0x15
MEDIA_STREAM_PROGRESS = 0x16
MEDIA_STREAM_DURATION = 0x17
MEDIA_SKIP = 0x18
MEDIA_SKIP_BACKWARD = 0x19
MEDIA_PAUSE_PLAY = 0x1A
MEDIA_IS_PLAYING = 0x1B
MEDIA_SET_PROGRESS = 0x1C
MEDIA_STREAM_ARTISTS = 0x1D
MEDIA_STREAM_TYPE = 0x1E

# Media-type byte values carried inside MEDIA_STREAM_TYPE payloads
MEDIA_TYPE_RADIO = 0x01
MEDIA_TYPE_SPOTIFY = 0x02

# Weather forecast frame and sub-field IDs
WEATHER_FORECAST = 0x30
FORECAST_TEMPERATURE = 0x31
FORECAST_WIND_SPEED = 0x32
FORECAST_PRECIPITATION = 0x33
FORECAST_TOTAL_CLOUD_COVER = 0x34
FORECAST_TIME = 0x35

# Tesla command bytes (frontend -> backend)
TESLA_SWITCH_CLIMATE_STATE = 0x60
TESLA_MINUS_TARGET_TEMP = 0x61
TESLA_PLUS_TARGET_TEMP = 0x62

# Historical-data request/response (the History view). Unlike the fire-and-forget
# command bytes above, these are a request/response pair: the backend replies to
# the requesting client only (server.send_to), never a broadcast.
TESLA_GET_GRAPH_PROPERTIES = 0x70  # F->B: request the graphable-property list (empty payload)
TESLA_GRAPH_PROPERTIES = 0x71      # B->F: count(2B) + per property id/unit/category (each len(2B)+UTF-8)
TESLA_GET_HISTORY = 0x72           # F->B: range_code(1B) + id(len(2B)+UTF-8) + start_ms(8B) + end_ms(8B)
TESLA_HISTORY = 0x73               # B->F: id(len(2B)+UTF-8) + status(1B) + count(4B) + count*(ts_ms(8B)+value(8B double))

# Trip request/response (the Trips view, issue #6). Contiguous with the History
# codes above and, like them, a request/response pair: the backend replies to the
# requesting client only (server.send_to), never a broadcast. A trip's natural key
# is its start_ms, echoed in TRIP_DETAIL so a stale reply can be discarded.
TRIP_GET_LIST = 0x74    # F->B: start_ms(8B) + end_ms(8B)  — the query window (a week)
TRIP_LIST = 0x75        # B->F: req_start_ms(8B) + req_end_ms(8B) + count(2B) + count*(start_ms(8B) + end_ms(8B) + distance_km(8B double))
                        #       (the echoed request window lets the client drop an out-of-order reply)
TRIP_GET_DETAIL = 0x76  # F->B: start_ms(8B) + end_ms(8B)  — the selected trip's window
TRIP_DETAIL = 0x77      # B->F: trip_id/start_ms(8B) + status(1B) + count(4B)
                        #       + count*(ts_ms(8B) + lat(8B double) + lon(8B double) + speed_kmh(8B double))
TRIP_GET_WEEK_COUNTS = 0x78  # F->B: num_weeks(2B) + num_weeks*(week_start_ms(8B) + week_end_ms(8B))
TRIP_WEEK_COUNTS = 0x79      # B->F: num_weeks(2B) + num_weeks*(week_start_ms(8B) + trip_count(2B))
                             #       (populates the week-selector dropdown's per-week counts;
                             #       week_start_ms is echoed so the client matches counts to weeks)

# Per-trip stats + graph (the Trips-view detail panel). Same request/response
# convention as the trip codes above — replied to the requesting client only, with
# the trip's start_ms echoed as trip_id so a stale reply (after switching trip) is
# dropped. The summary carries the values Trip.summary() already computes; the
# series reuses the History read path (get_data_history over the trip window) to
# return one numeric property's raw time series for the graph.
TRIP_GET_SUMMARY = 0x7A  # F->B: start_ms(8B) + end_ms(8B)  — the selected trip's window
TRIP_SUMMARY = 0x7B      # B->F: trip_id(8B) + status(1B) + start_ms(8B) + end_ms(8B)
                         #       + 7*double(8B): distance_km, avg_speed, max_speed,
                         #       energy_wh, wh_per_km, start_soc, end_soc (any may be NaN)
TRIP_GET_SERIES = 0x7C   # F->B: start_ms(8B) + end_ms(8B) + id(len(2B)+UTF-8)  — one property over the trip
TRIP_SERIES = 0x7D       # B->F: trip_id(8B) + id(len(2B)+UTF-8) + status(1B) + count(4B)
                         #       + count*(ts_ms(8B) + value(8B double))

# MyEnergi (Zappi) charger live stream (backend -> frontend). Like the weather
# frame, a CHARGER_STREAM packet is a sequence of (sub_id(1B) + value) pairs; each
# fixed-width sub_id implies its value width, so fields can be added without a format
# bump, and a field absent from a given frame just keeps its last value on the
# frontend. The one variable-width sub_id, CHARGER_RAW_JSON, is length-prefixed (4B)
# so it stays self-delimiting. The service polls the myenergi cloud (pymyenergi) and
# broadcasts this; a new client gets the last frame replayed via stream_everything.
CHARGER_STREAM = 0x50
CHARGER_STATUS = 0x51           # uint8: see CHARGER_STATUS_* below
CHARGER_PLUG_STATUS = 0x52      # uint8: see CHARGER_PLUG_* below
CHARGER_MODE = 0x53             # uint8: see CHARGER_MODE_* below
CHARGER_CHARGE_POWER = 0x54     # float64: power currently delivered to the car (W)
CHARGER_SESSION_ENERGY = 0x55   # float64: energy added this charging session (kWh)
CHARGER_SUPPLY_VOLTAGE = 0x56   # uint16: supply voltage (V)
CHARGER_GRID_POWER = 0x57       # float64: net grid power (W); + import from grid / - export
CHARGER_GENERATED_POWER = 0x58  # float64: local generation power (W), e.g. solar / PV
CHARGER_SUPPLY_FREQUENCY = 0x59 # float64: supply frequency (Hz)
CHARGER_L1_PHASE = 0x5A         # uint8: which phase L1 is wired to (pymyenergi Zappi.l1_phase)
CHARGER_RAW_JSON = 0x5F         # length(4B) + UTF-8 JSON: the complete raw pymyenergi
                                #   Zappi.data payload — every field the myenergi API
                                #   returned this poll (most never used). Lets new fields
                                #   reach the frontend with no protocol change.

# CHARGER_STATUS enum (maps pymyenergi Zappi.status: Paused/Charging/Completed)
CHARGER_STATUS_UNKNOWN = 0
CHARGER_STATUS_PAUSED = 1
CHARGER_STATUS_CHARGING = 2
CHARGER_STATUS_COMPLETED = 3

# CHARGER_PLUG_STATUS enum (maps pymyenergi Zappi.plug_status)
CHARGER_PLUG_UNKNOWN = 0
CHARGER_PLUG_DISCONNECTED = 1
CHARGER_PLUG_CONNECTED = 2
CHARGER_PLUG_WAITING = 3
CHARGER_PLUG_READY = 4
CHARGER_PLUG_CHARGING = 5
CHARGER_PLUG_FAULT = 6

# CHARGER_MODE enum (maps pymyenergi Zappi.charge_mode: Fast/Eco/Eco+/Stopped)
CHARGER_MODE_UNKNOWN = 0
CHARGER_MODE_FAST = 1
CHARGER_MODE_ECO = 2
CHARGER_MODE_ECO_PLUS = 3
CHARGER_MODE_STOPPED = 4

# Charging-session request/response (the Charging / charging-losses view). Same
# request/response convention as the Trips codes above: replied to the requesting
# client only (server.send_to), never broadcast. A session's natural key is its
# start_ms, echoed in the summary reply so a stale reply can be discarded. Sessions
# are derived on demand from stored telemetry (DetailedChargeState segmentation)
# joined to the logged myenergi charger energy — see charging_service.
CHARGING_GET_LIST = 0x80   # F->B: start_ms(8B) + end_ms(8B)  — the query window
CHARGING_LIST = 0x81       # B->F: req_start_ms(8B) + req_end_ms(8B) + count(2B)
                           #       + count*(start_ms(8B) + end_ms(8B) + charger_kwh(8B double))
                           #       (the echoed request window lets the client drop an out-of-order reply)
CHARGING_GET_SUMMARY = 0x82  # F->B: start_ms(8B) + end_ms(8B)  — the selected session's window
CHARGING_SUMMARY = 0x83      # B->F: session_id(8B) + status(1B) + start_ms(8B) + end_ms(8B)
                             #       + 9*double(8B): charger_kwh, ac_in_kwh, battery_kwh,
                             #       loss_cable_kwh, loss_conversion_kwh, loss_total_kwh,
                             #       loss_total_pct, start_soc, end_soc (any may be NaN)

# Month-to-date charging aggregate (the Charging view's stats grid). Request/response,
# replied to the requesting client only. The backend derives the month window from the
# 1st (00:00 in the configured timezone) to now, sums the myenergi-detected sessions and
# reads the tesla month counters, so the request carries no window.
CHARGING_GET_MONTH = 0x84  # F->B: (empty)
CHARGING_MONTH = 0x85      # B->F: status(1B) + 12*double(8B): charger_kwh, car_kwh,
                           #       wasted_kwh, efficiency_pct, car_wh_per_km, charger_wh_per_km,
                           #       driving_kwh, km_month, session_count, total_charge_s,
                           #       charging_cost_eur, home_grid_kwh (any may be NaN)

# Charger (myenergi) telemetry history — the Charging view's past-hour power graphs.
# Request/response, replied to the requesting client only. Same shape as TESLA_HISTORY,
# but read from the "myenergi_data" measurement (GridPower / ChargePower), which is now
# logged every poll so the series is gap-free.
CHARGER_GET_HISTORY = 0x86  # F->B: range_code(1B) + id(len(2B)+UTF-8) + start_ms(8B) + end_ms(8B)
CHARGER_HISTORY = 0x87      # B->F: id(len(2B)+UTF-8) + status(1B) + count(4B) + count*(ts_ms(8B)+value(8B double))

# Maximum accepted size of a single incoming message (defensive cap)
MAX_MSG_SIZE = 1024 * 1024  # 1 MB


def frame(msg_type: int, payload: bytes = b"") -> bytes:
    '''
    Wraps a message in the wire format: [4B length][1B type][payload].
    Length covers the type byte plus the payload.  Used by every service
    to build packets so the framing logic lives in exactly one place.
    Arguments:
        msg_type (int): Single-byte message type from the constants above.
        payload (bytes): Type-specific payload bytes; empty for commands.
    '''
    body = bytes((msg_type,)) + payload
    return struct.pack("!I", len(body)) + body
