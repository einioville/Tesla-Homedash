#include "logcontrol.hh"

#include <QJsonObject>

#include "logger.hh"
#include "protocol.hh"
#include "serverclient.hh"

namespace {
const Logger logger = Logger::get("logs");

// The backend rewrites a few megabytes at most; anything longer has gone wrong.
constexpr int kTimeoutMs = 15000;

// "12.3 MB", in the units the status view uses.
QString formatBytes(qint64 bytes) {
    static const char *units[] = {"B", "kB", "MB", "GB"};
    double value = static_cast<double>(bytes);
    int unit = 0;
    while (value >= 1024.0 && unit < 3) {
        value /= 1024.0;
        ++unit;
    }
    return QStringLiteral("%1 %2")
        .arg(unit == 0 ? QString::number(bytes) : QString::number(value, 'f', 1),
             QString::fromLatin1(units[unit]));
}
}  // namespace

LogControl::LogControl(QObject *parent) : QObject(parent) {
    m_timeout.setSingleShot(true);
    m_timeout.setInterval(kTimeoutMs);
    connect(&m_timeout, &QTimer::timeout, this, [this]() {
        finish(false, QStringLiteral("Näytön lokit tyhjennetty, palvelin ei vastannut"));
    });
}

void LogControl::attachServer(ServerClient *client) {
    m_server = client;
    connect(client, &ServerClient::packetReceived, this, &LogControl::onPacket);
}

void LogControl::clear(bool keepWarnings) {
    if (m_busy) {
        return;
    }
    m_localFreed = Logger::clearFiles(keepWarnings);
    logger.info(QStringLiteral("Log files cleared (%1), %2 bytes freed here")
                    .arg(keepWarnings ? QStringLiteral("warnings kept") : QStringLiteral("everything"))
                    .arg(m_localFreed));
    if (m_server == nullptr || !m_server->connected()) {
        emit finished(false, QStringLiteral("Näytön lokit tyhjennetty, palvelimeen ei ole yhteyttä"));
        return;
    }
    const QJsonObject request{
        {QStringLiteral("keep"), keepWarnings ? QStringLiteral("warnings") : QStringLiteral("none")},
    };
    m_server->sendPacket(protocol::frame(protocol::LOG_CLEAR, protocol::jsonRequestBody(request)));
    m_busy = true;
    emit busyChanged();
    m_timeout.start();
}

void LogControl::onPacket(quint8 type, const QByteArray &payload) {
    if (type != protocol::LOG_CLEAR_RESULT || !m_busy) {
        return;
    }
    const auto reply = protocol::readJsonReply(payload);
    if (!reply) {
        finish(false, QStringLiteral("Palvelimen vastaus oli vajaa"));
        return;
    }
    const QJsonObject &result = reply->body;
    if (!result.value(QStringLiteral("ok")).toBool()) {
        const QString reason = result.value(QStringLiteral("message")).toString();
        finish(false, reason.isEmpty() ? QStringLiteral("Palvelimen lokien tyhjennys epäonnistui")
                                       : reason);
        return;
    }
    const qint64 freed =
        m_localFreed + static_cast<qint64>(result.value(QStringLiteral("freedBytes")).toDouble());
    finish(true, QStringLiteral("Tyhjennetty · %1 vapautettu").arg(formatBytes(freed)));
}

void LogControl::finish(bool ok, const QString &message) {
    m_timeout.stop();
    if (m_busy) {
        m_busy = false;
        emit busyChanged();
    }
    emit finished(ok, message);
}
