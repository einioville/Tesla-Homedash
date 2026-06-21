#include "teslahistory.hh"

#include "../protocol.hh"
#include "../serverclient.hh"
#include "tesladata.hh"

#include <QDataStream>
#include <QDateTime>
#include <QIODevice>
#include <QLoggingCategory>
#include <QPointF>
#include <QTimer>
#include <QVariantMap>
#include <limits>

namespace {
Q_LOGGING_CATEGORY(lcHistory, "frontend_v2.history")
}

TeslaHistory::TeslaHistory(ServerClient *server, TeslaData *tesla, QObject *parent)
    : QObject(parent), m_server(server), m_tesla(tesla) {
    connect(server, &ServerClient::packetReceived, this, &TeslaHistory::onPacket);
    m_liveTimer = new QTimer(this);
    m_liveTimer->setInterval(1000);  // 1 s, per the live-graph spec
    connect(m_liveTimer, &QTimer::timeout, this, &TeslaHistory::onLiveTick);
}

QString TeslaHistory::qmlNameForId(const QString &id) {
    if (id.isEmpty()) {
        return id;
    }
    // Mirror generate_tesladata.py::qml_name — lower-case the first char only
    // (e.g. ACChargingPower -> aCChargingPower), so we can read the live value off
    // the Tesla singleton by Q_PROPERTY name.
    return id.left(1).toLower() + id.mid(1);
}

qint64 TeslaHistory::windowMsForRange(int rangeCode) {
    switch (rangeCode) {
        case protocol::HISTORY_RANGE_1H: return 60LL * 60 * 1000;
        case protocol::HISTORY_RANGE_1D: return 24LL * 60 * 60 * 1000;
        case protocol::HISTORY_RANGE_1W: return 7LL * 24 * 60 * 60 * 1000;
        case protocol::HISTORY_RANGE_1M: return 30LL * 24 * 60 * 60 * 1000;
        default: return 60LL * 60 * 1000;  // custom/unknown -> fall back to 1 h
    }
}

void TeslaHistory::startLive(const QString &id, int rangeCode) {
    if (id.isEmpty()) {
        return;
    }
    // Pause until the new seed lands so a tick can't append a value into a buffer
    // that's about to be replaced (e.g. when switching property while live).
    m_liveTimer->stop();
    m_live = true;
    m_livePending = true;
    m_liveId = id;
    m_liveRangeCode = rangeCode;
    m_liveWindowMs = windowMsForRange(rangeCode);
    // Seed from history; the per-second timer starts once the matching reply lands
    // (see parseHistory), so the rolling window begins from real stored data.
    requestHistory(id, rangeCode, 0.0, 0.0);
}

void TeslaHistory::stopLive() {
    m_live = false;
    m_livePending = false;
    m_liveTimer->stop();
}

void TeslaHistory::pauseLive() {
    // Freeze while the view is hidden. m_live stays set; the view re-seeds via
    // startLive() on re-show. Clearing m_livePending stops an in-flight seed reply
    // from restarting the timer behind a hidden view.
    m_livePending = false;
    m_liveTimer->stop();
}

void TeslaHistory::onLiveTick() {
    if (!m_live || !m_tesla) {
        return;
    }
    const qint64 now = QDateTime::currentMSecsSinceEpoch();
    const QVariant v = m_tesla->property(qmlNameForId(m_liveId).toUtf8().constData());
    bool ok = false;
    const double value = v.toDouble(&ok);
    if (ok) {
        // Store a real point only when the value changed since the last sample;
        // between changes the step line holds the previous value flat to the
        // advancing right edge (recomputeBounds moves m_maxX to now), so we don't
        // accumulate a synthetic point every second.
        bool changed = m_points.isEmpty();
        if (!m_points.isEmpty()) {
            changed = m_points.last().toPointF().y() != value;
        }
        if (changed) {
            m_points.append(
                QVariant::fromValue(QPointF(static_cast<double>(now), value)));
        }
    }
    recomputeBounds(now);
    emit liveTick();
    emit historyChanged();
}

