#ifndef FRONTEND_V2_WEATHERFORECASTMODEL_HH
#define FRONTEND_V2_WEATHERFORECASTMODEL_HH

#include <QAbstractListModel>
#include <QHash>
#include <QVector>

// One forecast hour. temperature is signed (sub-zero is normal here).
struct ForecastRow {
    int hour = 0;
    int temperature = 0;   // °C
    int windSpeed = 0;     // m/s
    int precipitation = 0; // mm
    int cloudCover = 0;    // %
};

/**
 * WeatherForecastModel — list model of upcoming forecast hours for the weather
 * view's Repeater. Roles: hour / temperature / windSpeed / precipitation /
 * cloudCover. Replaced wholesale each forecast frame (~15 min cadence) via
 * setRows(), so a Repeater/ListView re-lays-out atomically.
 */
class WeatherForecastModel : public QAbstractListModel {
    Q_OBJECT

public:
    enum Role {
        HourRole = Qt::UserRole + 1,
        TemperatureRole,
        WindSpeedRole,
        PrecipitationRole,
        CloudCoverRole,
    };

    using QAbstractListModel::QAbstractListModel;

    int rowCount(const QModelIndex &parent = QModelIndex()) const override;
    QVariant data(const QModelIndex &index, int role) const override;
    QHash<int, QByteArray> roleNames() const override;

    void setRows(const QVector<ForecastRow> &rows);

private:
    QVector<ForecastRow> m_rows;
};

#endif  // FRONTEND_V2_WEATHERFORECASTMODEL_HH
