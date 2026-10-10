#ifndef FRONTEND_V2_LOGCONTROL_HH
#define FRONTEND_V2_LOGCONTROL_HH

#include <QByteArray>
#include <QObject>
#include <QTimer>

class ServerClient;

/**
 * LogControl — clears the app's log files (Ylläpito > Lokit).
 *
 * Each half clears its own: this side's frontend.log is local to wherever the
 * frontend runs, so it is cleared here (Logger::clearFiles), and the backend is
 * asked to clear its own files and its warning/error store (LOG_CLEAR). The two
 * results come back as ONE `finished` — the row reports a single outcome.
 * "Keep warnings and errors" keeps the WARNING+ records in both halves' files
 * and leaves the backend's error store, behind the Järjestelmän tila lists, be.
 *
 * Registered with the QML engine as the singleton `Logs` (see main.cpp).
 */
class LogControl : public QObject {
    Q_OBJECT
    // True while the backend's half is pending.
    Q_PROPERTY(bool busy READ busy NOTIFY busyChanged)

public:
    explicit LogControl(QObject *parent = nullptr);

    bool busy() const { return m_busy; }

    void attachServer(ServerClient *client);

    Q_INVOKABLE void clear(bool keepWarnings);

signals:
    void busyChanged();
    // The combined outcome, worded for the row it was started from.
    void finished(bool ok, const QString &message);

private:
    void onPacket(quint8 type, const QByteArray &payload);
    void finish(bool ok, const QString &message);

    ServerClient *m_server = nullptr;
    QTimer m_timeout;
    qint64 m_localFreed = 0;
    bool m_busy = false;
};

#endif  // FRONTEND_V2_LOGCONTROL_HH
