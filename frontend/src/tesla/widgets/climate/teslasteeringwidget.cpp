//
// Created by ville on 2.1.2026.
//

#include "teslasteeringwidget.hh"
#include <QPixmap>
#include <QPainter>

TeslaSteeringwidget::TeslaSteeringwidget(QWidget *parent, TeslaDataProperty *td_property) : TeslaDataWidget(
    parent, td_property) {
    m_main_layout = new QVBoxLayout(this);
    m_main_layout->setAlignment(Qt::AlignCenter);
    m_main_layout->setContentsMargins(0, 0, 0, 0);
    m_main_layout->setSpacing(0);
    setLayout(m_main_layout);

    m_wheel = new QLabel(this);
    m_wheel->setFixedSize(30, 30);
    m_main_layout->addWidget(m_wheel, Qt::AlignCenter);

    m_heat_level_layout = new QHBoxLayout();
    m_heat_level_layout->setAlignment(Qt::AlignCenter);
    m_main_layout->addLayout(m_heat_level_layout);

    m_heating.reserve(2);
    QPixmap heating_pm = QPixmap(":/resources/icons/heating.png").scaled(
        10, 10, Qt::KeepAspectRatio, Qt::SmoothTransformation);
    for (uint8_t i = 0; i < 2; i++) {
        auto *heating_icon = new QLabel();
        heating_icon->setFixedSize(10, 10);
        heating_icon->setPixmap(heating_pm);
        m_heating.push_back(heating_icon);
        m_heat_level_layout->addWidget(heating_icon);
        heating_icon->setVisible(false);
    }

    m_renderer = new QSvgRenderer(this);

    setStyleSheet("border: none; background: transparent");

    drawWheelIcon(false);
    drawHeatingIcons(0);
}

void TeslaSteeringwidget::drawWheelIcon(bool heating) {
    m_renderer->load(QString(":/resources/icons/steering.svg"));

    QPixmap icon_map(30, 30);
    icon_map.fill(Qt::transparent);

    {
        QPainter painter(&icon_map);
        painter.setRenderHint(QPainter::Antialiasing);
        painter.setRenderHint(QPainter::SmoothPixmapTransform);
        m_renderer->render(&painter);
    }

    {
        QPainter painter(&icon_map);
        painter.setCompositionMode(QPainter::CompositionMode_SourceIn);
        painter.setRenderHint(QPainter::Antialiasing);

        if (heating) {
            painter.fillRect(icon_map.rect(), QColor(255, 0, 0, 255));
        } else {
            painter.fillRect(icon_map.rect(), QColor(255, 255, 255, 255));
        }
    }

    m_wheel->setPixmap(icon_map);

    /*
    switch (seat_climate_state) {
        case OFF:
            m_shadow->setColor(QColor(255, 255, 255, 255));
            break;
        case HEATING:
            m_shadow->setColor(QColor(255, 0, 0, 255));
            break;
        case COOLING:
            m_shadow->setColor(QColor(0, 0, 255, 255));
            break;
        default:
            m_shadow->setColor(QColor(255, 255, 255, 255));
            break;
    }
    */
}

void TeslaSteeringwidget::removeHeatingIcons() {
    for (const auto &i: m_heating) {
        i->setVisible(false);
    }
}

void TeslaSteeringwidget::drawHeatingIcons(const int &value) {
    removeHeatingIcons();

    for (uint8_t i = 0; i < m_heating.size(); i++) {
        m_heating[i]->setVisible(i < value);
    }
}

void TeslaSteeringwidget::updateDataDouble(const double &value, const quint64 &timestamp) {
    drawHeatingIcons(value);
    if (value > 0) {
        drawWheelIcon(true);
    } else {
        drawWheelIcon(false);
    }
}

