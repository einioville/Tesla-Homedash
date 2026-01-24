//
// Created by ville on 1.1.2026.
//

#ifndef GUI_TESLASEATWIDGET_HH
#define GUI_TESLASEATWIDGET_HH

#include "../tesladatawidget.hh"
#include "../../vehicle.hh"
#include <QObject>
#include <QGridLayout>
#include <QLabel>
#include <vector>
#include <QGraphicsDropShadowEffect>
#include <QSvgRenderer>
#include <QHBoxLayout>
#include <QVBoxLayout>

class TeslaSeatWidget : public TeslaDataMultiWidget {
    Q_OBJECT

public:
    explicit TeslaSeatWidget(QWidget *parent, QVector<TeslaDataProperty *> td_properties, bool driver);

    enum SeatClimateState {
        OFF,
        HEATING,
        COOLING,
    };

public slots:
    void updateDataBool(const bool &value, const quint64 &timestamp) {
    };

    void updateDataString(const QString &value, const quint64 &timestamp) {
    };

    void updateDataLocation(const double &value_latitude, const double &value_longitude, const quint64 &timestamp) {
    };

    void updateDataDouble(const double &value, const quint64 &timestamp) override;

private:
    void drawSeatIcon(SeatClimateState seat_climate_state);

    void drawHeatingIcons(const int &value, const bool heating);

    void removeHeatingIcons();

    QVBoxLayout *m_main_layout;
    QHBoxLayout *m_state_level_layout;
    QLabel *m_seat;
    //QGraphicsDropShadowEffect *m_shadow;
    std::vector<QLabel *> m_cooling;
    std::vector<QLabel *> m_heating;
    int m_old_value_cooling;
    int m_old_value_heating;
    QSvgRenderer *m_renderer;
    bool m_driver;
};

#endif //GUI_TESLASEATWIDGET_HH
