//
// Created by ville on 13.12.2025.
//

#include "weatherforecastcard.hh"
#include <QString>
#include <QTextStream>
#include <QFile>

WeatherForecastCard::WeatherForecastCard(QWidget *parent, int id) : QFrame(parent) {
    setObjectName("weathercard");
    this->id = id;

    layout = new QVBoxLayout(this);
    layout->setContentsMargins(10, 10, 10, 10);
    layout->setSpacing(0);
    setLayout(layout);

    value_font = QFont("Gotham Rounded Medium", 14);
    unit_font = QFont("Gotham Rounded Medium", 10);

    time = new QLabel(this);
    time->setFont(value_font);
    time->setAlignment(Qt::AlignCenter);
    time->setText("12");
    layout->addWidget(time);

    temperature_layout = new QHBoxLayout();
    temperature_value = new QLabel(this);
    temperature_value->setFont(value_font);
    temperature_value->setAlignment(Qt::AlignCenter);
    temperature_value->setText("27,5");
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
    windspeed_value = new QLabel(this);
    windspeed_value->setFont(value_font);
    windspeed_value->setAlignment(Qt::AlignCenter);
    windspeed_value->setText("37,5");
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
    precipitation_value = new QLabel(this);
    precipitation_value->setFont(value_font);
    precipitation_value->setAlignment(Qt::AlignCenter);
    precipitation_value->setText("2,5");
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
    cloudcover_value = new QLabel(this);
    cloudcover_value->setFont(value_font);
    cloudcover_value->setAlignment(Qt::AlignCenter);
    cloudcover_value->setText("88");
    cloudcover_layout->addWidget(cloudcover_value);
    cloudcover_unit = new QLabel(this);
    cloudcover_unit->setFont(unit_font);
    cloudcover_unit->setAlignment(Qt::AlignCenter);
    cloudcover_unit->setText("%");
    cloudcover_layout->addWidget(cloudcover_unit);
    layout->addLayout(cloudcover_layout);

    QFile style(":resources/styles/weathercard.qss");
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

void WeatherForecastCard::updatePrecipitation(double value, int id) {
    if (this->id != id) {
        return;
    }
    precipitation_value->setText(QString::number(value));
}

void WeatherForecastCard::updateTemperature(double value, int id) {
    if (this->id != id) {
        return;
    }
    temperature_value->setText(QString::number(value));
}

void WeatherForecastCard::updateTotalCloudCover(double value, int id) {
    if (this->id != id) {
        return;
    }
    cloudcover_value->setText(QString::number(value));
}

void WeatherForecastCard::updateWindSpeed(double value, int id) {
    if (this->id != id) {
        return;
    }
    windspeed_value->setText(QString::number(value));
}






