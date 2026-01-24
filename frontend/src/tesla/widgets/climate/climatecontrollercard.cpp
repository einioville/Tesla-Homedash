//
// Created by ville on 27.12.2025.
//

#include "climatecontrollercard.hh"
#include <QSvgRenderer>
#include <QPixmap>
#include <QIcon>
#include <QPainter>
#include <QColor>
#include <QSize>
#include <QGraphicsDropShadowEffect>
#include <cmath>
#include <QSizePolicy>
#include <QPainterPath>
#include <QFile>
#include <QFont>
#include <QVector>

ClimateControllerCard::ClimateControllerCard(QWidget *parent, TeslaDataProperty *inside_temp,
                                             TeslaDataProperty *outside_temp,
                                             TeslaDataProperty *target_temp,
                                             TeslaDataProperty *hvac_power_state) : QFrame{parent} {
    setObjectName("ClimateController");

    layout = new QGridLayout(this);
    layout->setSpacing(10);
    layout->setContentsMargins(10, 10, 10, 10);
    setLayout(layout);

    this->inside_temp = new TemperatureCard(this, inside_temp, "Sisä");
    layout->addWidget(this->inside_temp, 0, 0, 1, 2, Qt::AlignLeft | Qt::AlignTop);

    title = new QLabel(this);
    title->setFont(QFont("Gotham Rounded Medium", 16));
    title->setText("Ilmastointi");
    title->setAlignment(Qt::AlignCenter);
    title->setStyleSheet("background: transparent");
    layout->addWidget(title, 0, 2, 1, 1, Qt::AlignHCenter | Qt::AlignTop);

    this->outside_temp = new TemperatureCard(this, outside_temp, "Ulko");
    layout->addWidget(this->outside_temp, 0, 3, 1, 2, Qt::AlignRight | Qt::AlignTop);

    climate_starter = new TeslaClimateStarter(this, hvac_power_state, 100, 100);
    climate_starter->setSizePolicy(QSizePolicy::Ignored, QSizePolicy::Ignored);
    layout->addWidget(climate_starter, 1, 1, 2, 3, Qt::AlignCenter);

    steering_wheel = new TeslaSteeringwidget(this, target_temp);
    layout->addWidget(steering_wheel, 2, 0, 1, 1, Qt::AlignBottom | Qt::AlignHCenter);

    QVector<TeslaDataProperty *> test;
    test.push_back(outside_temp);

    left_seat = new TeslaSeatWidget(this, test, true);
    layout->addWidget(left_seat, 3, 0, 1, 1, Qt::AlignBottom | Qt::AlignHCenter);

    minus_target_temp = new QPushButton(this);
    minus_target_temp->setFixedSize(40, 40);
    minus_target_temp->setIconSize(QSize(40, 40));
    minus_target_temp->setIcon(QIcon(":/resources/icons/arrow_left.svg"));
    minus_target_temp->setStyleSheet("border: none; background-color: rgba(0, 0, 0, 0)");
    layout->addWidget(minus_target_temp, 3, 1, 1, 1, Qt::AlignBottom | Qt::AlignHCenter);

    this->target_temp = new TemperatureCard(this, target_temp, "Target");
    layout->addWidget(this->target_temp, 3, 2, 1, 1, Qt::AlignBottom | Qt::AlignHCenter);

    plus_target_temp = new QPushButton(this);
    plus_target_temp->setFixedSize(40, 40);
    plus_target_temp->setIconSize(QSize(40, 40));
    plus_target_temp->setIcon(QIcon(":/resources/icons/arrow_right.svg"));
    plus_target_temp->setStyleSheet("border: none; background-color: rgba(0, 0, 0, 0)");
    layout->addWidget(plus_target_temp, 3, 3, 1, 1, Qt::AlignBottom | Qt::AlignHCenter);

    right_seat = new TeslaSeatWidget(this, test, false);
    layout->addWidget(right_seat, 3, 4, 1, 1, Qt::AlignBottom | Qt::AlignHCenter);

    arrow_left_shadow = new QGraphicsDropShadowEffect;
    arrow_left_shadow->setColor(QColor(0, 0, 255, 200));
    arrow_left_shadow->setOffset(0, 0);
    arrow_left_shadow->setBlurRadius(15);

    arrow_right_shadow = new QGraphicsDropShadowEffect;
    arrow_right_shadow->setColor(QColor(255, 0, 0, 200));
    arrow_right_shadow->setOffset(0, 0);
    arrow_right_shadow->setBlurRadius(15);

    //drawSteeringIcon(false);

    minus_target_temp->setGraphicsEffect(arrow_left_shadow);
    plus_target_temp->setGraphicsEffect(arrow_right_shadow);

    QFile style(":/resources/styles/climatecontroller.qss");
    if (style.open(QFile::ReadOnly | QFile::Text)) {
        QTextStream stream(&style);
        base_style = stream.readAll();
        setStyleSheet(base_style);
    }

    m_shadow = new QGraphicsDropShadowEffect(this);
    m_shadow->setBlurRadius(50);
    m_shadow->setXOffset(10);
    m_shadow->setYOffset(10);
    m_shadow->setColor(QColor(0, 0, 0, 150));
    setGraphicsEffect(m_shadow);
}

void ClimateControllerCard::connectItems(TeslaDataHandler *tesla_data_handler) {
    tesla_data_handler->connectToDataUpdateSignal(40, steering_wheel);
    tesla_data_handler->connectToDataUpdateSignal({43}, left_seat);
    tesla_data_handler->connectToDataUpdateSignal({44}, right_seat);
    tesla_data_handler->connectToDataUpdateSignal(39, climate_starter);
    tesla_data_handler->connectToDataUpdateSignal(22, outside_temp);
    tesla_data_handler->connectToDataUpdateSignal(17, inside_temp);
    tesla_data_handler->connectToDataUpdateSignal(15, target_temp);
    connect(minus_target_temp, &QPushButton::clicked, tesla_data_handler, &TeslaDataHandler::minusTargetTemperature);
    connect(plus_target_temp, &QPushButton::clicked, tesla_data_handler, &TeslaDataHandler::plusTargetTemperature);
    connect(climate_starter->getStarter(), &QPushButton::clicked, tesla_data_handler,
            &TeslaDataHandler::switchClimateState);
}

