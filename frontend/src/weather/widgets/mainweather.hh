//
// Created by ville on 15.12.2025.
//

#ifndef GUI_MAINWEATHER_HH
#define GUI_MAINWEATHER_HH
#include <QFrame>
#include <QGridLayout>
#include "weatherforecastcard.hh"
#include <QVector>
#include <QLabel>
#include <QHBoxLayout>
#include "currentweathercard.hh"
#include <QGraphicsDropShadowEffect>

class MainWeather : public QFrame {
    Q_OBJECT

public:
    MainWeather(QWidget *parent);

signals:
    void updateTime(quint8 time, int id);

    void updateTemperature(double value, int id);

    void updateWindSpeed(double value, int id);

    void updatePrecipitation(double value, int id);

    void updateTotalCloudCover(double value, int id);

public slots:
    void updateForecastData(const QVector<quint8> &times, const QVector<double> &temperatures,
                            const QVector<double> &windspeeds, const QVector<double> &precipitations,
                            const QVector<double> &cloudcovers);

private:
    QGridLayout *layout;

    CurrentWeatherCard *current_weather;

    QVector<WeatherForecastCard *> cards;

    QGraphicsDropShadowEffect *shadow;
};

#endif //GUI_MAINWEATHER_HH
