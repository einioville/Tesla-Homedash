//
// Created by ville on 1.1.2026.
//

#include "teslaseatwidget.hh"
#include <QColor>
#include <QPixmap>
#include <QString>
#include <QPainter>

TeslaSeatWidget::TeslaSeatWidget(QWidget *parent, QVector<TeslaDataProperty *> td_properties,
                                 bool driver) : TeslaDataMultiWidget(
    parent, td_properties) {
    m_main_layout = new QVBoxLayout(this);
    m_main_layout->setAlignment(Qt::AlignCenter);
    m_main_layout->setContentsMargins(0, 0, 0, 0);
    m_main_layout->setSpacing(0);
    setLayout(m_main_layout);

    m_seat = new QLabel(this);
    m_seat->setFixedSize(30, 30);
    m_main_layout->addWidget(m_seat, Qt::AlignCenter);

    /*
    m_shadow = new QGraphicsDropShadowEffect(this);
    m_shadow->setColor(QColor(255, 255, 255, 200));
    m_shadow->setOffset(0, 0);
    m_shadow->setBlurRadius(10);
    m_seat->setGraphicsEffect(m_shadow);
    */

    m_state_level_layout = new QHBoxLayout();
    m_state_level_layout->setAlignment(Qt::AlignCenter);
    m_main_layout->addLayout(m_state_level_layout);

    m_cooling.reserve(3);
    QPixmap cooling_pm = QPixmap(":/resources/icons/cooling.png").scaled(
        10, 10, Qt::KeepAspectRatio, Qt::SmoothTransformation);

    for (uint8_t i = 0; i < 3; i++) {
        auto *cooling_icon = new QLabel();
        cooling_icon->setFixedSize(10, 10);
        cooling_icon->setPixmap(cooling_pm);
        m_cooling.push_back(cooling_icon);
        cooling_icon->setVisible(false);
        m_state_level_layout->addWidget(cooling_icon);
    }

    m_heating.reserve(3);
    QPixmap heating_pm = QPixmap(":/resources/icons/heating.png").scaled(
        10, 10, Qt::KeepAspectRatio, Qt::SmoothTransformation);

    for (uint8_t i = 0; i < 3; i++) {
        auto *heating_icon = new QLabel();
        heating_icon->setFixedSize(10, 10);
        heating_icon->setPixmap(heating_pm);
        m_heating.push_back(heating_icon);
        heating_icon->setVisible(false);
        m_state_level_layout->addWidget(heating_icon);
    }

    m_renderer = new QSvgRenderer(this);

    m_driver = driver;

    setStyleSheet("border: none; background: transparent");

    drawHeatingIcons(0, true);
    drawSeatIcon(OFF);
}

void TeslaSeatWidget::drawSeatIcon(SeatClimateState seat_climate_state) {
    m_renderer->load(QString(":/resources/icons/seat.svg"));

    QPixmap icon_map(30, 30);
    icon_map.fill(Qt::transparent);

    {
        QPainter painter(&icon_map);
        painter.setRenderHint(QPainter::Antialiasing);
        painter.setRenderHint(QPainter::SmoothPixmapTransform);

        if (!m_driver) {
            painter.translate(icon_map.width(), 0);
            painter.scale(-1, 1);
        }

        m_renderer->render(&painter);
    }

    {
        QPainter painter(&icon_map);
        painter.setCompositionMode(QPainter::CompositionMode_SourceIn);
        painter.setRenderHint(QPainter::Antialiasing);

        switch (seat_climate_state) {
            case OFF:
                painter.fillRect(icon_map.rect(), QColor(255, 255, 255, 255));
                break;
            case HEATING:
                painter.fillRect(icon_map.rect(), QColor(255, 0, 0, 255));
                break;
            case COOLING:
                painter.fillRect(icon_map.rect(), QColor(0, 0, 255, 255));
                break;
            default:
                painter.fillRect(icon_map.rect(), QColor(255, 255, 255, 255));
                break;
        }
    }

    m_seat->setPixmap(icon_map);

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

void TeslaSeatWidget::removeHeatingIcons() {
    for (const auto &i: m_heating) {
        i->setVisible(false);
    }
}

void TeslaSeatWidget::drawHeatingIcons(const int &value, const bool heating) {
    removeHeatingIcons();

    if (heating) {
        for (uint8_t i = 0; i < m_heating.size(); i++) {
            m_heating[i]->setVisible(i < value);
        }
    } else {
        return;
    }
}

void TeslaSeatWidget::updateDataDouble(const double &value, const quint64 &timestamp) {
    drawHeatingIcons(value, true);
    if (value > 0) {
        drawSeatIcon(HEATING);
    } else {
        drawSeatIcon(OFF);
    }
    m_old_value_heating = value;
    m_old_value_cooling = value;
}

