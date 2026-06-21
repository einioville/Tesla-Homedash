#ifndef FRONTEND_V2_WEATHERDATA_HH
#define FRONTEND_V2_WEATHERDATA_HH

#include <QAbstractListModel>
#include <QByteArray>
#include <QObject>
#include <QVariantMap>

#include "weatherforecastmodel.hh"

class ServerClient;

/**
 * WeatherData — the single weather datahandler, exposed to QML as the `Weather`
 * singleton. Parses the WEATHER_FORECAST frame into per-hour rows: row 0 is the
 * live current-hour observation (exposed as the `current` object for a banner),
 * rows 1.. populate the `forecast` list model. Built in C++ so the positional
 * hour↔value correlation is preserved; temperature is kept signed.
 */
class WeatherData : public QObject {
    Q_OBJECT
    Q_PROPERTY(QAbstractListModel *forecast READ forecast CONSTANT)
    Q_PROPERTY(QVariantMap current READ current NOTIFY currentChanged)
    Q_PROPERTY(bool hasData READ hasData NOTIFY currentChanged)

public:
    explicit WeatherData(ServerClient *server, QObject *parent = nullptr);

    QAbstractListModel *forecast() const { return m_forecast; }
    QVariantMap current() const { return m_current; }
    bool hasData() const { return !m_current.isEmpty(); }

signals:
    void currentChanged();

private slots:
    void onPacket(quint8 type, const QByteArray &payload);

private:
    WeatherForecastModel *m_forecast;
    QVariantMap m_current;
};

#endif  // FRONTEND_V2_WEATHERDATA_HH
