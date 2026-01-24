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
    QVector<double> temperatures;
    QVector<double> windspeeds;
    QVector<double> precipitations;
    QVector<double> cloudcovers;

    while (true) {
        if (device->bytesAvailable() == 0) {
            break;
        }

        quint8 data_id;
        stream >> data_id;

        switch (data_id) {
            case 0x35:
                quint8 time;
                stream >> time;
                times.push_back(time);
                break;

            case 0x31:
                double temperature;
                stream >> temperature;
                temperatures.push_back(temperature);
                break;

            case 0x32:
                double windspeed;
                stream >> windspeed;
                windspeeds.push_back(windspeed);
                break;

            case 0x33:
                double precipitation;
                stream >> precipitation;
                precipitations.push_back(precipitation);
                break;

            case 0x34:
                double cloudcover;
                stream >> cloudcover;
                cloudcovers.push_back(cloudcover);
                break;

            default:
                break;
        }
    }

    emit onMainWeatherUpdate(times, temperatures, windspeeds, precipitations, cloudcovers);
}

