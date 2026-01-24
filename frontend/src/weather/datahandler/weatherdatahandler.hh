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
    void onMainWeatherUpdate(const QVector<quint8> &times, const QVector<double> &temperatures,
                             const QVector<double> &windspeeds, const QVector<double> &precipitations,
                             const QVector<double> &cloudcovers);
};

#endif //GUI_WEATHERDATAHANDLER_HH
