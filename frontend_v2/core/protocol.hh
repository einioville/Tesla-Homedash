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
