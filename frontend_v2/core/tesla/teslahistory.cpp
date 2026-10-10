#include "teslahistory.hh"

#include "../logger.hh"
#include "../protocol.hh"
#include "../seriesbounds.hh"
#include "../serverclient.hh"
#include "tesladata.hh"

#include <QDataStream>
#include <QDateTime>
#include <QIODevice>
#include <QPointF>
#include <QTimer>
#include <QVariantMap>

namespace {
const Logger logger = Logger::get("tesla.history");
}

TeslaHistory::TeslaHistory(ServerClient *server, TeslaData *tesla, QObject *parent)
    : QObject(parent), m_server(server), m_tesla(tesla) {
    connect(server, &ServerClient::packetReceived, this, &TeslaHistory::onPacket);
    m_liveTimer = new QTimer(this);
    connect(m_liveTimer, &QTimer::timeout, this, &TeslaHistory::onLiveTick);
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

int TeslaHistory::liveTickIntervalForRange(int rangeCode) {
    // Throttle the live tick by window size. The tick both samples the live value
    // and advances the right edge, so its period is also the redraw rate AND the
    // value-sampling resolution. On the long windows a 1 s advance is sub-pixel, so
    // we slow the tick down to keep the per-tick full series rebuild from stuttering
    // on the Pi — subsampling value changes to a resolution that is imperceptible at
    // that zoom (a 30 s step on a 30-day axis).
    switch (rangeCode) {
        case protocol::HISTORY_RANGE_1H: return 1000;   // 1 s — responsive on a 1 h axis
        case protocol::HISTORY_RANGE_1D: return 5000;   // 5 s
        case protocol::HISTORY_RANGE_1W: return 10000;  // 10 s
        case protocol::HISTORY_RANGE_1M: return 30000;  // 30 s
        default: return 1000;  // custom/unknown -> 1 s
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
    // Throttle the per-second rebuild on long windows (see liveTickIntervalForRange).
    // The timer is (re)started in parseHistory once the seed lands; setting the
    // interval here applies on that start.
    m_liveTimer->setInterval(liveTickIntervalForRange(rangeCode));
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
    const QVariant v = m_tesla->property(TeslaData::qmlName(m_liveId).toUtf8().constData());
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
    // historyChanged first, then liveTick: the graph's advanceLive() (driven by
    // liveTick) reads the binding-backed points/bounds, which update on historyChanged,
    // so the data must be published before the tick fires or the live line lags a tick.
    emit historyChanged();
    emit liveTick();
}

void TeslaHistory::recomputeBounds(qint64 nowMs) {
    const SeriesBounds bounds = rollLiveWindow(m_points, m_liveWindowMs, nowMs);
    m_minX = bounds.minX;
    m_maxX = bounds.maxX;
    m_minY = bounds.minY;
    m_maxY = bounds.maxY;
}

void TeslaHistory::requestProperties() {
    m_server->sendPacket(protocol::frame(protocol::TESLA_GET_GRAPH_PROPERTIES));
    logger.info(QStringLiteral("Graphable-property list requested"));
}

void TeslaHistory::requestHistory(const QString &id, int rangeCode,
                                  double startMs, double endMs) {
    if (id.isEmpty()) {
        return;
    }
    m_currentId = id;
    setLoading(true);

    m_server->sendPacket(protocol::frame(
        protocol::TESLA_GET_HISTORY,
        protocol::historyRequestBody(static_cast<quint8>(rangeCode), id,
                                     static_cast<qint64>(startMs), static_cast<qint64>(endMs))));
    logger.info(QStringLiteral("History requested | id=%1 range=%2").arg(id).arg(rangeCode));
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

void TeslaHistory::parseProperties(const QByteArray &payload) {
    QDataStream stream(payload);
    stream.setByteOrder(QDataStream::BigEndian);
    QIODevice *device = stream.device();

    if (device->bytesAvailable() < 2) {
        logger.warning(QStringLiteral("Graph-properties frame too short"));
        return;
    }
    quint16 count;
    stream >> count;

    QVariantList properties;
    for (quint16 i = 0; i < count; ++i) {
        QString id;
        QString unit;
        QString category;
        QString lineMode;
        if (!protocol::readString(stream, id) || !protocol::readString(stream, unit) ||
            !protocol::readString(stream, category) || !protocol::readString(stream, lineMode)) {
            logger.warning(QStringLiteral("Truncated graph-properties frame at entry %1").arg(i));
            return;
        }
        if (device->bytesAvailable() < 1) {
            logger.warning(QStringLiteral("Truncated graph-properties frame at entry %1").arg(i));
            return;
        }
        quint8 zeroBased;
        stream >> zeroBased;
        QVariantMap entry;
        entry.insert(QStringLiteral("id"), id);
        entry.insert(QStringLiteral("unit"), unit);
        entry.insert(QStringLiteral("category"), category);
        // Graph render hint: "step" (hold-forward, default) or "linear" (point-to-point).
        entry.insert(QStringLiteral("line_mode"), lineMode);
        // Pin the graph's y-axis bottom to 0 (a quantity that cannot go negative).
        entry.insert(QStringLiteral("zero_based"), zeroBased != 0);
        properties.append(entry);
    }

    m_properties = properties;
    emit propertiesChanged();
    logger.debug(QStringLiteral("Graphable properties: %1").arg(properties.size()));
}

void TeslaHistory::parseHistory(const QByteArray &payload) {
    QDataStream stream(payload);
    stream.setByteOrder(QDataStream::BigEndian);

    QString id;
    if (!protocol::readString(stream, id)) {
        logger.warning(QStringLiteral("Truncated history frame (id)"));
        return;
    }
    // Discard replies for a property the user has already switched away from.
    if (id != m_currentId) {
        logger.debug(QStringLiteral("Dropping stale history reply for %1").arg(id));
        return;
    }
    const auto series = protocol::readSeries(stream);
    if (!series) {
        logger.warning(QStringLiteral("Truncated history frame (header)"));
        return;
    }
    if (series->truncated) {
        logger.warning(QStringLiteral("Truncated history points at %1").arg(series->points.size()));
    }
    const quint8 status = series->status;

    QVariantList points;
    points.reserve(series->points.size());
    for (const QPointF &point : series->points) {
        points.append(QVariant::fromValue(point));
    }
    m_points = points;
    const SeriesBounds bounds = seriesBounds(series->points);
    m_minX = bounds.minX;
    m_maxX = bounds.maxX;
    m_minY = bounds.minY;
    m_maxY = bounds.maxY;
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
    logger.debug(QStringLiteral("History applied | id=%1 points=%2 status=%3")
                     .arg(id)
                     .arg(points.size())
                     .arg(status));
}

void TeslaHistory::setLoading(bool loading) {
    if (m_loading == loading) {
        return;
    }
    m_loading = loading;
    emit loadingChanged();
}
