#ifndef FRONTEND_V2_PROTOCOL_HH
#define FRONTEND_V2_PROTOCOL_HH

#include <QByteArray>
#include <QtEndian>
#include <QtGlobal>

/**
 * Binary protocol constants + outbound framing — the frontend mirror of
 * backend/src/utils/protocol.py. Keep the two in lockstep: these byte values
 * are the contract between the asyncio backend and this client. All multi-byte
 * integers on the wire are big-endian.
 *
 * Inbound frames are reassembled and stripped in ServerClient; frame() here is
 * the single place OUTBOUND packets are built (commands in later stages).
 */
namespace protocol {

// Tesla-data framing (both directions)
inline constexpr quint8 MSG_JSON = 0x01;       // reserved/legacy — unused by this client
inline constexpr quint8 MSG_LIST = 0x02;       // reserved/legacy — unused by this client
inline constexpr quint8 MSG_TERMINATE = 0x03;
inline constexpr quint8 MSG_STREAM = 0x04;

// Media stream + control bytes
inline constexpr quint8 MEDIA_STREAM_IMAGE = 0x14;
inline constexpr quint8 MEDIA_STREAM_NAME = 0x15;
inline constexpr quint8 MEDIA_STREAM_PROGRESS = 0x16;
inline constexpr quint8 MEDIA_STREAM_DURATION = 0x17;
inline constexpr quint8 MEDIA_SKIP = 0x18;
inline constexpr quint8 MEDIA_SKIP_BACKWARD = 0x19;
inline constexpr quint8 MEDIA_PAUSE_PLAY = 0x1A;
inline constexpr quint8 MEDIA_IS_PLAYING = 0x1B;
inline constexpr quint8 MEDIA_SET_PROGRESS = 0x1C;
inline constexpr quint8 MEDIA_STREAM_ARTISTS = 0x1D;
inline constexpr quint8 MEDIA_STREAM_TYPE = 0x1E;

// Media-type byte values carried inside MEDIA_STREAM_TYPE payloads
inline constexpr quint8 MEDIA_TYPE_RADIO = 0x01;
inline constexpr quint8 MEDIA_TYPE_SPOTIFY = 0x02;

// Weather forecast frame + sub-field IDs
inline constexpr quint8 WEATHER_FORECAST = 0x30;
inline constexpr quint8 FORECAST_TEMPERATURE = 0x31;
inline constexpr quint8 FORECAST_WIND_SPEED = 0x32;
inline constexpr quint8 FORECAST_PRECIPITATION = 0x33;
inline constexpr quint8 FORECAST_TOTAL_CLOUD_COVER = 0x34;
inline constexpr quint8 FORECAST_TIME = 0x35;

// Tesla command bytes (frontend -> backend)
inline constexpr quint8 TESLA_SWITCH_CLIMATE_STATE = 0x60;
inline constexpr quint8 TESLA_MINUS_TARGET_TEMP = 0x61;
inline constexpr quint8 TESLA_PLUS_TARGET_TEMP = 0x62;

// History request/response (the History view). A request/response pair: the
// backend replies to this client only (not a broadcast). Keep in lockstep with
// protocol.py.
inline constexpr quint8 TESLA_GET_GRAPH_PROPERTIES = 0x70;  // F->B: request graphable-property list (empty)
inline constexpr quint8 TESLA_GRAPH_PROPERTIES = 0x71;      // B->F: count(2B) + per property id/unit/category (len(2B)+UTF-8)
inline constexpr quint8 TESLA_GET_HISTORY = 0x72;           // F->B: range_code(1B) + id(len(2B)+UTF-8) + start_ms(8B) + end_ms(8B)
inline constexpr quint8 TESLA_HISTORY = 0x73;               // B->F: id(len(2B)+UTF-8) + status(1B) + count(4B) + count*(ts_ms(8B)+value(8B double))

// Trip request/response (the Trips view). Contiguous with the History codes and,
// like them, a request/response pair — the backend replies to this client only.
// A trip's natural key is its start_ms, echoed in TRIP_DETAIL so a stale reply
// (after switching trip) can be discarded. Keep in lockstep with protocol.py.
inline constexpr quint8 TRIP_GET_LIST = 0x74;    // F->B: start_ms(8B) + end_ms(8B)
inline constexpr quint8 TRIP_LIST = 0x75;        // B->F: req_start_ms(8B) + req_end_ms(8B) + count(2B) + count*(start_ms(8B) + end_ms(8B) + distance_km(8B double))
inline constexpr quint8 TRIP_GET_DETAIL = 0x76;  // F->B: start_ms(8B) + end_ms(8B)
inline constexpr quint8 TRIP_DETAIL = 0x77;      // B->F: trip_id(8B) + status(1B) + count(4B) + count*(ts_ms(8B) + lat(8B double) + lon(8B double) + speed_kmh(8B double))
inline constexpr quint8 TRIP_GET_WEEK_COUNTS = 0x78;  // F->B: num_weeks(2B) + num_weeks*(week_start_ms(8B) + week_end_ms(8B))
inline constexpr quint8 TRIP_WEEK_COUNTS = 0x79;      // B->F: num_weeks(2B) + num_weeks*(week_start_ms(8B) + trip_count(2B))

// Per-trip stats + graph (the Trips-view detail panel). Same request/response
// convention: replied to this client only, trip_id (== start_ms) echoed so a stale
// reply (after switching trip) is dropped. TRIP_SERIES also echoes the property id.
inline constexpr quint8 TRIP_GET_SUMMARY = 0x7A;  // F->B: start_ms(8B) + end_ms(8B)
inline constexpr quint8 TRIP_SUMMARY = 0x7B;      // B->F: trip_id(8B) + status(1B) + start_ms(8B) + end_ms(8B) + 7*double(8B): distance_km, avg_speed, max_speed, energy_wh, wh_per_km, start_soc, end_soc
inline constexpr quint8 TRIP_GET_SERIES = 0x7C;   // F->B: start_ms(8B) + end_ms(8B) + id(len(2B)+UTF-8)
inline constexpr quint8 TRIP_SERIES = 0x7D;       // B->F: trip_id(8B) + id(len(2B)+UTF-8) + status(1B) + count(4B) + count*(ts_ms(8B)+value(8B double))

// MyEnergi (Zappi) charger live stream (backend -> frontend broadcast). A sequence of
// (sub_id(1B) + value) pairs; each fixed-width sub_id implies its value width. The one
// variable-width sub_id, CHARGER_RAW_JSON, is length-prefixed (4B). Mirror of protocol.py.
inline constexpr quint8 CHARGER_STREAM = 0x50;
inline constexpr quint8 CHARGER_STATUS = 0x51;            // uint8 (CHARGER_STATUS_*)
inline constexpr quint8 CHARGER_PLUG_STATUS = 0x52;       // uint8 (CHARGER_PLUG_*)
inline constexpr quint8 CHARGER_MODE = 0x53;              // uint8 (CHARGER_MODE_*)
inline constexpr quint8 CHARGER_CHARGE_POWER = 0x54;      // float64 W
inline constexpr quint8 CHARGER_SESSION_ENERGY = 0x55;    // float64 kWh
inline constexpr quint8 CHARGER_SUPPLY_VOLTAGE = 0x56;    // uint16 V
inline constexpr quint8 CHARGER_GRID_POWER = 0x57;        // float64 W (+import/-export)
inline constexpr quint8 CHARGER_GENERATED_POWER = 0x58;   // float64 W (solar/PV)
inline constexpr quint8 CHARGER_SUPPLY_FREQUENCY = 0x59;  // float64 Hz
inline constexpr quint8 CHARGER_L1_PHASE = 0x5A;          // uint8
inline constexpr quint8 CHARGER_RAW_JSON = 0x5F;          // len(4B) + UTF-8 JSON (full raw Zappi payload)

// CHARGER_STATUS enum (maps pymyenergi Zappi.status)
inline constexpr quint8 CHARGER_STATUS_UNKNOWN = 0;
inline constexpr quint8 CHARGER_STATUS_PAUSED = 1;
inline constexpr quint8 CHARGER_STATUS_CHARGING = 2;
inline constexpr quint8 CHARGER_STATUS_COMPLETED = 3;
// CHARGER_PLUG_STATUS enum
inline constexpr quint8 CHARGER_PLUG_UNKNOWN = 0;
inline constexpr quint8 CHARGER_PLUG_DISCONNECTED = 1;
inline constexpr quint8 CHARGER_PLUG_CONNECTED = 2;
inline constexpr quint8 CHARGER_PLUG_WAITING = 3;
inline constexpr quint8 CHARGER_PLUG_READY = 4;
inline constexpr quint8 CHARGER_PLUG_CHARGING = 5;
inline constexpr quint8 CHARGER_PLUG_FAULT = 6;
// CHARGER_MODE enum
inline constexpr quint8 CHARGER_MODE_UNKNOWN = 0;
inline constexpr quint8 CHARGER_MODE_FAST = 1;
inline constexpr quint8 CHARGER_MODE_ECO = 2;
inline constexpr quint8 CHARGER_MODE_ECO_PLUS = 3;
inline constexpr quint8 CHARGER_MODE_STOPPED = 4;

// Charging-losses / month request/response + charger telemetry history (the Charging
// view). All replied to this client only. Keep in lockstep with protocol.py.
inline constexpr quint8 CHARGING_GET_LIST = 0x80;    // F->B: start_ms(8B) + end_ms(8B)
inline constexpr quint8 CHARGING_LIST = 0x81;        // B->F: req_start(8B)+req_end(8B)+count(2B)+count*(start(8B)+end(8B)+charger_kwh(8B))
inline constexpr quint8 CHARGING_GET_SUMMARY = 0x82; // F->B: start_ms(8B) + end_ms(8B)
inline constexpr quint8 CHARGING_SUMMARY = 0x83;     // B->F: session_id(8B)+status(1B)+start(8B)+end(8B)+11*double (…, end_soc, cost_eur, avg_price_eur_per_kwh)
inline constexpr quint8 CHARGING_GET_MONTH = 0x84;   // F->B: (empty)
inline constexpr quint8 CHARGING_MONTH = 0x85;       // B->F: status(1B) + 13*double (charger_kwh, car_kwh, wasted_kwh, efficiency_pct, car_wh_per_km, charger_wh_per_km, driving_kwh, km_month, session_count, total_charge_s, charging_cost_eur, home_grid_kwh, home_cost_eur)
inline constexpr quint8 CHARGER_GET_HISTORY = 0x86;  // F->B: range_code(1B)+id(len(2B)+UTF-8)+start(8B)+end(8B)
inline constexpr quint8 CHARGER_HISTORY = 0x87;      // B->F: id(len(2B)+UTF-8)+status(1B)+count(4B)+count*(ts(8B)+value(8B double))

// Live Nord Pool spot price broadcast (the Charging view's current-price tile). Mirror of
// protocol.py: status 0 => no price (fields NaN), else 1. spot is raw wholesale €/kWh,
// allIn the VAT+margin estimate; hourStartMs is the UTC start of the priced hour.
inline constexpr quint8 SPOT_PRICE_STREAM = 0x88;    // B->F: status(1B)+hour_start_ms(8B)+spot(8B double)+all_in(8B double)

// Runtime configuration (the Options view). Mirror of protocol.py: a request/response
// pair plus one command. Both JSON bodies are len(4B) + UTF-8 (the CHARGER_RAW_JSON
// idiom) because the schema is variable-shaped and these packets are rare. A successful
// CONFIG_SET replies CONFIG_SET_RESULT to this client AND broadcasts a fresh
// CONFIG_SCHEMA to every client, so a second frontend refreshes its values.
inline constexpr quint8 CONFIG_GET_SCHEMA = 0x90;  // F->B: (empty)
inline constexpr quint8 CONFIG_SCHEMA = 0x91;      // B->F: status(1B) + len(4B) + UTF-8 JSON
inline constexpr quint8 CONFIG_SET = 0x92;         // F->B: len(4B) + UTF-8 JSON {"key","value"}
inline constexpr quint8 CONFIG_SET_RESULT = 0x93;  // B->F: status(1B) + len(4B) + UTF-8 JSON
inline constexpr quint8 CONFIG_RESTART = 0x94;     // F->B: (empty) — ask the backend to exit for systemd

// CONFIG_* status byte: 0 = failure (schema unavailable / value rejected, nothing written).
inline constexpr quint8 CONFIG_STATUS_ERROR = 0;
inline constexpr quint8 CONFIG_STATUS_OK = 1;

// History request range codes (mirror the backend _RANGE_* and the QML RangeSelector)
inline constexpr quint8 HISTORY_RANGE_1H = 0;
inline constexpr quint8 HISTORY_RANGE_1D = 1;
inline constexpr quint8 HISTORY_RANGE_1M = 2;
inline constexpr quint8 HISTORY_RANGE_CUSTOM = 3;
inline constexpr quint8 HISTORY_RANGE_1W = 4;

// MSG_STREAM value-type tags (select the payload encoding of a Tesla field)
inline constexpr quint8 VALUE_TYPE_FLOAT = 0;   // double (8B)
inline constexpr quint8 VALUE_TYPE_STRING = 1;  // length(2B) + UTF-8
inline constexpr quint8 VALUE_TYPE_BOOL = 2;    // uint8 (1B)
inline constexpr quint8 VALUE_TYPE_DICT = 3;    // sequence of double(8B) — Location = lat, lon

// Receive-side defensive cap. NOTE the deliberate asymmetry: the backend caps a
// single message at 1 MB (MAX_MSG_SIZE in protocol.py), but this client tolerates
// up to 16 MB before treating the length prefix as corrupt and resetting the
// stream. This is intentional receive-side headroom — do not "fix" it to 1 MB.
inline constexpr qint64 MAX_PACKET_LENGTH = 16 * 1024 * 1024;

/**
 * Wraps a message in the wire format: [4B big-endian length][1B type][payload].
 * Length covers the type byte plus the payload. Mirror of protocol.py frame();
 * the single place outbound framing is built on the frontend.
 */
inline QByteArray frame(quint8 msgType, const QByteArray &payload = QByteArray()) {
    const quint32 bodyLength = static_cast<quint32>(1 + payload.size());

    QByteArray out;
    out.resize(4);
    qToBigEndian<quint32>(bodyLength, out.data());
    out.append(static_cast<char>(msgType));
    out.append(payload);
    return out;
}

}  // namespace protocol

#endif  // FRONTEND_V2_PROTOCOL_HH
