//
// Created by ville on 15.12.2025.
//

#include "currentweathercard.hh"
#include <QFile>
#include <QTextStream>
#include <QString>
#include <QFont>

CurrentWeatherCard::CurrentWeatherCard(QWidget *parent) : QFrame(parent) {
    setObjectName("currentweathercard");

    layout = new QHBoxLayout(this);
    layout->setContentsMargins(10, 10, 10, 10);
    setLayout(layout);

    temperature_font = QFont("Gotham Rounded Medium", 30);
    secondary_font = QFont("Gotham Rounded Medium", 18);
    secondary_unit_font = QFont("Gotham Rounded Medium", 14);

    temperature_layout = new QHBoxLayout();
    temperature_value = new QLabel(this);
    temperature_value->setFont(temperature_font);
    temperature_value->setText("27,5");
    temperature_layout->addWidget(temperature_value);
    temperature_unit = new QLabel(this);
    temperature_unit->setText("°C");
    temperature_unit->setFont(secondary_font);
    temperature_layout->addWidget(temperature_unit);
    layout->addLayout(temperature_layout);

    layout->addStretch();

    windspeed_layout = new QVBoxLayout();
    windspeed_value = new QLabel(this);
    windspeed_value->setAlignment(Qt::AlignHCenter | Qt::AlignBottom);
    windspeed_value->setFixedWidth(90);
    windspeed_value->setFont(secondary_font);
    windspeed_value->setText("37,5");
    windspeed_layout->addWidget(windspeed_value);
    windspeed_unit = new QLabel(this);
    windspeed_unit->setAlignment(Qt::AlignHCenter | Qt::AlignTop);
    windspeed_unit->setFont(secondary_unit_font);
    windspeed_unit->setText("m/s");
    windspeed_layout->addWidget(windspeed_unit);
    layout->addLayout(windspeed_layout);

    splitter_1 = new QFrame(this);
    splitter_1->setFrameStyle(QFrame::NoFrame);
    splitter_1->setFixedWidth(4);
    splitter_1->setStyleSheet("background-color: white; color: white; border: none; border-radius: 2px");
    layout->addWidget(splitter_1);

    precipitation_layout = new QVBoxLayout();
    precipitation_value = new QLabel(this);
    precipitation_value->setAlignment(Qt::AlignHCenter | Qt::AlignBottom);
    precipitation_value->setFixedWidth(90);
    precipitation_value->setFont(secondary_font);
    precipitation_value->setText("2,5");
    precipitation_layout->addWidget(precipitation_value);
    precipitation_unit = new QLabel(this);
    precipitation_unit->setAlignment(Qt::AlignHCenter | Qt::AlignTop);
    precipitation_unit->setFont(secondary_unit_font);
    precipitation_unit->setText("mm");
    precipitation_layout->addWidget(precipitation_unit);
    layout->addLayout(precipitation_layout);

    splitter_2 = new QFrame(this);
    splitter_2->setFrameStyle(QFrame::NoFrame);
    splitter_2->setFixedWidth(4);
    splitter_2->setStyleSheet("background-color: white; color: white; border: none; border-radius: 2px");
    layout->addWidget(splitter_2);

    cloudcover_layout = new QVBoxLayout();
    cloudcover_value = new QLabel(this);
    cloudcover_value->setAlignment(Qt::AlignHCenter | Qt::AlignBottom);
    cloudcover_value->setFixedWidth(90);
    cloudcover_value->setFont(secondary_font);
    cloudcover_value->setText("88");
    cloudcover_layout->addWidget(cloudcover_value);
    cloudcover_unit = new QLabel(this);
    cloudcover_unit->setAlignment(Qt::AlignHCenter | Qt::AlignTop);
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

void CurrentWeatherCard::updateTemperature(double value, int id) {
    temperature_value->setText(QString::number(value));
}

void CurrentWeatherCard::updatePrecipitation(double value, int id) {
    precipitation_value->setText(QString::number(value));
}

void CurrentWeatherCard::updateTotalCloudCover(double value, int id) {
    cloudcover_value->setText(QString::number(value));
}

void CurrentWeatherCard::updateWindSpeed(double value, int id) {
    windspeed_value->setText(QString::number(value));
}
