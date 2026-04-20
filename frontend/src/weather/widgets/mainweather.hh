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

    void updateTemperature(qint8 value, int id);

    void updateWindSpeed(quint8 value, int id);

    void updatePrecipitation(quint8 value, int id);

    void updateTotalCloudCover(quint8 value, int id);

public slots:
    void updateForecastData(const QVector<quint8> &times, const QVector<qint8> &temperatures,
                            const QVector<quint8> &windspeeds, const QVector<quint8> &precipitations,
                            const QVector<quint8> &cloudcovers);

private:
    QGridLayout *layout;

    CurrentWeatherCard *current_weather;

    QVector<WeatherForecastCard *> cards;

    QGraphicsDropShadowEffect *shadow;
};

#endif //GUI_MAINWEATHER_HH
