#ifndef FRONTEND_V2_WEATHERDATA_HH
#define FRONTEND_V2_WEATHERDATA_HH

#include <QByteArray>
#include <QObject>
#include <QVariantMap>

class ServerClient;

/**
 * WeatherData — the `Weather` singleton: the backend's WEATHER_VIEW document, read by the
 * Weather view and the dashboard panel that reuses its hourly card. Carried as the backend's
 * JSON, opaque here like SystemStatus's, so a field the view gains needs no C++ change.
 * WEATHER_FORECAST is the frozen frontend's and is ignored.
 */
class WeatherData : public QObject {
    Q_OBJECT
    // {meta, now, hourly, daily, astro, warnings}; empty until the first document.
    Q_PROPERTY(QVariantMap view READ view NOTIFY viewChanged)
    Q_PROPERTY(bool hasView READ hasView NOTIFY viewChanged)

public:
    explicit WeatherData(ServerClient *server, QObject *parent = nullptr);

    QVariantMap view() const { return m_view; }
    bool hasView() const { return !m_view.isEmpty(); }

signals:
    void viewChanged();

private slots:
    void onPacket(quint8 type, const QByteArray &payload);

private:
    QVariantMap m_view;
};

#endif  // FRONTEND_V2_WEATHERDATA_HH
