#ifndef FRONTEND_V2_TESLAHISTORY_HH
#define FRONTEND_V2_TESLAHISTORY_HH

#include <QByteArray>
#include <QObject>
#include <QString>
#include <QVariantList>

class ServerClient;
class TeslaData;
class QDataStream;
class QIODevice;
class QTimer;

/**
 * TeslaHistory — the History-view datahandler, exposed to QML as the `History`
 * singleton. Unlike the push/subscribe handlers (Tesla/Weather/Media), this one
 * is request/response: requestProperties() / requestHistory() send a request and
 * the backend replies to this client only.
 *
 *  - `properties` lists the graphable properties for the dropdown.
 *  - `points` is the current series as a JS array of points (x = epoch ms as a
 *    double, y = value), fed straight into a Qt Graphs LineSeries via replace().
 *  - `minX/maxX/minY/maxY` bound the data so the QML axes can auto-fit.
 *
 * A history reply echoes its property id; a reply whose id no longer matches the
 * one last requested is discarded, so quickly switching property/range can't draw
 * a stale series. Parsing runs on the GUI thread (the bound properties are not
 * thread-safe); malformed/truncated frames are dropped.
 */
class TeslaHistory : public QObject {
    Q_OBJECT
    Q_PROPERTY(QVariantList properties READ properties NOTIFY propertiesChanged)
    Q_PROPERTY(QVariantList points READ points NOTIFY historyChanged)
    Q_PROPERTY(QString currentPropertyId READ currentPropertyId NOTIFY historyChanged)
    Q_PROPERTY(int pointCount READ pointCount NOTIFY historyChanged)
    Q_PROPERTY(double minX READ minX NOTIFY historyChanged)
    Q_PROPERTY(double maxX READ maxX NOTIFY historyChanged)
    Q_PROPERTY(double minY READ minY NOTIFY historyChanged)
    Q_PROPERTY(double maxY READ maxY NOTIFY historyChanged)
    Q_PROPERTY(bool loading READ loading NOTIFY loadingChanged)

public:
    explicit TeslaHistory(ServerClient *server, TeslaData *tesla,
                          QObject *parent = nullptr);

    QVariantList properties() const { return m_properties; }
    QVariantList points() const { return m_points; }
    QString currentPropertyId() const { return m_currentId; }
    int pointCount() const { return static_cast<int>(m_points.size()); }
    double minX() const { return m_minX; }
    double maxX() const { return m_maxX; }
    double minY() const { return m_minY; }
    double maxY() const { return m_maxY; }
    bool loading() const { return m_loading; }

    // Ask the backend for the graphable-property list. Cheap; call each time the
    // view is shown so lazily-typed properties fill in as the session runs.
    Q_INVOKABLE void requestProperties();
    // Ask the backend for one property's history. rangeCode is a HISTORY_RANGE_*
    // value; startMs/endMs are epoch ms used only for the custom range.
    Q_INVOKABLE void requestHistory(const QString &id, int rangeCode,
                                    double startMs, double endMs);

    // Live mode: seed the rolling window from history, then advance it every
    // second from live telemetry (read off the Tesla singleton by property id).
    // startLive takes a preset rangeCode for the window size; stopLive returns to
    // static; pauseLive halts the timer while the view is hidden (call startLive
    // again on re-show to re-seed and resume).
    Q_INVOKABLE void startLive(const QString &id, int rangeCode);
    Q_INVOKABLE void stopLive();
    Q_INVOKABLE void pauseLive();

signals:
    void propertiesChanged();
    void historyChanged();
    void historyReady();  // fired after a matching history reply is applied
    void liveTick();      // fired after the live window advances (no view reset)
    void loadingChanged();

private slots:
    void onPacket(quint8 type, const QByteArray &payload);
    void onLiveTick();

private:
    void setLoading(bool loading);
    void parseProperties(const QByteArray &payload);
    void parseHistory(const QByteArray &payload);
    static bool readString(QDataStream &stream, QIODevice *device, QString &out);

    // Live helpers.
    static QString qmlNameForId(const QString &id);  // id -> Tesla Q_PROPERTY name
    static qint64 windowMsForRange(int rangeCode);   // preset -> window width (ms)
    static int liveTickIntervalForRange(int rangeCode);  // preset -> live tick period (ms)
    void recomputeBounds(qint64 nowMs);              // roll window + recompute min/max

    ServerClient *m_server;
    TeslaData *m_tesla;
    QVariantList m_properties;
    QVariantList m_points;
    QString m_currentId;  // property id the user is currently viewing
    double m_minX = 0.0;
    double m_maxX = 0.0;
    double m_minY = 0.0;
    double m_maxY = 0.0;
    bool m_loading = false;

    // Live-mode state.
    QTimer *m_liveTimer = nullptr;
    bool m_live = false;         // live mode active
    bool m_livePending = false;  // waiting for the seed reply to start the timer
    QString m_liveId;            // property streamed in live mode
    int m_liveRangeCode = 0;     // preset code (drives the window size)
    qint64 m_liveWindowMs = 0;   // rolling-window width in ms
};

#endif  // FRONTEND_V2_TESLAHISTORY_HH
