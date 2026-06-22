#include "weatherdata.hh"

#include "../logger.hh"
#include "../protocol.hh"
#include "../serverclient.hh"

#include <QDataStream>
#include <QIODevice>
#include <QVector>
#include <algorithm>

namespace {
const Logger logger = Logger::get("weather");
}

WeatherData::WeatherData(ServerClient *server, QObject *parent)
    : QObject(parent), m_forecast(new WeatherForecastModel(this)) {
    connect(server, &ServerClient::packetReceived, this, &WeatherData::onPacket);
}

void WeatherData::onPacket(quint8 type, const QByteArray &payload) {
    if (type != protocol::WEATHER_FORECAST) {
        return;  // not ours
    }

    QDataStream stream(payload);
    stream.setByteOrder(QDataStream::BigEndian);
    QIODevice *device = stream.device();

    QVector<quint8> times;
    QVector<qint8> temperatures;
    QVector<quint8> windSpeeds;
    QVector<quint8> precipitations;
    QVector<quint8> cloudCovers;

    // The frame is a sequence of (sub_id, value) byte pairs. Read BOTH bytes
    // every iteration — including for an unknown sub-id — so one stray record
    // can't desync the rest of the frame.
    while (device->bytesAvailable() >= 2) {
        quint8 subId;
        stream >> subId;
        switch (subId) {
            case protocol::FORECAST_TIME: {
                quint8 value;
                stream >> value;
                times.push_back(value);
                break;
            }
            case protocol::FORECAST_TEMPERATURE: {
                qint8 value;  // signed: sub-zero temperatures are normal
                stream >> value;
                temperatures.push_back(value);
                break;
            }
            case protocol::FORECAST_WIND_SPEED: {
                quint8 value;
                stream >> value;
                windSpeeds.push_back(value);
                break;
            }
            case protocol::FORECAST_PRECIPITATION: {
                quint8 value;
                stream >> value;
                precipitations.push_back(value);
                break;
            }
            case protocol::FORECAST_TOTAL_CLOUD_COVER: {
                quint8 value;
                stream >> value;
                cloudCovers.push_back(value);
                break;
            }
            default: {
                quint8 ignored;
                stream >> ignored;  // consume the value byte to stay aligned
                break;
            }
        }
    }

    // The parallel vectors are positionally aligned (index i = hour i); clamp to
    // the shortest so a malformed frame can't pair a temperature with the wrong
    // hour.
    const int n = static_cast<int>(std::min({times.size(), temperatures.size(), windSpeeds.size(),
                                             precipitations.size(), cloudCovers.size()}));
    if (n < 1) {
        logger.warning(QStringLiteral("Forecast frame had no complete rows"));
        return;
    }

    const auto makeRow = [&](int i) {
        ForecastRow row;
        row.hour = times.at(i);
        row.temperature = temperatures.at(i);
        row.windSpeed = windSpeeds.at(i);
        row.precipitation = precipitations.at(i);
        row.cloudCover = cloudCovers.at(i);
        return row;
    };

    // Row 0 is the current-hour observation (banner); 1..n-1 are the forecast.
    const ForecastRow currentRow = makeRow(0);
    QVariantMap current;
    current.insert(QStringLiteral("hour"), currentRow.hour);
    current.insert(QStringLiteral("temperature"), currentRow.temperature);
    current.insert(QStringLiteral("windSpeed"), currentRow.windSpeed);
    current.insert(QStringLiteral("precipitation"), currentRow.precipitation);
    current.insert(QStringLiteral("cloudCover"), currentRow.cloudCover);

    QVector<ForecastRow> rows;
    rows.reserve(n - 1);
    for (int i = 1; i < n; ++i) {
        rows.push_back(makeRow(i));
    }

    // One atomic update per frame: swap the whole model + current object.
    m_forecast->setRows(rows);
    m_current = current;
    emit currentChanged();

    logger.debug(QStringLiteral("Forecast updated | hours=%1").arg(n));
}
