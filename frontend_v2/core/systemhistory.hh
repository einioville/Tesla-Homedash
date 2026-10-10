#ifndef FRONTEND_V2_SYSTEMHISTORY_HH
#define FRONTEND_V2_SYSTEMHISTORY_HH

#include <QByteArray>
#include <QList>
#include <QObject>
#include <QTimer>
#include <QVariantMap>

class ServerClient;

/**
 * SystemHistory — the Järjestelmän tila graphs' data source.
 *
 * The backend samples the host every couple of seconds into a ten-minute ring
 * buffer whether or not anyone is looking (backend/src/system_service/
 * system_history.py); this object fetches from it only while `active`, which the
 * graphs set from their own visibility. Fetches are incremental — each asks for
 * what is newer than the last sample held — so after the first one a poll moves a
 * sample or two, and returning to the section only fetches what was missed.
 *
 * The samples are kept here as rows and handed to QML as COLUMNS (`series`), one
 * array per metric, because that is what a polyline is built from. A value the
 * backend could not compute arrives as NaN, which the graph draws as a gap.
 *
 * Registered with the QML engine as the singleton `SystemHistory` (see main.cpp).
 */
class SystemHistory : public QObject {
    Q_OBJECT
    // { t: [epoch ms], cpu: [[pct] per core], memUsed: [B], diskRead, diskWrite,
    //   netRx, netTx: [B/s], cpuTemp: [°C] } — every array the same length,
    //   oldest first.
    Q_PROPERTY(QVariantMap series READ series NOTIFY historyChanged)
    // What changes too rarely to be a column: interval_s, window_s, mem_total_b,
    // cpu_count, temp_available and disk {path, device, total_b, used_b, free_b,
    // used_pct}.
    Q_PROPERTY(QVariantMap info READ info NOTIFY historyChanged)
    // True once any reply has been received.
    Q_PROPERTY(bool loaded READ loaded NOTIFY historyChanged)
    // True while anything on screen has retained the poll; gates all polling.
    Q_PROPERTY(bool active READ active NOTIFY activeChanged)

public:
    explicit SystemHistory(QObject *parent = nullptr);

    QVariantMap series() const { return m_series; }
    QVariantMap info() const { return m_info; }
    bool loaded() const { return m_loaded; }
    bool active() const { return m_consumers > 0; }

    void attachServer(ServerClient *client);

    // Reference-counted like System's, for the same reason: a screen being
    // built and one being torn down overlap.
    Q_INVOKABLE void retain();
    Q_INVOKABLE void release();

    // Asks for the samples newer than the last one held, now.
    Q_INVOKABLE void refresh();

signals:
    void historyChanged();
    void activeChanged();

private:
    struct Sample {
        qint64 t = 0;
        QList<double> cpu;
        double memUsed = 0;
        double diskRead = 0;
        double diskWrite = 0;
        double netRx = 0;
        double netTx = 0;
        double cpuTemp = 0;
    };

    void onPacket(quint8 type, const QByteArray &payload);
    void rebuildSeries();

    QTimer m_timer;
    ServerClient *m_server = nullptr;
    QList<Sample> m_samples;
    QVariantMap m_series;
    QVariantMap m_info;
    bool m_loaded = false;
    int m_consumers = 0;
};

#endif  // FRONTEND_V2_SYSTEMHISTORY_HH
