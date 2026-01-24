//
// Created by ville on 31.12.2025.
//

#ifndef GUI_TESLACLIMATESTARTER_HH
#define GUI_TESLACLIMATESTARTER_HH

#include <QObject>
#include "../tesladatawidget.hh"
#include "../../vehicle.hh"
#include <QPushButton>
#include <QLabel>
#include <QString>
#include <queue>
#include <QWidget>
#include <QHBoxLayout>
#include <QGraphicsDropShadowEffect>

class TeslaClimateStarter : public TeslaDataWidget {
    Q_OBJECT

public:
    explicit TeslaClimateStarter(QWidget *parent, TeslaDataProperty *tesla_data_property, int w, int h);

    QPushButton *getStarter();

public slots:
    void updateDataString(const QString &value, const quint64 &timestamp) override;

    void updateDataBool(const bool &value, const quint64 &timestamp) {
    };

    void updateDataDouble(const double &value, const quint64 &timestamp) {
    };

    void updateDataLocation(const double &value_latitude, const double &value_longitude, const quint64 &timestamp) {
    };

signals:
    void onShadowUpdate(const QString &shadow_name);

private:
    QHBoxLayout *m_layout;
    QPushButton *m_start_button;
    QGraphicsDropShadowEffect *m_shadow;
};

#endif //GUI_TESLACLIMATESTARTER_HH