void TeslaHistory::recomputeBounds(qint64 nowMs) {
    const double left = static_cast<double>(nowMs - m_liveWindowMs);
    // Roll the window: drop points older than the left edge, but keep the last one
    // before it as the boundary so the value held at the edge is still known (the
    // step line needs it to draw the left portion of the window correctly).
    int firstInside = 0;
    while (firstInside < m_points.size()
           && m_points[firstInside].toPointF().x() < left) {
        ++firstInside;
    }
    const int dropCount = firstInside > 0 ? firstInside - 1 : 0;
    if (dropCount > 0) {
        m_points.remove(0, dropCount);
    }
    m_minX = left;
    m_maxX = static_cast<double>(nowMs);
    // y-bounds over the retained points (used only as a fallback when the visible
    // window has no points; a degenerate single-value range is fine — HistoryGraph
    // pads y via yPad). Neutral [0,1] when empty.
    double minY = std::numeric_limits<double>::max();
    double maxY = std::numeric_limits<double>::lowest();
    for (const QVariant &p : m_points) {
        const double y = p.toPointF().y();
        minY = qMin(minY, y);
        maxY = qMax(maxY, y);
    }
    if (m_points.isEmpty()) {
        m_minY = 0.0;
        m_maxY = 1.0;
    } else {
        m_minY = minY;
        m_maxY = maxY;
    }
}

void TeslaHistory::requestProperties() {
    m_server->sendPacket(protocol::frame(protocol::TESLA_GET_GRAPH_PROPERTIES));
    qCInfo(lcHistory) << "Graphable-property list requested";
}

void TeslaHistory::requestHistory(const QString &id, int rangeCode,
                                  double startMs, double endMs) {
    if (id.isEmpty()) {
        return;
    }
    m_currentId = id;
    setLoading(true);

    QByteArray payload;
    QDataStream stream(&payload, QIODevice::WriteOnly);
    stream.setByteOrder(QDataStream::BigEndian);
    const QByteArray idBytes = id.toUtf8();
    stream << static_cast<quint8>(rangeCode);
    stream << static_cast<quint16>(idBytes.size());
    stream.writeRawData(idBytes.constData(), idBytes.size());
    stream << static_cast<qint64>(startMs);
    stream << static_cast<qint64>(endMs);

    m_server->sendPacket(protocol::frame(protocol::TESLA_GET_HISTORY, payload));
    qCInfo(lcHistory) << "History requested | id=" << id << "range=" << rangeCode;
}

void TeslaHistory::onPacket(quint8 type, const QByteArray &payload) {
    switch (type) {
        case protocol::TESLA_GRAPH_PROPERTIES:
            parseProperties(payload);
            break;
        case protocol::TESLA_HISTORY:
            parseHistory(payload);
            break;
        default:
            break;  // not ours
    }
}

bool TeslaHistory::readString(QDataStream &stream, QIODevice *device, QString &out) {
    if (device->bytesAvailable() < 2) {
        return false;
    }
    quint16 length;
    stream >> length;
    if (device->bytesAvailable() < length) {
        return false;
    }
    QByteArray raw(length, Qt::Uninitialized);
    stream.readRawData(raw.data(), length);
    out = QString::fromUtf8(raw);
    return true;
}

