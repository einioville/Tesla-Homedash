//
// Created by ville on 27.12.2025.
//

#ifndef GUI_CLIMATECONTROLLER_HH
#define GUI_CLIMATECONTROLLER_HH
#include <QFrame>
#include "../../datahandler/tesladatahandler.hh"
#include "../tesladatawidget.hh"
#include <QPushButton>
#include <QGridLayout>
#include <QLabel>
#include "temperaturecard.hh"
#include "../../vehicle.hh"
#include <QSvgRenderer>
#include <QGraphicsDropShadowEffect>
#include <QTimer>
#include "../tesladatawidget.hh"
#include <QLinearGradient>
#include "teslaclimatestarter.hh"
#include "teslaseatwidget.hh"
#include "teslasteeringwidget.hh"
#include "../../datahandler/tesladatahandler.hh"
#include <QGraphicsDropShadowEffect>

class ClimateControllerCard : public QFrame {
    Q_OBJECT

public:
    ClimateControllerCard(QWidget *parent, TeslaDataProperty *inside_temp, TeslaDataProperty *outside_temp,
                          TeslaDataProperty *target_temp, TeslaDataProperty *hvac_power_state);

    void connectItems(TeslaDataHandler *tesla_data_handler);

private:
    QGridLayout *layout;

    QLabel *title;

    TemperatureCard *inside_temp;
    TemperatureCard *outside_temp;
    TemperatureCard *target_temp;

    QPushButton *minus_target_temp;
    QPushButton *plus_target_temp;

    TeslaSteeringwidget *steering_wheel;
    TeslaClimateStarter *climate_starter;

    TeslaSeatWidget *left_seat;
    TeslaSeatWidget *right_seat;

    QGraphicsDropShadowEffect *arrow_left_shadow;
    QGraphicsDropShadowEffect *arrow_right_shadow;
    QString base_style;

    QGraphicsDropShadowEffect *m_shadow;
};

#endif //GUI_CLIMATECONTROLLER_HH
