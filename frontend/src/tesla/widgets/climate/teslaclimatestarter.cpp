//
// Created by ville on 31.12.2025.
//

#include "teslaclimatestarter.hh"
#include <QIcon>
#include <QSize>
#include <QColor>
#include <QSizePolicy>

TeslaClimateStarter::TeslaClimateStarter(QWidget *parent, TeslaDataProperty *tesla_data_property, int w,
                                         int h) : TeslaDataWidget(
    parent, tesla_data_property) {
    m_layout = new QHBoxLayout(this);
    setLayout(m_layout);

    m_start_button = new QPushButton(this);
    m_start_button->setFixedSize(w, h);
    m_start_button->setIconSize(QSize(w, h));
    m_start_button->setIcon(QIcon(":/resources/icons/power_off.svg"));
    m_start_button->setStyleSheet("border: none; background: transparent");
    m_layout->addWidget(m_start_button);

    m_shadow = new QGraphicsDropShadowEffect(m_start_button);
    m_shadow->setBlurRadius(15);
    m_shadow->setOffset(0, 0);
    m_shadow->setColor(QColor(255, 0, 0, 255));
    m_start_button->setGraphicsEffect(m_shadow);
}

void TeslaClimateStarter::updateDataString(const QString &value, const quint64 &timestamp) {
    if (value == "HvacPowerStateOff") {
        m_start_button->setIcon(QIcon(":/resources/icons/power_off.svg"));
        m_shadow->setColor(QColor(255, 0, 0, 255));
    } else if (value == "HvacPowerStateOn") {
        m_start_button->setIcon(QIcon(":/resources/icons/power_on.svg"));
        m_shadow->setColor(QColor(0, 255, 0, 255));
    } else {
        m_start_button->setIcon(QIcon(":/resources/icons/power_pending.svg"));
        m_shadow->setColor(QColor(255, 255, 0, 255));
    }
}

QPushButton *TeslaClimateStarter::getStarter() {
    return m_start_button;
}

