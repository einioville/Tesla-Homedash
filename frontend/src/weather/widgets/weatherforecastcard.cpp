//
// Created by ville on 13.12.2025.
//

#include "weatherforecastcard.hh"
#include <QString>
#include <QTextStream>
#include <QFile>
#include <QFontMetrics>
#include <QPainter>
#include <QPixmap>
#include <QSvgRenderer>

WeatherForecastCard::WeatherForecastCard(QWidget *parent, int id) : QFrame(parent) {
    setObjectName("weathercard");
    this->id = id;

    layout = new QVBoxLayout(this);
    layout->setContentsMargins(10, 10, 10, 10);
    layout->setSpacing(0);
    setLayout(layout);

    value_font = QFont("Gotham Rounded Medium", 14);
    unit_font = QFont("Gotham Rounded Medium", 10);

    const int icon_h = QFontMetrics(value_font).ascent();

    time = new QLabel(this);
    time->setFont(value_font);
    time->setAlignment(Qt::AlignCenter);
    time->setText("-");
    layout->addWidget(time);

    temperature_layout = new QHBoxLayout();
    temperature_layout->setSpacing(4);
    temperature_icon = new QLabel(this);
    temperature_icon->setPixmap(renderWeatherIcon(":/resources/icons/weather/thermometer.svg", icon_h));
    temperature_icon->setAlignment(Qt::AlignVCenter);
    temperature_layout->addWidget(temperature_icon);
    temperature_value = new QLabel(this);
    temperature_value->setFont(value_font);
    temperature_value->setAlignment(Qt::AlignCenter);
    temperature_value->setText("-");
    temperature_layout->addWidget(temperature_value);
    temperature_unit = new QLabel(this);
    temperature_unit->setFont(unit_font);
    temperature_unit->setAlignment(Qt::AlignCenter);
    temperature_unit->setText("°C");
    temperature_layout->addWidget(temperature_unit);
    layout->addLayout(temperature_layout);

    main_splitter = new QFrame(this);
    main_splitter->setFrameStyle(QFrame::NoFrame);
    main_splitter->setFixedHeight(2);
    main_splitter->setStyleSheet("background-color: white; color: white; border: none; border-radius: 2px");
    layout->addWidget(main_splitter);

    windspeed_layout = new QHBoxLayout();
    windspeed_layout->setSpacing(4);
    windspeed_icon = new QLabel(this);
    windspeed_icon->setPixmap(renderWeatherIcon(":/resources/icons/weather/wind.svg", icon_h));
    windspeed_icon->setAlignment(Qt::AlignVCenter);
    windspeed_layout->addWidget(windspeed_icon);
    windspeed_value = new QLabel(this);
    windspeed_value->setFont(value_font);
    windspeed_value->setAlignment(Qt::AlignCenter);
    windspeed_value->setText("-");
    windspeed_layout->addWidget(windspeed_value);
    windspeed_unit = new QLabel(this);
    windspeed_unit->setFont(unit_font);
    windspeed_unit->setAlignment(Qt::AlignCenter);
    windspeed_unit->setText("m/s");
    windspeed_layout->addWidget(windspeed_unit);
    layout->addLayout(windspeed_layout);

    sub_splitter_1 = new QFrame(this);
    sub_splitter_1->setFrameStyle(QFrame::NoFrame);
    sub_splitter_1->setFixedHeight(2);
    sub_splitter_1->setStyleSheet("background-color: white; color: white; border: none; border-radius: 2px");
    layout->addWidget(sub_splitter_1);

    precipitation_layout = new QHBoxLayout();
    precipitation_layout->setSpacing(4);
    precipitation_icon = new QLabel(this);
    precipitation_icon->setPixmap(renderWeatherIcon(":/resources/icons/weather/rain.svg", icon_h));
    precipitation_icon->setAlignment(Qt::AlignVCenter);
    precipitation_layout->addWidget(precipitation_icon);
    precipitation_value = new QLabel(this);
    precipitation_value->setFont(value_font);
    precipitation_value->setAlignment(Qt::AlignCenter);
    precipitation_value->setText("-");
    precipitation_layout->addWidget(precipitation_value);
    precipitation_unit = new QLabel(this);
    precipitation_unit->setFont(unit_font);
    precipitation_unit->setAlignment(Qt::AlignCenter);
    precipitation_unit->setText("mm");
    precipitation_layout->addWidget(precipitation_unit);
    layout->addLayout(precipitation_layout);

    sub_splitter_2 = new QFrame(this);
    sub_splitter_2->setFrameStyle(QFrame::NoFrame);
    sub_splitter_2->setFixedHeight(2);
    sub_splitter_2->setStyleSheet("background-color: white; color: white; border: none; border-radius: 2px");
    layout->addWidget(sub_splitter_2);

    cloudcover_layout = new QHBoxLayout();
    cloudcover_layout->setSpacing(4);
    cloudcover_icon = new QLabel(this);
    cloudcover_icon->setPixmap(renderWeatherIcon(":/resources/icons/weather/clouds.svg", icon_h));
    cloudcover_icon->setAlignment(Qt::AlignVCenter);
    cloudcover_layout->addWidget(cloudcover_icon);
    cloudcover_value = new QLabel(this);
    cloudcover_value->setFont(value_font);
    cloudcover_value->setAlignment(Qt::AlignCenter);
    cloudcover_value->setText("-");
    cloudcover_layout->addWidget(cloudcover_value);
    cloudcover_unit = new QLabel(this);
    cloudcover_unit->setFont(unit_font);
    cloudcover_unit->setAlignment(Qt::AlignCenter);
    cloudcover_unit->setText("%");
    cloudcover_layout->addWidget(cloudcover_unit);
    layout->addLayout(cloudcover_layout);

    QFile style(":/resources/styles/weatherforecastcard.qss");
    if (style.open(QFile::ReadOnly | QFile::Text)) {
        QTextStream stream(&style);
        QString base_style = stream.readAll();
        setStyleSheet(base_style);
    }
}

