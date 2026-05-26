//
// Created by ville on 13.12.2025.
//

#ifndef GUI_WEATHERFORECASTCARD_HH
#define GUI_WEATHERFORECASTCARD_HH
#include <QWidget>
#include <QHBoxLayout>
#include <QVBoxLayout>
#include <QLabel>
#include <QFrame>
#include <QFont>

class WeatherForecastCard : public QFrame {
    Q_OBJECT

public:
    explicit WeatherForecastCard(QWidget *parent, int id);

public slots:
    void updateTime(quint8 time, int id);

    void updateTemperature(qint8 value, int id);

    void updateWindSpeed(quint8 value, int id);

    void updatePrecipitation(quint8 value, int id);

    void updateTotalCloudCover(quint8 value, int id);

private:
    QPixmap renderWeatherIcon(const QString &resource, int target_height) const;

    int id;

    QVBoxLayout *layout;

    QLabel *time;

    QHBoxLayout *temperature_layout;
    QLabel *temperature_icon;
    QLabel *temperature_value;
    QLabel *temperature_unit;

    QHBoxLayout *windspeed_layout;
    QLabel *windspeed_icon;
    QLabel *windspeed_value;
    QLabel *windspeed_unit;

    QHBoxLayout *precipitation_layout;
    QLabel *precipitation_icon;
    QLabel *precipitation_value;
    QLabel *precipitation_unit;

    QHBoxLayout *cloudcover_layout;
    QLabel *cloudcover_icon;
    QLabel *cloudcover_value;
    QLabel *cloudcover_unit;

    QFrame *main_splitter;
    QFrame *sub_splitter_1;
    QFrame *sub_splitter_2;

    QFont value_font;
    QFont unit_font;
};

#endif //GUI_WEATHERFORECASTCARD_HH
