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
    // Sentinel id MainWeather tags the current-hour observation (row 0) with.
    // The banner shares the forecast cards' update signals, so it must ignore
    // every emit except the one carrying this id — otherwise the later
    // forecast-hour emits overwrite it and it ends up mirroring the last card.
    static constexpr int kCurrentWeatherId = 69;

    explicit CurrentWeatherCard(QWidget *parent);

public slots:
    void updateTime(quint8 time, int id);

    void updateTemperature(qint8 value, int id);

    void updateWindSpeed(quint8 value, int id);

    void updatePrecipitation(quint8 value, int id);

    void updateTotalCloudCover(quint8 value, int id);

private:
    QPixmap renderWeatherIcon(const QString &resource, int target_height) const;

    QHBoxLayout *layout;

    QHBoxLayout *temperature_layout;
    QLabel *temperature_icon;
    QLabel *temperature_value;
    QLabel *temperature_unit;

    QHBoxLayout *windspeed_layout;
    QLabel *windspeed_icon;
    QLabel *windspeed_value;
    QLabel *windspeed_unit;

    QFrame *splitter_1;

    QHBoxLayout *precipitation_layout;
    QLabel *precipitation_icon;
    QLabel *precipitation_value;
    QLabel *precipitation_unit;

    QFrame *splitter_2;

    QHBoxLayout *cloudcover_layout;
    QLabel *cloudcover_icon;
    QLabel *cloudcover_value;
    QLabel *cloudcover_unit;

    QFont temperature_font;
    QFont secondary_font;
    QFont secondary_unit_font;
};

#endif //GUI_CURRENTWEATHERCARD_HH
