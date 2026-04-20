//
// Created by ville on 13.12.2025.
//

#ifndef GUI_WEATHERDATAHANDLER_HH
#define GUI_WEATHERDATAHANDLER_HH
#include <QObject>
#include <QByteArray>
#include <QObject>
#include "../widgets/mainweather.hh"

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
