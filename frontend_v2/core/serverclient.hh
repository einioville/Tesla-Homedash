#ifndef FRONTEND_V2_SERVERCLIENT_HH
#define FRONTEND_V2_SERVERCLIENT_HH

#include <QAbstractSocket>
#include <QByteArray>
#include <QObject>
#include <QString>
#include <QTcpSocket>
#include <QTimer>

/**
 * ServerClient — owns the single QTcpSocket to the backend and is the only
 * ingress/egress point for the binary protocol (port 6969).
 *
 * Inbound: reassembles framed packets ([4B big-endian length][1B type][payload])
 * out of the TCP byte stream and emits ONE packetReceived(type, payload) signal;
 * the per-domain data models and singletons connect to it and filter by type. It
 * is protocol-agnostic by design — it never interprets payloads.
 *
 * Outbound: sendPacket() writes a pre-framed packet (build with protocol::frame)
 * non-blocking.
 *
 * Reconnects every 10 s on disconnect/error and exposes a bindable connection
 * state (connected / stateText) to QML.
 *
 * Registered as the QML singleton `Server`. main.cpp constructs it and every
 * listener before calling start(), so none misses the backend's on-connect
 * snapshot burst.
 */
class ServerClient : public QObject {
    Q_OBJECT
    Q_PROPERTY(bool connected READ connected NOTIFY connectedChanged)
    Q_PROPERTY(QString stateText READ stateText NOTIFY stateTextChanged)
    // This end of the socket as the backend sees it — how the status view's
    // client list tells this display from the others. Empty / 0 while down.
    Q_PROPERTY(QString localAddress READ localAddress NOTIFY connectedChanged)
    Q_PROPERTY(int localPort READ localPort NOTIFY connectedChanged)

public:
    enum class State { Disconnected, Connecting, Connected, Reconnecting };
    Q_ENUM(State)

    explicit ServerClient(QString host, quint16 port, QObject *parent = nullptr);

    bool connected() const { return m_state == State::Connected; }
    QString stateText() const;
    QString localAddress() const {
        return connected() ? m_socket->localAddress().toString() : QString();
    }
    int localPort() const { return connected() ? m_socket->localPort() : 0; }

    // Begins connecting and arms the reconnect loop. Call once after construction.
    void start();

    // Writes an already-framed packet (build it with protocol::frame). Non-blocking.
    void sendPacket(const QByteArray &framed);

signals:
    // The single demux point. `type` is the message-type byte; `payload` is the
    // frame with its length prefix and type byte already stripped.
    void packetReceived(quint8 type, const QByteArray &payload);

    void connectedChanged();
    void stateTextChanged();

private slots:
    void onConnect();
    void onDisconnect();
    void onReadyRead();
    void onError(QAbstractSocket::SocketError error);

private:
    void connectToServer();
    void setState(State state);

    QTcpSocket *m_socket;
    QByteArray m_buffer;
    QString m_host;
    quint16 m_port;
    QTimer *m_reconnectTimer;
    State m_state = State::Disconnected;
};

#endif  // FRONTEND_V2_SERVERCLIENT_HH