void TeslaHistory::parseProperties(const QByteArray &payload) {
    QDataStream stream(payload);
    stream.setByteOrder(QDataStream::BigEndian);
    QIODevice *device = stream.device();

    if (device->bytesAvailable() < 2) {
        qCWarning(lcHistory) << "Graph-properties frame too short";
        return;
    }
    quint16 count;
    stream >> count;

    QVariantList properties;
    for (quint16 i = 0; i < count; ++i) {
        QString id;
        QString unit;
        QString category;
        if (!readString(stream, device, id) || !readString(stream, device, unit) ||
            !readString(stream, device, category)) {
            qCWarning(lcHistory) << "Truncated graph-properties frame at entry" << i;
            return;
        }
        QVariantMap entry;
        entry.insert(QStringLiteral("id"), id);
        entry.insert(QStringLiteral("unit"), unit);
        entry.insert(QStringLiteral("category"), category);
        properties.append(entry);
    }

    m_properties = properties;
    emit propertiesChanged();
    qCDebug(lcHistory) << "Graphable properties:" << properties.size();
}

void TeslaHistory::parseHistory(const QByteArray &payload) {
    QDataStream stream(payload);
    stream.setByteOrder(QDataStream::BigEndian);
    QIODevice *device = stream.device();

    QString id;
    if (!readString(stream, device, id)) {
        qCWarning(lcHistory) << "Truncated history frame (id)";
        return;
    }
    // Discard replies for a property the user has already switched away from.
    if (id != m_currentId) {
        qCDebug(lcHistory) << "Dropping stale history reply for" << id;
        return;
    }
    if (device->bytesAvailable() < 5) {
        qCWarning(lcHistory) << "Truncated history frame (header)";
        return;
    }
    quint8 status;
    stream >> status;
    quint32 count;
    stream >> count;

    QVariantList points;
    double minX = std::numeric_limits<double>::max();
    double maxX = std::numeric_limits<double>::lowest();
    double minY = std::numeric_limits<double>::max();
    double maxY = std::numeric_limits<double>::lowest();

    if (status == 1) {
        points.reserve(static_cast<int>(count));
        for (quint32 i = 0; i < count; ++i) {
            if (device->bytesAvailable() < 16) {
                qCWarning(lcHistory) << "Truncated history points at" << i;
                break;
            }
            qint64 timestamp;
            stream >> timestamp;
            double value;
            stream >> value;
            const double x = static_cast<double>(timestamp);
            points.append(QVariant::fromValue(QPointF(x, value)));
            minX = qMin(minX, x);
            maxX = qMax(maxX, x);
            minY = qMin(minY, value);
            maxY = qMax(maxY, value);
        }
    }

    m_points = points;
    if (points.isEmpty()) {
        // Neutral, valid axis bounds so the empty graph still renders.
        m_minX = 0.0;
        m_maxX = 1.0;
        m_minY = 0.0;
        m_maxY = 1.0;
    } else {
        m_minX = minX;
        m_maxX = maxX;
        m_minY = minY;
        m_maxY = maxY;
        // A single point (or several sharing one timestamp) leaves m_minX == m_maxX
        // — a zero-width x-range. A QML ValueAxis with min == max divides by zero
        // mapping data to pixels and crashes QtGraphs, so pad to a non-zero span
        // centred on the point. (A degenerate y-range is harmless: HistoryGraph pads
        // it via yPad when auto-fitting, so only x needs guarding here.)
        if (m_maxX <= m_minX) {
            m_minX -= 60000.0;  // +/- 1 min in ms
            m_maxX += 60000.0;
        }
    }
    // Live seed: this reply seeds the rolling window. Override the bounds to the
    // live window [now-size, now] (so the axis shows the whole window, not just the
    // seeded data extent), then start the per-second timer. historyReady still
    // fires below, so HistoryGraph draws the seed and resets the view once.
    if (m_livePending && id == m_liveId) {
        recomputeBounds(QDateTime::currentMSecsSinceEpoch());
        m_livePending = false;
        m_liveTimer->start();
    }
    setLoading(false);
    emit historyChanged();
    emit historyReady();
    qCDebug(lcHistory) << "History applied | id=" << id << "points=" << points.size()
                       << "status=" << status;
}

void TeslaHistory::setLoading(bool loading) {
    if (m_loading == loading) {
        return;
    }
    m_loading = loading;
    emit loadingChanged();
}
