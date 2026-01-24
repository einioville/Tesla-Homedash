//
// Created by ville on 27.11.2025.
//

#ifndef GUI_MAP_HH
#define GUI_MAP_HH
#include <QQuickWidget>
#include <QWidget>
#include <QQuickItem>
#include <QGraphicsDropShadowEffect>
#include <QQuickView>
#include <QQmlEngine>
#include <QVBoxLayout>
#include <QPainterPath>
#include "../tesladatawidget.hh"
#include "../../vehicle.hh"
#include "../../datahandler/tesladatahandler.hh"

class TeslaMap : public TeslaDataMultiWidget {
    Q_OBJECT

public:
    explicit TeslaMap(QWidget *parent, QVector<TeslaDataProperty *> td_properties);

    void connectToTeslaDataHandler(const TeslaDataHandler *handler);

public slots:
    void updateDataDouble(const double &value, const quint64 &timestamp) override;

    void updateDataLocation(const double &value_latitude, const double &value_longitude,
                            const quint64 &timestamp) override;

    void updateDataBool(const bool &value, const quint64 &timestamp) override;

    void updateDataString(const QString &value, const quint64 &timestamp) override;

    void resizeEvent(QResizeEvent *event) override;

private:
    QVBoxLayout *layout;
    QQuickView *view;
    QWidget *container;
    QQmlEngine *engine;
    QQuickItem *map;
    QGraphicsDropShadowEffect *shadow;
};

#endif //GUI_MAP_HH
