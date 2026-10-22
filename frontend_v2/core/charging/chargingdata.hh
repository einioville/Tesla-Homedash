#ifndef FRONTEND_V2_CHARGINGDATA_HH
#define FRONTEND_V2_CHARGINGDATA_HH

#include <QByteArray>
#include <QList>
#include <QObject>
#include <QPointF>
#include <QVariantMap>

class ServerClient;

/**
 * ChargingData — the Charging-view datahandler, exposed to QML as the `Charging`
 * singleton. It combines three flows over the one socket:
 *
 *  - Live charger state: parses the CHARGER_STREAM broadcast (myenergi) into the tile
 *    properties the view shows (status, charge and grid power, session energy); the
 *    frame's other fields are read past. Updated on every frame regardless of view state.
 *  - Past-hour power graphs: startLive() seeds two rolling 1 h series (grid power +
 *    charge power) from CHARGER_HISTORY, then extends each from the live stream — every
 *    series drives a HistoryGraph via a ready (reload) + tick (advance) signal, the same
 *    contract TeslaHistory's live mode uses, but sourced from the stream instead of a
 *    polled value. stopLive() freezes the graph buffers while the view is hidden.
 *  - Month-to-date stats: requestMonth() -> CHARGING_MONTH -> the `monthSummary` map.
 *
 * Parsing runs on the GUI thread (the bound properties are not thread-safe). A short
 * spot-price, month or history header drops the frame; a history reply cut inside its
 * points keeps the points before the cut, and a CHARGER_STREAM frame keeps the fields
 * before its first truncated or unknown one. A charger-history reply is routed to its
 * series by the echoed id; a request dropped while the socket was down is re-issued on
 * reconnect (as TripsData does).
 */
class ChargingData : public QObject {
    Q_OBJECT
    // Live charger state (CHARGER_STREAM): the fields the view shows.
    Q_PROPERTY(int status READ status NOTIFY liveStateChanged)
    Q_PROPERTY(double chargePowerW READ chargePowerW NOTIFY liveStateChanged)
    Q_PROPERTY(double gridPowerW READ gridPowerW NOTIFY liveStateChanged)
    Q_PROPERTY(double sessionEnergyKwh READ sessionEnergyKwh NOTIFY liveStateChanged)

    // Live Nord Pool spot price (SPOT_PRICE_STREAM): the VAT+margin all-in €/kWh the
    // tiles use. `hasSpotPrice` stays false until the first status=1 frame (or when spot
    // pricing is disabled backend-side).
    Q_PROPERTY(bool hasSpotPrice READ hasSpotPrice NOTIFY spotPriceChanged)
    Q_PROPERTY(double spotPriceEurPerKwh READ spotPriceEurPerKwh NOTIFY spotPriceChanged)

    // Month-to-date aggregate (CHARGING_MONTH): `valid` + the 13 fields (NaN -> "—").
    Q_PROPERTY(QVariantMap monthSummary READ monthSummary NOTIFY monthChanged)

    // Past-hour power series, each { points, minX, maxX, minY, maxY, count }, points a
    // QList<QPointF> a HistoryGraph binds as it is.
    Q_PROPERTY(QVariantMap gridSeries READ gridSeries NOTIFY gridChanged)
    Q_PROPERTY(QVariantMap chargeSeries READ chargeSeries NOTIFY chargeChanged)
    Q_PROPERTY(bool historyLoading READ historyLoading NOTIFY historyLoadingChanged)

public:
    explicit ChargingData(ServerClient *server, QObject *parent = nullptr);

    int status() const { return m_status; }
    double chargePowerW() const { return m_chargePowerW; }
    double gridPowerW() const { return m_gridPowerW; }
    double sessionEnergyKwh() const { return m_sessionEnergyKwh; }
    bool hasSpotPrice() const { return m_hasSpotPrice; }
    double spotPriceEurPerKwh() const { return m_spotPriceEurPerKwh; }
    QVariantMap monthSummary() const { return m_month; }
    QVariantMap gridSeries() const { return seriesMap(m_grid); }
    QVariantMap chargeSeries() const { return seriesMap(m_charge); }
    bool historyLoading() const { return m_historyLoading; }

    // Begin/refresh the live past-hour graphs: seed both series from history and let the
    // live stream extend them. Call when the view becomes current.
    Q_INVOKABLE void startLive();
    // Stop extending the graphs from the stream (the view is hidden). Live tile state
    // keeps updating; only the graph buffers freeze.
    Q_INVOKABLE void stopLive();
    // Ask the backend for the month-to-date aggregate (the stats grid).
    Q_INVOKABLE void requestMonth();

signals:
    void liveStateChanged();
    void spotPriceChanged();
    void monthChanged();
    void monthReady();
    void gridChanged();
    void gridReady();  // fresh grid seed -> HistoryGraph.reloadFull()
    void gridTick();   // live grid append -> HistoryGraph.advanceLive()
    void chargeChanged();
    void chargeReady();
    void chargeTick();
    void historyLoadingChanged();

private slots:
    void onPacket(quint8 type, const QByteArray &payload);
    // Re-issue a request dropped while the socket was down (sendPacket is a non-blocking
    // write that no-ops when disconnected). Fires on the connection state changing.
    void onConnectedChanged();

private:
    // One rolling past-hour series, ascending by x (epoch ms).
    struct Series {
        QList<QPointF> points;
        double minX = 0.0;
        double maxX = 1.0;
        double minY = 0.0;
        double maxY = 1.0;
    };

    void parseStream(const QByteArray &payload);
    void parseSpotPrice(const QByteArray &payload);
    void parseMonth(const QByteArray &payload);
    void parseChargerHistory(const QByteArray &payload);
    void sendHistoryRequest(const QString &id);
    void seedSeries(Series &s, const QList<QPointF> &points, qint64 nowMs);
    void appendLive(Series &s, double value, qint64 nowMs);
    void rollBounds(Series &s, qint64 nowMs);
    static QVariantMap seriesMap(const Series &s);
    void setHistoryLoading(bool loading);

    ServerClient *m_server;

    // Live charger state.
    int m_status = 0;
    double m_chargePowerW = 0.0;
    double m_gridPowerW = 0.0;
    double m_sessionEnergyKwh = 0.0;

    // Live spot price (SPOT_PRICE_STREAM).
    bool m_hasSpotPrice = false;
    double m_spotPriceEurPerKwh = 0.0;

    // Month aggregate + reconnect-retry flag.
    QVariantMap m_month;
    bool m_monthRequested = false;

    // Rolling graph series + whether the live stream is currently extending them.
    Series m_grid;
    Series m_charge;
    bool m_graphLive = false;
    bool m_historyLoading = false;

    static constexpr qint64 kWindowMs = 60LL * 60 * 1000;  // 1 h past-hour window
};

#endif  // FRONTEND_V2_CHARGINGDATA_HH
