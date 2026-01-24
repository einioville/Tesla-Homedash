//
// Created by ville on 15.12.2025.
//

#include "mainweather.hh"
#include <QPainter>
#include <QPainterPath>
#include <QRadialGradient>
#include <QPointF>
#include <QColor>
#include <QFile>

MainWeather::MainWeather(QWidget *parent) {
    setObjectName("mainweather");
    layout = new QGridLayout(this);
    layout->setContentsMargins(10, 10, 10, 10);
    layout->setSpacing(10);
    setLayout(layout);

    current_weather = new CurrentWeatherCard(this);
    layout->addWidget(current_weather, 0, 0, 1, 5);
    connect(this, &MainWeather::updateTemperature, current_weather, &CurrentWeatherCard::updateTemperature);
    connect(this, &MainWeather::updateWindSpeed, current_weather, &CurrentWeatherCard::updateWindSpeed);
    connect(this, &MainWeather::updatePrecipitation, current_weather, &CurrentWeatherCard::updatePrecipitation);
    connect(this, &MainWeather::updateTotalCloudCover, current_weather, &CurrentWeatherCard::updateTotalCloudCover);

    for (int i = 0; i < 5; i++) {
        WeatherForecastCard *weather_card = new WeatherForecastCard(this, i);
        cards.push_back(weather_card);
        layout->addWidget(weather_card, 1, i, 2, 1);
        connect(this, &MainWeather::updateTime, weather_card, &WeatherForecastCard::updateTime);
        connect(this, &MainWeather::updateTemperature, weather_card, &WeatherForecastCard::updateTemperature);
        connect(this, &MainWeather::updateWindSpeed, weather_card, &WeatherForecastCard::updateWindSpeed);
        connect(this, &MainWeather::updatePrecipitation, weather_card, &WeatherForecastCard::updatePrecipitation);
        connect(this, &MainWeather::updateTotalCloudCover, weather_card, &WeatherForecastCard::updateTotalCloudCover);
    }

    QFile style(":resources/styles/mainweather.qss");
    if (style.open(QFile::ReadOnly | QFile::Text)) {
        QTextStream stream(&style);
        const QString base_style = stream.readAll();
        setStyleSheet(base_style);
    }

    shadow = new QGraphicsDropShadowEffect(this);
    shadow->setBlurRadius(50);
    shadow->setXOffset(10);
    shadow->setYOffset(10);
    shadow->setColor(QColor(0, 0, 0, 150));
    setGraphicsEffect(shadow);
}

void MainWeather::updateForecastData(const QVector<quint8> &times, const QVector<double> &temperatures,
                                     const QVector<double> &windspeeds, const QVector<double> &precipitations,
                                     const QVector<double> &cloudcovers) {
    if (times.size() < 6 || temperatures.size() < 6 || windspeeds.size() < 6 || precipitations.size() < 6 || cloudcovers
        .size() < 5) {
        return;
    }

    emit updateTime(times[0], 69);
    emit updateTemperature(temperatures[0], 69);
    emit updateWindSpeed(windspeeds[0], 69);
    emit updatePrecipitation(precipitations[0], 69);
    emit updateTotalCloudCover(cloudcovers[0], 69);

    for (int i = 0; i < 5; i++) {
        emit updateTime(times[i], i);
        emit updateTemperature(temperatures[i], i);
        emit updateWindSpeed(windspeeds[i], i);
        emit updatePrecipitation(precipitations[i], i);
        emit updateTotalCloudCover(cloudcovers[i], i);
    }
}
