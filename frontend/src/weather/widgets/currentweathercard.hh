//
// Created by ville on 15.12.2025.
//

#ifndef GUI_CURRENTWEATHERCARD_HH
#define GUI_CURRENTWEATHERCARD_HH
#include <QFrame>
#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QLabel>
#include <QFont>

class CurrentWeatherCard : public QFrame {
    Q_OBJECT

public:
    explicit CurrentWeatherCard(QWidget *parent);

public slots:
    void updateTime(quint8 time, int id);

    void updateTemperature(double value, int id);

    void updateWindSpeed(double value, int id);

    void updatePrecipitation(double value, int id);

    void updateTotalCloudCover(double value, int id);

private:
    QHBoxLayout *layout;

    QHBoxLayout *temperature_layout;
    QLabel *temperature_value;
    QLabel *temperature_unit;

    QVBoxLayout *windspeed_layout;
    QLabel *windspeed_value;
    QLabel *windspeed_unit;

    QFrame *splitter_1;

    QVBoxLayout *precipitation_layout;
    QLabel *precipitation_value;
    QLabel *precipitation_unit;

    QFrame *splitter_2;

    QVBoxLayout *cloudcover_layout;
    QLabel *cloudcover_value;
    QLabel *cloudcover_unit;

    QFont temperature_font;
    QFont secondary_font;
    QFont secondary_unit_font;
};

#endif //GUI_CURRENTWEATHERCARD_HH