void WeatherForecastCard::updateTime(quint8 time, int id) {
    if (this->id != id) {
        return;
    }

    QString time_str;
    if (time < 10) {
        time_str = "0" + QString::number(time);
    } else {
        time_str = QString::number(time);
    }

    this->time->setText(time_str);
}

void WeatherForecastCard::updatePrecipitation(quint8 value, int id) {
    if (this->id != id) {
        return;
    }
    precipitation_value->setText(QString::number(value));
}

void WeatherForecastCard::updateTemperature(qint8 value, int id) {
    if (this->id != id) {
        return;
    }
    temperature_value->setText(QString::number(value));
}

void WeatherForecastCard::updateTotalCloudCover(quint8 value, int id) {
    if (this->id != id) {
        return;
    }
    cloudcover_value->setText(QString::number(value));
}

void WeatherForecastCard::updateWindSpeed(quint8 value, int id) {
    if (this->id != id) {
        return;
    }
    windspeed_value->setText(QString::number(value));
}

QPixmap WeatherForecastCard::renderWeatherIcon(const QString &resource, int target_height) const {
    QSvgRenderer renderer(resource);
    QPixmap icon_map(target_height, target_height);
    icon_map.fill(Qt::transparent);
    {
        QPainter painter(&icon_map);
        painter.setRenderHint(QPainter::Antialiasing);
        painter.setRenderHint(QPainter::SmoothPixmapTransform);
        renderer.render(&painter);
    }
    {
        // Re-tint the rendered SVG to match the white label text.
        QPainter painter(&icon_map);
        painter.setCompositionMode(QPainter::CompositionMode_SourceIn);
        painter.setRenderHint(QPainter::Antialiasing);
        painter.fillRect(icon_map.rect(), Qt::white);
    }
    return icon_map;
}






