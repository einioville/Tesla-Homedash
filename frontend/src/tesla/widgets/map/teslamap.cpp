//
// Created by ville on 27.11.2025.
//

#include "teslamap.hh"
#include <QUrl>
#include <QPainterPath>

TeslaMap::TeslaMap(QWidget *parent, QVector<TeslaDataProperty *> td_properties) : TeslaDataMultiWidget(
    parent, td_properties) {
    layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);

    engine = new QQmlEngine(this);

    view = new QQuickView(engine, nullptr);
    view->setResizeMode(QQuickView::SizeRootObjectToView);
    view->setColor(Qt::transparent);
    view->setSource(QUrl("qrc:/src/tesla/widgets/map/map.qml"));

    map = view->rootObject();

    container = QWidget::createWindowContainer(view, this);
    container->setFocusPolicy(Qt::StrongFocus);

    layout->addWidget(container);

    shadow = new QGraphicsDropShadowEffect(this);
    shadow->setBlurRadius(50);
    shadow->setXOffset(10);
    shadow->setYOffset(10);
    shadow->setColor(QColor(0, 0, 0, 150));
    setGraphicsEffect(shadow);
}

void TeslaMap::updateDataDouble(const double &value, const quint64 &timestamp) {
    if (map) {
        map->setProperty("rotation", value);
    }
}

void TeslaMap::updateDataLocation(const double &value_latitude, const double &value_longitude,
                                  const quint64 &timestamp) {
    qDebug() << "fhskjfghdfkunlghndakughadfngufdahgjfd";
    if (map) {
        map->setProperty("latitude", std::round(value_latitude * 1'000'000.0) / 1'000'000.0);
        map->setProperty("longitude", std::round(value_longitude * 1'000'000.0) / 1'000'000.0);
    }
}

void TeslaMap::updateDataString(const QString &value, const quint64 &timestamp) {
    return;
}

void TeslaMap::updateDataBool(const bool &value, const quint64 &timestamp) {
    return;
}

void TeslaMap::resizeEvent(QResizeEvent *event) {
    QWidget::resizeEvent(event);
    QPainterPath path;
    path.addRoundedRect(rect(), 5, 5);
    QRegion mask(path.toFillPolygon().toPolygon());
    setMask(mask);
}

void TeslaMap::connectToTeslaDataHandler(const TeslaDataHandler *handler) {
    handler->connectToDataUpdateSignal(getTeslaDataPropertyIds(), this);
}
