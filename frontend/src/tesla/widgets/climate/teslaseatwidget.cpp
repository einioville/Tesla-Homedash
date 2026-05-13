//
// Created by ville on 1.1.2026.
//

#include "teslaseatwidget.hh"
#include <QColor>
#include <QPixmap>
#include <QString>
#include <QPainter>
#include <QSvgRenderer>

TeslaSeatWidget::TeslaSeatWidget(QWidget *parent, QVector<TeslaDataProperty *> td_properties,
                                 bool driver) : TeslaDataMultiWidget(
    parent, td_properties) {
    m_driver = driver;

    m_main_layout = new QVBoxLayout(this);
    m_main_layout->setAlignment(Qt::AlignCenter);
    m_main_layout->setContentsMargins(0, 0, 0, 0);
    m_main_layout->setSpacing(0);
    setLayout(m_main_layout);

    m_seat = new QLabel(this);
    m_seat->setFixedSize(30, 30);
    m_main_layout->addWidget(m_seat, Qt::AlignCenter);

    m_state_level_layout = new QHBoxLayout();
    m_state_level_layout->setAlignment(Qt::AlignCenter);
    m_main_layout->addLayout(m_state_level_layout);

    m_cooling.reserve(3);
    QPixmap cooling_pm = QPixmap(":/resources/icons/cooling.png").scaled(
        10, 10, Qt::KeepAspectRatio, Qt::SmoothTransformation);

    for (uint8_t i = 0; i < 3; i++) {
        auto *cooling_icon = new QLabel(this);
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
        auto *heating_icon = new QLabel(this);
        heating_icon->setFixedSize(10, 10);
        heating_icon->setPixmap(heating_pm);
        m_heating.push_back(heating_icon);
        heating_icon->setVisible(false);
        m_state_level_layout->addWidget(heating_icon);
    }

    // Render the seat silhouette once per tint at construction. The per-update
    // drawSeatIcon path just swaps the cached pixmap into m_seat.
    m_icon_off = renderSeatPixmap(QColor(255, 255, 255, 255));
    m_icon_heating = renderSeatPixmap(QColor(255, 0, 0, 255));
    m_icon_cooling = renderSeatPixmap(QColor(0, 0, 255, 255));

    setStyleSheet("border: none; background: transparent");

    drawHeatingIcons(0, true);
    drawSeatIcon(OFF);
}

QPixmap TeslaSeatWidget::renderSeatPixmap(const QColor &tint) const {
    QSvgRenderer renderer(QString(":/resources/icons/seat.svg"));

    QPixmap icon_map(30, 30);
    icon_map.fill(Qt::transparent);

    {
        QPainter painter(&icon_map);
        painter.setRenderHint(QPainter::Antialiasing);
        painter.setRenderHint(QPainter::SmoothPixmapTransform);

        // Passenger seat mirrors the driver SVG horizontally.
        if (!m_driver) {
            painter.translate(icon_map.width(), 0);
            painter.scale(-1, 1);
        }

        renderer.render(&painter);
    }

    {
        QPainter painter(&icon_map);
        painter.setCompositionMode(QPainter::CompositionMode_SourceIn);
        painter.setRenderHint(QPainter::Antialiasing);
        painter.fillRect(icon_map.rect(), tint);
    }

    return icon_map;
}

void TeslaSeatWidget::drawSeatIcon(SeatClimateState seat_climate_state) {
    switch (seat_climate_state) {
        case HEATING:
            m_seat->setPixmap(m_icon_heating);
            break;
        case COOLING:
            m_seat->setPixmap(m_icon_cooling);
            break;
        case OFF:
        default:
            m_seat->setPixmap(m_icon_off);
            break;
    }
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
