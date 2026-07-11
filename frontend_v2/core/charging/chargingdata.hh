#ifndef FRONTEND_V2_CHARGINGDATA_HH
#define FRONTEND_V2_CHARGINGDATA_HH

#include <QByteArray>
#include <QObject>
#include <QVariantList>
#include <QVariantMap>

class ServerClient;

/**
 * ChargingData — the Charging-view datahandler, exposed to QML as the `Charging`
 * singleton. It combines three flows over the one socket:
 *
 *  - Live charger state: parses the CHARGER_STREAM broadcast (myenergi) into the scalar
 *    tile properties (status/plug/mode/powers/energy/voltage/frequency/phase) plus the
 *    full raw Zappi payload (`raw`). Updated on every frame regardless of view state.
 *  - Past-hour power graphs: startLive() seeds two rolling 1 h series (grid power +
 *    charge power) from CHARGER_HISTORY, then extends each from the live stream — every
 *    series drives a HistoryGraph via a ready (reload) + tick (advance) signal, the same
 *    contract TeslaHistory's live mode uses, but sourced from the stream instead of a
 *    polled value. stopLive() freezes the graph buffers while the view is hidden.
 *  - Month-to-date stats: requestMonth() -> CHARGING_MONTH -> the `monthSummary` map.
 *
 * Parsing runs on the GUI thread (the bound properties are not thread-safe); malformed/
 * truncated frames are dropped. A charger-history reply is routed to its series by the
 * echoed id; a request dropped while the socket was down is re-issued on reconnect
 * (mirroring TripsData / TeslaHistory).
 */
class ChargingData : public QObject {
    Q_OBJECT
    // Live charger state (CHARGER_STREAM).
    Q_PROPERTY(bool hasLiveState READ hasLiveState NOTIFY liveStateChanged)
    Q_PROPERTY(int status READ status NOTIFY liveStateChanged)
    Q_PROPERTY(int plugStatus READ plugStatus NOTIFY liveStateChanged)
    Q_PROPERTY(int mode READ mode NOTIFY liveStateChanged)
    Q_PROPERTY(double chargePowerW READ chargePowerW NOTIFY liveStateChanged)
    Q_PROPERTY(double gridPowerW READ gridPowerW NOTIFY liveStateChanged)
    Q_PROPERTY(double generatedPowerW READ generatedPowerW NOTIFY liveStateChanged)
    Q_PROPERTY(double sessionEnergyKwh READ sessionEnergyKwh NOTIFY liveStateChanged)
    Q_PROPERTY(double supplyVoltage READ supplyVoltage NOTIFY liveStateChanged)
    Q_PROPERTY(double supplyFrequency READ supplyFrequency NOTIFY liveStateChanged)
    Q_PROPERTY(int l1Phase READ l1Phase NOTIFY liveStateChanged)
    Q_PROPERTY(QVariantMap raw READ raw NOTIFY liveStateChanged)

    // Live Nord Pool spot price (SPOT_PRICE_STREAM). `hasSpotPrice` stays false until the
    // first status=1 frame (or when spot pricing is disabled backend-side). price is the
    // VAT+margin all-in €/kWh the tiles use; rawPrice is the wholesale €/kWh; hourStartMs
    // is the UTC start of the priced hour.
    Q_PROPERTY(bool hasSpotPrice READ hasSpotPrice NOTIFY spotPriceChanged)
    Q_PROPERTY(double spotPriceEurPerKwh READ spotPriceEurPerKwh NOTIFY spotPriceChanged)
    Q_PROPERTY(double spotRawEurPerKwh READ spotRawEurPerKwh NOTIFY spotPriceChanged)
    Q_PROPERTY(double spotHourStartMs READ spotHourStartMs NOTIFY spotPriceChanged)

    // Month-to-date aggregate (CHARGING_MONTH): `valid` + the 12 fields (NaN -> "—").
    Q_PROPERTY(QVariantMap monthSummary READ monthSummary NOTIFY monthChanged)
    Q_PROPERTY(bool monthLoading READ monthLoading NOTIFY monthLoadingChanged)

    // Past-hour power series, each { points: [{x,y}], minX, maxX, minY, maxY, count }.
    Q_PROPERTY(QVariantMap gridSeries READ gridSeries NOTIFY gridChanged)
    Q_PROPERTY(QVariantMap chargeSeries READ chargeSeries NOTIFY chargeChanged)
    Q_PROPERTY(bool historyLoading READ historyLoading NOTIFY historyLoadingChanged)

public:
    explicit ChargingData(ServerClient *server, QObject *parent = nullptr);

    bool hasLiveState() const { return m_hasLiveState; }
    int status() const { return m_status; }
    int plugStatus() const { return m_plugStatus; }
    int mode() const { return m_mode; }
    double chargePowerW() const { return m_chargePowerW; }
    double gridPowerW() const { return m_gridPowerW; }
    double generatedPowerW() const { return m_generatedPowerW; }
    double sessionEnergyKwh() const { return m_sessionEnergyKwh; }
    double supplyVoltage() const { return m_supplyVoltage; }
    double supplyFrequency() const { return m_supplyFrequency; }
    int l1Phase() const { return m_l1Phase; }
    QVariantMap raw() const { return m_raw; }
    bool hasSpotPrice() const { return m_hasSpotPrice; }
    double spotPriceEurPerKwh() const { return m_spotPriceEurPerKwh; }
    double spotRawEurPerKwh() const { return m_spotRawEurPerKwh; }
    double spotHourStartMs() const { return m_spotHourStartMs; }
    QVariantMap monthSummary() const { return m_month; }
    bool monthLoading() const { return m_monthLoading; }
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
    void monthLoadingChanged();
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
    // One rolling past-hour series. points is a QPointF list ascending by x (epoch ms),
    // fed straight into a HistoryGraph.
    struct Series {
        QVariantList points;
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
    void seedSeries(Series &s, const QVariantList &points, qint64 nowMs);
    void appendLive(Series &s, double value, qint64 nowMs);
    void rollBounds(Series &s, qint64 nowMs);
    static QVariantMap seriesMap(const Series &s);
    void setMonthLoading(bool loading);
    void setHistoryLoading(bool loading);

    ServerClient *m_server;

    // Live charger state.
    bool m_hasLiveState = false;
    int m_status = 0;
    int m_plugStatus = 0;
    int m_mode = 0;
    double m_chargePowerW = 0.0;
    double m_gridPowerW = 0.0;
    double m_generatedPowerW = 0.0;
    double m_sessionEnergyKwh = 0.0;
    double m_supplyVoltage = 0.0;
    double m_supplyFrequency = 0.0;
    int m_l1Phase = 0;
    QVariantMap m_raw;

    // Live spot price (SPOT_PRICE_STREAM).
    bool m_hasSpotPrice = false;
    double m_spotPriceEurPerKwh = 0.0;
    double m_spotRawEurPerKwh = 0.0;
    double m_spotHourStartMs = 0.0;

    // Month aggregate + reconnect-retry flag.
    QVariantMap m_month;
    bool m_monthLoading = false;
    bool m_monthRequested = false;

    // Rolling graph series + whether the live stream is currently extending them.
    Series m_grid;
    Series m_charge;
    bool m_graphLive = false;
    bool m_historyLoading = false;

    static constexpr qint64 kWindowMs = 60LL * 60 * 1000;  // 1 h past-hour window
};

#endif  // FRONTEND_V2_CHARGINGDATA_HH
