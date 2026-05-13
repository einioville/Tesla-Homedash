//
// Created by ville on 2.1.2026.
//

#include "teslasteeringwidget.hh"
#include <QPixmap>
#include <QPainter>
#include <QSvgRenderer>

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
        auto *heating_icon = new QLabel(this);
        heating_icon->setFixedSize(10, 10);
        heating_icon->setPixmap(heating_pm);
        m_heating.push_back(heating_icon);
        m_heat_level_layout->addWidget(heating_icon);
        heating_icon->setVisible(false);
    }

    // Render the wheel SVG once per tint at construction.
    m_icon_off = renderWheelPixmap(QColor(255, 255, 255, 255));
    m_icon_heating = renderWheelPixmap(QColor(255, 0, 0, 255));

    setStyleSheet("border: none; background: transparent");

    drawWheelIcon(false);
    drawHeatingIcons(0);
}

QPixmap TeslaSteeringwidget::renderWheelPixmap(const QColor &tint) const {
    QSvgRenderer renderer(QString(":/resources/icons/steering.svg"));

    QPixmap icon_map(30, 30);
    icon_map.fill(Qt::transparent);

    {
        QPainter painter(&icon_map);
        painter.setRenderHint(QPainter::Antialiasing);
        painter.setRenderHint(QPainter::SmoothPixmapTransform);
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

void TeslaSteeringwidget::drawWheelIcon(bool heating) {
    m_wheel->setPixmap(heating ? m_icon_heating : m_icon_off);
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
    drawWheelIcon(value > 0);
}
