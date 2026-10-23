#ifndef FRONTEND_V2_SYSTEMSTATUS_HH
#define FRONTEND_V2_SYSTEMSTATUS_HH

#include <QByteArray>
#include <QObject>
#include <QTimer>
#include <QVariantMap>

class ServerClient;

/**
 * SystemStatus — the data source of the Järjestelmän tila service cards.
 *
 * Pull, not push. The backend runs its service probes only when asked
 * (SYSTEM_GET_STATUS), and this object only asks while something on screen has
 * retained it — the Järjestelmän tila section, from its own visibility. A
 * settings screen nobody has opened costs nothing.
 *
 * Everything is reported as an opaque QVariantMap straight from the backend's
 * JSON, deliberately: the document is a dashboard, not a contract, and adding a
 * metric on the backend should not need a C++ change here to display it.
 *
 * Registered with the QML engine as the singleton `System` (see main.cpp).
 */
class SystemStatus : public QObject {
    Q_OBJECT
    // The last status document. Empty until the first reply arrives.
    Q_PROPERTY(QVariantMap data READ data NOTIFY dataChanged)
    // True once any reply has been received, so the panel can tell "loading"
    // from "the backend answered and there is genuinely nothing".
    Q_PROPERTY(bool loaded READ loaded NOTIFY dataChanged)
    // True while anything on screen has retained the poll; gates all polling.
    Q_PROPERTY(bool active READ active NOTIFY activeChanged)

    // The open warning/error list of one service card (SYSTEM_GET_LOG).
    Q_PROPERTY(bool logOpen READ logOpen NOTIFY logChanged)
    Q_PROPERTY(bool logLoading READ logLoading NOTIFY logChanged)
    Q_PROPERTY(QString logLabel READ logLabel NOTIFY logChanged)
    // [{t, level, logger, message, open}], newest first, so the open ones —
    // logged since the service last worked — lead.
    Q_PROPERTY(QVariantList logEntries READ logEntries NOTIFY logChanged)
    // Epoch ms where the open entries begin; null while the service is fine.
    Q_PROPERTY(QVariant logOpenSince READ logOpenSince NOTIFY logChanged)

public:
    explicit SystemStatus(QObject *parent = nullptr);

    QVariantMap data() const { return m_data; }
    bool loaded() const { return m_loaded; }
    bool active() const { return m_consumers > 0; }

    bool logOpen() const { return m_logOpen; }
    bool logLoading() const { return m_logLoading; }
    QString logLabel() const { return m_logLabel; }
    QVariantList logEntries() const { return m_logEntries; }
    QVariant logOpenSince() const { return m_logOpenSince; }

    void attachServer(ServerClient *client);

    // Polling is reference-counted rather than a flag: a screen being built and
    // one being torn down overlap (a section switch, a rebuilt Loader), and a
    // flag set by the newcomer would be cleared by the one leaving. Each
    // consumer retains while visible and releases once.
    Q_INVOKABLE void retain();
    Q_INVOKABLE void release();

    // Asks for a fresh status document now, regardless of the poll timer.
    Q_INVOKABLE void refresh();

    // Opens one card's list and fetches its entries; closeLog() dismisses it.
    Q_INVOKABLE void openLog(const QString &service, const QString &label);
    Q_INVOKABLE void closeLog();

signals:
    void dataChanged();
    void activeChanged();
    void logChanged();

private:
    void onPacket(quint8 type, const QByteArray &payload);
    void onLogPacket(const QByteArray &payload);

    QTimer m_timer;
    ServerClient *m_server = nullptr;
    QVariantMap m_data;
    bool m_loaded = false;
    int m_consumers = 0;

    bool m_logOpen = false;
    bool m_logLoading = false;
    QString m_logService;
    QString m_logLabel;
    QVariantList m_logEntries;
    QVariant m_logOpenSince;
};

#endif  // FRONTEND_V2_SYSTEMSTATUS_HH
