//
// Created by ville on 2.1.2026.
//

#ifndef GUI_TESLASTEERINGWIDGET_HH
#define GUI_TESLASTEERINGWIDGET_HH

#include "../tesladatawidget.hh"
#include <QObject>
#include "../../vehicle.hh"
#include <QHBoxLayout>
#include <QVBoxLayout>
#include <QLabel>
#include <vector>
#include <QSvgRenderer>

class TeslaSteeringwidget : public TeslaDataWidget {
    Q_OBJECT

public:
    explicit TeslaSteeringwidget(QWidget *parent, TeslaDataProperty *td_property);

public slots:
    void updateDataBool(const bool &value, const quint64 &timestamp) {
    };

    void updateDataString(const QString &value, const quint64 &timestamp) {
    };

    void updateDataLocation(const double &value_latitude, const double &value_longitude, const quint64 &timestamp) {
    };

    void updateDataDouble(const double &value, const quint64 &timestamp) override;

private:
    void drawWheelIcon(bool heating);

    void drawHeatingIcons(const int &value);

    void removeHeatingIcons();

    QVBoxLayout *m_main_layout;
    QHBoxLayout *m_heat_level_layout;
    QLabel *m_wheel;
    std::vector<QLabel *> m_heating;
    int m_old_value_heating;
    QSvgRenderer *m_renderer;
};

#endif //GUI_TESLASTEERINGWIDGET_HH
