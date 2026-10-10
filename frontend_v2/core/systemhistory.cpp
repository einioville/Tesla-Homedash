#include "systemhistory.hh"

#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QtEndian>

#include <limits>

#include "logger.hh"
#include "protocol.hh"
#include "serverclient.hh"

namespace {
const Logger logger = Logger::get("system.history");

// The backend samples every 2 s; polling at the same pace keeps the graph at
// most one sample behind.
constexpr int kPollMs = 2000;

// Samples kept past the left edge of the window, in intervals. The graph slides
// each new sample in from the right, and during the slide the left edge shows
// what lies just beyond the window — without these it would show a gap there.
constexpr int kMarginIntervals = 3;

constexpr double kNaN = std::numeric_limits<double>::quiet_NaN();

// A JSON number, or NaN for null / missing — the graph's gap.
double numberOr(const QJsonValue &value) {
    return value.isDouble() ? value.toDouble() : kNaN;
}
}  // namespace

SystemHistory::SystemHistory(QObject *parent) : QObject(parent) {
    m_timer.setInterval(kPollMs);
    connect(&m_timer, &QTimer::timeout, this, &SystemHistory::refresh);
}

void SystemHistory::attachServer(ServerClient *client) {
    m_server = client;
    connect(client, &ServerClient::packetReceived, this, &SystemHistory::onPacket);
    // A reconnect while the graphs are open resumes at once rather than waiting
    // out a poll interval.
    connect(client, &ServerClient::connectedChanged, this, [this, client]() {
        if (client->connected() && active()) {
            refresh();
        }
    });
}

void SystemHistory::retain() {
    if (++m_consumers == 1) {
        emit activeChanged();
        refresh();
        m_timer.start();
    }
}

void SystemHistory::release() {
    if (m_consumers == 0) {
        logger.warning(QStringLiteral("release() without a matching retain()"));
        return;
    }
    if (--m_consumers == 0) {
        m_timer.stop();
        emit activeChanged();
    }
}

void SystemHistory::refresh() {
    if (m_server == nullptr || !m_server->connected()) {
        return;
    }
    QByteArray payload(8, '\0');
    const qint64 since = m_samples.isEmpty() ? 0 : m_samples.last().t;
    qToBigEndian<qint64>(since, payload.data());
    m_server->sendPacket(protocol::frame(protocol::SYSTEM_GET_HISTORY, payload));
}

void SystemHistory::onPacket(quint8 type, const QByteArray &payload) {
    if (type != protocol::SYSTEM_HISTORY) {
        return;
    }
    if (payload.size() < 5) {
        logger.warning(QStringLiteral("SYSTEM_HISTORY: payload too short"));
        return;
    }
    const quint8 status = static_cast<quint8>(payload.at(0));
    const quint32 length = qFromBigEndian<quint32>(payload.constData() + 1);
    if (static_cast<qint64>(payload.size()) < 5 + static_cast<qint64>(length)) {
        logger.warning(QStringLiteral("SYSTEM_HISTORY: truncated body"));
        return;
    }
    if (status != protocol::CONFIG_STATUS_OK) {
        logger.warning(QStringLiteral("Backend could not build the system history"));
        return;
    }

    QJsonParseError error{};
    const QJsonDocument doc =
        QJsonDocument::fromJson(payload.mid(5, static_cast<int>(length)), &error);
    if (error.error != QJsonParseError::NoError || !doc.isObject()) {
        logger.warning(QStringLiteral("Malformed SYSTEM_HISTORY: %1").arg(error.errorString()));
        return;
    }
    const QJsonObject root = doc.object();

    // Everything but the samples themselves.
    QVariantMap info = root.toVariantMap();
    info.remove(QStringLiteral("samples"));
    info.remove(QStringLiteral("reset"));
    m_info = info;

    // `reset`: this side asked for everything, or holds samples the backend's
    // clock has not reached — either way, what is held no longer lines up.
    if (root.value(QStringLiteral("reset")).toBool()) {
        m_samples.clear();
    }
    const QJsonArray rows = root.value(QStringLiteral("samples")).toArray();
    for (const QJsonValue &rowValue : rows) {
        const QJsonObject row = rowValue.toObject();
        Sample sample;
        sample.t = static_cast<qint64>(row.value(QStringLiteral("t")).toDouble());
        // The backend sends only what is newer than `since`, but a reply that
        // crossed a reconnect could still overlap; never add a sample twice.
        if (!m_samples.isEmpty() && sample.t <= m_samples.last().t) {
            continue;
        }
        const QJsonArray cores = row.value(QStringLiteral("cpu")).toArray();
        sample.cpu.reserve(cores.size());
        for (const QJsonValue &core : cores) {
            sample.cpu.append(numberOr(core));
        }
        sample.memUsed = numberOr(row.value(QStringLiteral("mem_used_b")));
        sample.diskRead = numberOr(row.value(QStringLiteral("disk_read_bps")));
        sample.diskWrite = numberOr(row.value(QStringLiteral("disk_write_bps")));
        sample.netRx = numberOr(row.value(QStringLiteral("net_rx_bps")));
        sample.netTx = numberOr(row.value(QStringLiteral("net_tx_bps")));
        sample.cpuTemp = numberOr(row.value(QStringLiteral("cpu_temp_c")));
        m_samples.append(sample);
    }

    // Trim to the window (plus the slide margin), measured from the newest
    // sample rather than from this side's clock.
    if (!m_samples.isEmpty()) {
        const double intervalS = qMax(0.5, m_info.value(QStringLiteral("interval_s")).toDouble());
        const double windowS = qMax(60.0, m_info.value(QStringLiteral("window_s")).toDouble());
        const qint64 cutoff = m_samples.last().t -
                              static_cast<qint64>((windowS + kMarginIntervals * intervalS) * 1000.0);
        qsizetype drop = 0;
        while (drop < m_samples.size() && m_samples.at(drop).t < cutoff) {
            ++drop;
        }
        m_samples.remove(0, drop);
    }

    rebuildSeries();
    m_loaded = true;
    emit historyChanged();
}

void SystemHistory::rebuildSeries() {
    qsizetype cores = 0;
    for (const Sample &sample : std::as_const(m_samples)) {
        cores = qMax(cores, sample.cpu.size());
    }

    QVariantList t, memUsed, diskRead, diskWrite, netRx, netTx, cpuTemp;
    QList<QVariantList> cpu(cores);
    for (const Sample &sample : std::as_const(m_samples)) {
        t.append(static_cast<double>(sample.t));
        for (qsizetype core = 0; core < cores; ++core) {
            cpu[core].append(core < sample.cpu.size() ? sample.cpu.at(core) : kNaN);
        }
        memUsed.append(sample.memUsed);
        diskRead.append(sample.diskRead);
        diskWrite.append(sample.diskWrite);
        netRx.append(sample.netRx);
        netTx.append(sample.netTx);
        cpuTemp.append(sample.cpuTemp);
    }

    QVariantList cpuColumns;
    cpuColumns.reserve(cores);
    for (const QVariantList &column : std::as_const(cpu)) {
        cpuColumns.append(QVariant(column));
    }

    m_series = {
        {QStringLiteral("t"), t},
        {QStringLiteral("cpu"), cpuColumns},
        {QStringLiteral("memUsed"), memUsed},
        {QStringLiteral("diskRead"), diskRead},
        {QStringLiteral("diskWrite"), diskWrite},
        {QStringLiteral("netRx"), netRx},
        {QStringLiteral("netTx"), netTx},
        {QStringLiteral("cpuTemp"), cpuTemp},
    };
}
