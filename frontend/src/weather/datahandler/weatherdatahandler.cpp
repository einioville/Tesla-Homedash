//
// Created by ville on 13.12.2025.
//

#include "weatherdatahandler.hh"
#include <QDataStream>
#include <QVector>
#include <QIODevice>

WeatherDataHandler::WeatherDataHandler(QObject *parent) : QObject{parent} {
    return;
}

void WeatherDataHandler::connectMainWeather(MainWeather *main_weather) {
    connect(this, &WeatherDataHandler::onMainWeatherUpdate, main_weather, &MainWeather::updateForecastData);
}

void WeatherDataHandler::onMainForecastUpdate(const QByteArray &packet) {
    QDataStream stream(packet);
    stream.setByteOrder(QDataStream::BigEndian);
    QIODevice *device = stream.device();

    QVector<quint8> times;
    QVector<qint8> temperatures;
    QVector<quint8> windspeeds;
    QVector<quint8> precipitations;
    QVector<quint8> cloudcovers;

    while (true) {
        if (device->bytesAvailable() == 0) {
            break;
        }

        quint8 data_id;
        stream >> data_id;

        // Each sub-id payload is exactly one byte; if the frame is truncated
        // mid-record, stop rather than reading past the buffer.
        if (device->bytesAvailable() < 1) {
            qWarning() << "WeatherDataHandler: truncated payload after sub-id" << data_id;
            break;
        }

        switch (data_id) {
            case 0x35: {
                quint8 time;
                stream >> time;
                times.push_back(time);
                break;
            }

            case 0x31: {
                qint8 temperature;
                stream >> temperature;
                temperatures.push_back(temperature);
                break;
            }

            case 0x32: {
                quint8 windspeed;
                stream >> windspeed;
                windspeeds.push_back(windspeed);
                break;
            }

            case 0x33: {
                quint8 precipitation;
                stream >> precipitation;
                precipitations.push_back(precipitation);
                break;
            }

            case 0x34: {
                quint8 cloudcover;
                stream >> cloudcover;
                cloudcovers.push_back(cloudcover);
                break;
            }

            default:
                break;
        }
    }

    emit onMainWeatherUpdate(times, temperatures, windspeeds, precipitations, cloudcovers);
}
