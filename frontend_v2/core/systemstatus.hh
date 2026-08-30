#ifndef FRONTEND_V2_SYSTEMSTATUS_HH
#define FRONTEND_V2_SYSTEMSTATUS_HH

#include <QByteArray>
#include <QObject>
#include <QTimer>
#include <QVariantMap>

class ServerClient;

/**
 * SystemStatus — the maintenance dashboard's data source.
 *
 * Pull, not push. The backend samples /proc only when asked (SYSTEM_GET_STATUS),
 * and this object only asks while `active` is true — which the status panel sets
 * from its own visibility. A settings screen nobody has opened costs nothing.
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
    // Set by the panel while it is on screen; gates all polling.
    Q_PROPERTY(bool active READ active WRITE setActive NOTIFY activeChanged)

public:
    explicit SystemStatus(QObject *parent = nullptr);

    QVariantMap data() const { return m_data; }
    bool loaded() const { return m_loaded; }
    bool active() const { return m_active; }
    void setActive(bool active);

    void attachServer(ServerClient *client);

    // Asks for a fresh sample now, regardless of the poll timer.
    Q_INVOKABLE void refresh();

signals:
    void dataChanged();
    void activeChanged();

private:
    void onPacket(quint8 type, const QByteArray &payload);

    QTimer m_timer;
    ServerClient *m_server = nullptr;
    QVariantMap m_data;
    bool m_loaded = false;
    bool m_active = false;
};

#endif  // FRONTEND_V2_SYSTEMSTATUS_HH
