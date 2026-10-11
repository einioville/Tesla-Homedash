#include "weatherdata.hh"

#include "../logger.hh"
#include "../protocol.hh"
#include "../serverclient.hh"

#include <QJsonObject>

namespace {
const Logger logger = Logger::get("weather");
}

WeatherData::WeatherData(ServerClient *server, QObject *parent) : QObject(parent) {
    connect(server, &ServerClient::packetReceived, this, &WeatherData::onPacket);
}

void WeatherData::onPacket(quint8 type, const QByteArray &payload) {
    if (type != protocol::WEATHER_VIEW) {
        return;
    }
    // A bad frame keeps the last good document, as the backend keeps its last good frame
    // through a failed fetch.
    const auto reply = protocol::readJsonReply(payload);
    if (!reply) {
        logger.warning(QStringLiteral("Malformed WEATHER_VIEW"));
        return;
    }
    m_view = reply->body.toVariantMap();
    emit viewChanged();
    logger.debug(QStringLiteral("Weather view updated | hours=%1")
                     .arg(m_view.value(QStringLiteral("hourly")).toList().size()));
}
