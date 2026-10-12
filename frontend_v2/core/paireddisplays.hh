#ifndef FRONTEND_V2_PAIREDDISPLAYS_HH
#define FRONTEND_V2_PAIREDDISPLAYS_HH

#include <QObject>
#include <QString>
#include <QVariantList>

class ServerClient;

/**
 * PairedDisplays — the Ylläpito › Näytöt card's list (issue #64): every display
 * that has logged in to the backend, and revoking one.
 *
 * Holds no copy it edits, like TeslaFields: revoke() sends AUTH_REVOKE and the
 * list re-renders from the AUTH_DISPLAYS the backend broadcasts after any
 * change — a login, a revoke, a display connecting or leaving. Revoking this
 * display itself is allowed; the backend then closes the connection and the
 * login prompt comes up.
 *
 * Registered with the QML engine as the singleton `PairedDisplays` (main.cpp),
 * rendered by items/settings/PairedDisplaysPanel.qml.
 */
class PairedDisplays : public QObject {
    Q_OBJECT
    // One map per display: {id, name, address, created, lastSeen (epoch ms), connected}.
    Q_PROPERTY(QVariantList displays READ displays NOTIFY displaysChanged)
    Q_PROPERTY(bool loaded READ loaded NOTIFY displaysChanged)

public:
    explicit PairedDisplays(QObject *parent = nullptr);

    QVariantList displays() const { return m_displays; }
    bool loaded() const { return m_loaded; }

    // Wires the AUTH_DISPLAYS traffic once the socket exists (main.cpp).
    void attachServer(ServerClient *client);

    // Asks for the list. Called by the card when it is built; a reconnect while
    // it has been asked for once re-requests it.
    Q_INVOKABLE void refresh();
    Q_INVOKABLE void revoke(const QString &id);

signals:
    void displaysChanged();

private:
    void onPacket(quint8 type, const QByteArray &payload);

    ServerClient *m_server = nullptr;
    QVariantList m_displays;
    bool m_loaded = false;
    bool m_wanted = false;
};

#endif  // FRONTEND_V2_PAIREDDISPLAYS_HH
