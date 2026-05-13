//
// Created by ville on 13.12.2025.
//

#ifndef GUI_WEATHERDATAHANDLER_HH
#define GUI_WEATHERDATAHANDLER_HH
#include <QObject>
#include <QByteArray>
#include "../widgets/mainweather.hh"

/**
 * WeatherDataHandler — parses a single WEATHER_FORECAST packet (msg type
 * 0x30) into parallel arrays for time / temperature / wind speed /
 * precipitation / cloud cover, then emits onMainWeatherUpdate.
 *
 * The packet is a sequence of (sub_id, value) records; see CLAUDE.md
 * "Weather forecast sub-IDs" for the wire format.
 */
class WeatherDataHandler : public QObject {
    Q_OBJECT

public:
    explicit WeatherDataHandler(QObject *parent);

    void connectMainWeather(MainWeather *main_weather);

public slots:
    void onMainForecastUpdate(const QByteArray &packet);

signals:
    void onMainWeatherUpdate(const QVector<quint8> &times, const QVector<qint8> &temperatures,
                             const QVector<quint8> &windspeeds, const QVector<quint8> &precipitations,
                             const QVector<quint8> &cloudcovers);
};

#endif //GUI_WEATHERDATAHANDLER_HH
