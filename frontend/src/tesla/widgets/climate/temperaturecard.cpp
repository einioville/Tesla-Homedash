//
// Created by ville on 27.12.2025.
//

#include "temperaturecard.hh"
#include <QString>

TemperatureCard::TemperatureCard(QWidget *parent, TeslaDataProperty *td_property,
                                 const QString &title) : TeslaDataWidget{parent, td_property} {
    layout = new QVBoxLayout(this);
    setLayout(layout);

    font = QFont("Gotham Rounded Medium", 12);

    this->title = new QLabel(this);
    this->title->setText(title);
    this->title->setFont(font);
    this->title->setAlignment(Qt::AlignBottom | Qt::AlignHCenter);
    layout->addWidget(this->title, Qt::AlignBottom | Qt::AlignHCenter);

    value = new QLabel(this);
    value->setText("21 °C");
    value->setFont(font);
    value->setAlignment(Qt::AlignBottom | Qt::AlignHCenter);
    layout->addWidget(value, Qt::AlignBottom | Qt::AlignHCenter);

    unit = QString::fromStdString(td_property->unit);
    setStyleSheet("background: transparent");
}

void TemperatureCard::updateDataBool(const bool &value, const quint64 &timestamp) {
    return;
}

void TemperatureCard::updateDataDouble(const double &value, const quint64 &timestamp) {
    this->value->setText(QString::number(value) + " " + unit);
}

void TemperatureCard::updateDataLocation(const double &value_latitude, const double &value_longitude,
                                         const quint64 &timestamp) {
    return;
}

void TemperatureCard::updateDataString(const QString &value, const quint64 &timestamp) {
    return;
}


