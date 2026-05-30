//
// Created by ville on 15.12.2025.
//

#include "currentweathercard.hh"
#include <QFile>
#include <QTextStream>
#include <QString>
#include <QFont>
#include <QFontMetrics>
#include <QPainter>
#include <QPixmap>
#include <QSvgRenderer>

CurrentWeatherCard::CurrentWeatherCard(QWidget *parent) : QFrame(parent) {
    setObjectName("currentweathercard");

    layout = new QHBoxLayout(this);
    layout->setContentsMargins(10, 10, 10, 10);
    setLayout(layout);

    temperature_font = QFont("Gotham Rounded Medium", 30);
    secondary_font = QFont("Gotham Rounded Medium", 18);
    secondary_unit_font = QFont("Gotham Rounded Medium", 14);

    const int temperature_icon_h = QFontMetrics(temperature_font).ascent();
    const int secondary_icon_h = QFontMetrics(secondary_font).ascent();

    temperature_layout = new QHBoxLayout();
    temperature_icon = new QLabel(this);
    temperature_icon->setPixmap(renderWeatherIcon(":/resources/icons/weather/thermometer.svg", temperature_icon_h));
    temperature_icon->setAlignment(Qt::AlignVCenter);
    temperature_layout->addWidget(temperature_icon);
    temperature_value = new QLabel(this);
    temperature_value->setFont(temperature_font);
    temperature_value->setText("-");
    temperature_layout->addWidget(temperature_value);
    temperature_unit = new QLabel(this);
    temperature_unit->setText("°C");
    temperature_unit->setFont(secondary_font);
    temperature_layout->addWidget(temperature_unit);
    layout->addLayout(temperature_layout);

    layout->addStretch();

    windspeed_layout = new QHBoxLayout();
    windspeed_layout->setSpacing(4);
    windspeed_icon = new QLabel(this);
    windspeed_icon->setPixmap(renderWeatherIcon(":/resources/icons/weather/wind.svg", secondary_icon_h));
    windspeed_icon->setAlignment(Qt::AlignVCenter);
    windspeed_layout->addWidget(windspeed_icon);
    windspeed_value = new QLabel(this);
    windspeed_value->setAlignment(Qt::AlignVCenter);
    windspeed_value->setFont(secondary_font);
    windspeed_value->setText("-");
    windspeed_layout->addWidget(windspeed_value);
    windspeed_unit = new QLabel(this);
    windspeed_unit->setAlignment(Qt::AlignVCenter);
    windspeed_unit->setFont(secondary_unit_font);
    windspeed_unit->setText("m/s");
    windspeed_layout->addWidget(windspeed_unit);
    layout->addLayout(windspeed_layout);

    splitter_1 = new QFrame(this);
    splitter_1->setFrameStyle(QFrame::NoFrame);
    splitter_1->setFixedWidth(4);
    splitter_1->setStyleSheet("background-color: white; color: white; border: none; border-radius: 2px");
    layout->addWidget(splitter_1);

    precipitation_layout = new QHBoxLayout();
    precipitation_layout->setSpacing(4);
    precipitation_icon = new QLabel(this);
    precipitation_icon->setPixmap(renderWeatherIcon(":/resources/icons/weather/rain.svg", secondary_icon_h));
    precipitation_icon->setAlignment(Qt::AlignVCenter);
    precipitation_layout->addWidget(precipitation_icon);
    precipitation_value = new QLabel(this);
    precipitation_value->setAlignment(Qt::AlignVCenter);
    precipitation_value->setFont(secondary_font);
    precipitation_value->setText("-");
    precipitation_layout->addWidget(precipitation_value);
    precipitation_unit = new QLabel(this);
    precipitation_unit->setAlignment(Qt::AlignVCenter);
    precipitation_unit->setFont(secondary_unit_font);
    precipitation_unit->setText("mm");
    precipitation_layout->addWidget(precipitation_unit);
    layout->addLayout(precipitation_layout);

    splitter_2 = new QFrame(this);
    splitter_2->setFrameStyle(QFrame::NoFrame);
    splitter_2->setFixedWidth(4);
    splitter_2->setStyleSheet("background-color: white; color: white; border: none; border-radius: 2px");
    layout->addWidget(splitter_2);

    cloudcover_layout = new QHBoxLayout();
    cloudcover_layout->setSpacing(4);
    cloudcover_icon = new QLabel(this);
    cloudcover_icon->setPixmap(renderWeatherIcon(":/resources/icons/weather/clouds.svg", secondary_icon_h));
    cloudcover_icon->setAlignment(Qt::AlignVCenter);
    cloudcover_layout->addWidget(cloudcover_icon);
    cloudcover_value = new QLabel(this);
    cloudcover_value->setAlignment(Qt::AlignVCenter);
    cloudcover_value->setFont(secondary_font);
    cloudcover_value->setText("-");
    cloudcover_layout->addWidget(cloudcover_value);
    cloudcover_unit = new QLabel(this);
    cloudcover_unit->setAlignment(Qt::AlignVCenter);
    cloudcover_unit->setFont(secondary_unit_font);
    cloudcover_unit->setText("%");
    cloudcover_layout->addWidget(cloudcover_unit);
    layout->addLayout(cloudcover_layout);

    QFile style(":resources/styles/currentweathercard.qss");
    if (style.open(QFile::ReadOnly | QFile::Text)) {
        QTextStream stream(&style);
        QString base_style = stream.readAll();
        setStyleSheet(base_style);
    }
}

void CurrentWeatherCard::updateTime(quint8 time, int id) {
    return;
}

void CurrentWeatherCard::updateTemperature(qint8 value, int id) {
    // Only react to the current-hour observation; ignore the forecast-hour
    // emits that share this signal (see kCurrentWeatherId).
    if (id != kCurrentWeatherId) {
        return;
    }
    temperature_value->setText(QString::number(value));
}

void CurrentWeatherCard::updatePrecipitation(quint8 value, int id) {
    if (id != kCurrentWeatherId) {
        return;
    }
    precipitation_value->setText(QString::number(value));
}

void CurrentWeatherCard::updateTotalCloudCover(quint8 value, int id) {
    if (id != kCurrentWeatherId) {
        return;
    }
    cloudcover_value->setText(QString::number(value));
}

void CurrentWeatherCard::updateWindSpeed(quint8 value, int id) {
    if (id != kCurrentWeatherId) {
        return;
    }
    windspeed_value->setText(QString::number(value));
}

QPixmap CurrentWeatherCard::renderWeatherIcon(const QString &resource, int target_height) const {
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
