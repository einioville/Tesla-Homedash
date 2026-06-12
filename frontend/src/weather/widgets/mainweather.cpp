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

    QFile style(":/resources/styles/mainweather.qss");
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

void MainWeather::updateForecastData(const QVector<quint8> &times, const QVector<qint8> &temperatures,
                                     const QVector<quint8> &windspeeds, const QVector<quint8> &precipitations,
                                     const QVector<quint8> &cloudcovers) {
    if (times.size() < 6 || temperatures.size() < 6 || windspeeds.size() < 6 || precipitations.size() < 6 || cloudcovers
        .size() < 6) {
        return;
    }

    // Row 0 is the live current-hour observation; tag it with the banner's
    // sentinel id so only CurrentWeatherCard consumes it (forecast cards skip
    // any id that isn't their own).
    emit updateTime(times[0], CurrentWeatherCard::kCurrentWeatherId);
    emit updateTemperature(temperatures[0], CurrentWeatherCard::kCurrentWeatherId);
    emit updateWindSpeed(windspeeds[0], CurrentWeatherCard::kCurrentWeatherId);
    emit updatePrecipitation(precipitations[0], CurrentWeatherCard::kCurrentWeatherId);
    emit updateTotalCloudCover(cloudcovers[0], CurrentWeatherCard::kCurrentWeatherId);

    // entries 1..5 are the 5 forecast hours; entry 0 is the current-hour observation
    // already emitted above for CurrentWeatherCard
    for (int i = 1; i <= 5; i++) {
        emit updateTime(times[i], i - 1);
        emit updateTemperature(temperatures[i], i - 1);
        emit updateWindSpeed(windspeeds[i], i - 1);
        emit updatePrecipitation(precipitations[i], i - 1);
        emit updateTotalCloudCover(cloudcovers[i], i - 1);
    }
}
