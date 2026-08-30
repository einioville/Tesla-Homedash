#ifndef FRONTEND_V2_CONNECTIONPROBE_HH
#define FRONTEND_V2_CONNECTIONPROBE_HH

#include <QObject>
#include <QString>
#include <QTcpSocket>
#include <QTimer>

/**
 * ConnectionProbe — answers "is anything actually listening there?" for the
 * backend address settings.
 *
 * backendHost / backendPort are restart-tier: AppConfig consumes them once at
 * startup, so a typo does not surface as an error, it surfaces as a dashboard
 * that never connects — after a restart, with nothing on screen explaining why.
 * This probes the entered value BEFORE that restart.
 *
 * Deliberately separate from ServerClient: that one owns the live session and
 * reconnects forever, which is exactly what a validation check must not do. This
 * opens a socket, waits `kTimeoutMs`, reports, and closes. A successful probe is
 * aborted the instant it connects — the backend sees a connection that opens and
 * closes, and the snapshot it streams is simply discarded.
 *
 * Advisory only. The value is still saved either way: the backend may legitimately
 * not be up yet when the address is configured.
 *
 * Registered with the QML engine as the singleton `Probe` (see main.cpp).
 */
class ConnectionProbe : public QObject {
    Q_OBJECT
    // "unknown" | "checking" | "reachable" | "unreachable". A plain string rather
    // than a Q_ENUM so QML compares it without any enum-registration ceremony.
    Q_PROPERTY(QString state READ state NOTIFY stateChanged)
    // The socket's own error text on failure, empty otherwise — "Connection
    // refused" and "Host not found" are different problems and the user can act
    // on the difference.
    Q_PROPERTY(QString detail READ detail NOTIFY stateChanged)
    // What was last probed, so the view can say which address the verdict is about.
    Q_PROPERTY(QString target READ target NOTIFY stateChanged)

public:
    explicit ConnectionProbe(QObject *parent = nullptr);

    QString state() const { return m_state; }
    QString detail() const { return m_detail; }
    QString target() const { return m_target; }

    // Starts a probe, replacing any in flight. A blank host or an out-of-range
    // port reports "unreachable" without touching the network.
    Q_INVOKABLE void check(const QString &host, int port);

signals:
    void stateChanged();

private:
    void finish(const QString &state, const QString &detail);

    QTcpSocket m_socket;
    QTimer m_timeout;
    QString m_state = QStringLiteral("unknown");
    QString m_detail;
    QString m_target;
};

#endif  // FRONTEND_V2_CONNECTIONPROBE_HH
