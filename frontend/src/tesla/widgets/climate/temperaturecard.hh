//
// Created by ville on 27.12.2025.
//

#ifndef GUI_TEMPERATURECARD_HH
#define GUI_TEMPERATURECARD_HH
#include "../tesladatawidget.hh"
#include <QLabel>
#include <QVBoxLayout>
#include <QFrame>
#include "../../vehicle.hh"
#include <QString>
#include <string>
#include <QFont>

class TemperatureCard : public TeslaDataWidget {
public:
    TemperatureCard(QWidget *parent, TeslaDataProperty *td_property, const QString &title);

public slots:
    void updateDataDouble(const double &value, const quint64 &timestamp) override;

    void updateDataString(const QString &value, const quint64 &timestamp) override;

    void updateDataBool(const bool &value, const quint64 &timestamp) override;

    void updateDataLocation(const double &value_latitude, const double &value_longitude,
                            const quint64 &timestamp) override;

private:
    QVBoxLayout *layout;
    QLabel *title;
    QLabel *value;
    QString unit;
    QFont font;
};

#endif //GUI_TEMPERATURECARD_HH
