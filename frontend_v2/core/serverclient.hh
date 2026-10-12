#ifndef FRONTEND_V2_SERVERCLIENT_HH
#define FRONTEND_V2_SERVERCLIENT_HH

#include <QAbstractSocket>
#include <QByteArray>
#include <QFutureWatcher>
#include <QObject>
#include <QSslSocket>
#include <QString>
#include <QTimer>

#include <optional>

#include "credentialstore.hh"
#include "scram.hh"

/**
 * ServerClient — owns the single TLS socket to the backend and is the only
 * ingress/egress point for the binary protocol (port 6969).
 *
 * Login first (issue #64): after the TLS handshake the backend sends AUTH_HELLO,
 * and this side answers with the token it remembers for this backend
 * (CredentialStore) or, once the user has typed the password, a SCRAM exchange
 * that ends with a new token. Every frame of that exchange is handled here;
 * nothing is emitted and `connected` stays false until the backend accepts, so
 * the data models never see a session that is not logged in. A remembered
 * certificate that no longer matches is never trusted silently: the password is
 * asked for again, and the SCRAM exchange proves the new certificate.
 *
 * Inbound: reassembles framed packets ([4B big-endian length][1B type][payload])
 * out of the TLS byte stream and emits ONE packetReceived(type, payload) signal;
 * the per-domain data models and singletons connect to it and filter by type. It
 * is protocol-agnostic by design — it never interprets payloads.
 *
 * Outbound: sendPacket() writes a pre-framed packet (build with protocol::frame)
 * non-blocking.
 *
 * Reconnects every 10 s on disconnect/error — except while a password is needed,
 * when it waits for login() — and exposes a bindable connection state
 * (connected / stateText) and login state (authState …) to QML.
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
    // "offline", "authenticating", "loginRequired", "noPassword" or
    // "authenticated" — a string so QML switches on it with no enum registration.
    Q_PROPERTY(QString authState READ authState NOTIFY authChanged)
    // Why the last login did not go through, in Finnish; "" when there is nothing to say.
    Q_PROPERTY(QString authMessage READ authMessage NOTIFY authChanged)
    // A password login is in flight (connecting, deriving the key, waiting for the answer).
    Q_PROPERTY(bool loginBusy READ loginBusy NOTIFY authChanged)
    Q_PROPERTY(bool loginPromptVisible READ loginPromptVisible NOTIFY authChanged)
    // The id the backend gave this display at login — how the Näytöt card marks
    // this display. Empty before the first login.
    Q_PROPERTY(QString deviceId READ deviceId NOTIFY authChanged)
    Q_PROPERTY(QString endpoint READ endpoint CONSTANT)

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

    QString authState() const;
    QString authMessage() const { return m_authMessage; }
    bool loginBusy() const { return m_loginInFlight; }
    bool loginPromptVisible() const;
    QString deviceId() const;
    QString endpoint() const { return m_endpoint; }

    // Begins connecting and arms the reconnect loop. Call once after construction.
    void start();

    // Writes an already-framed packet (build it with protocol::frame). Non-blocking.
    void sendPacket(const QByteArray &framed);

    // Logs in with the password: connects if needed and runs the SCRAM exchange.
    // The password is held only until the key is derived.
    Q_INVOKABLE void login(const QString &password);
    // The login prompt's ✕ and the Options view's Kirjaudu row.
    Q_INVOKABLE void dismissLoginPrompt();
    Q_INVOKABLE void showLoginPrompt();

signals:
    // The single demux point. `type` is the message-type byte; `payload` is the
    // frame with its length prefix and type byte already stripped.
    void packetReceived(quint8 type, const QByteArray &payload);

    void connectedChanged();
    void stateTextChanged();
    void authChanged();

private slots:
    void onEncrypted();
    void onDisconnect();
    void onReadyRead();
    void onError(QAbstractSocket::SocketError error);

private:
    // Where the login stands on the current connection.
    enum class Phase { Hello, Challenge, Deriving, Result, Session };
    enum class Auth { Offline, Authenticating, LoginRequired, NoPassword, Authenticated };

    void connectToServer();
    // A connection ended (onDisconnect / onError, either or both): reconnect, or
    // wait for login() when a password is needed.
    void connectionLost();
    void setState(State state);
    void setAuth(Auth auth, const QString &message = QString());
    void handleLoginPacket(quint8 type, const QByteArray &payload);
    void onHello(bool passwordSet);
    void startPasswordLogin();
    void onChallenge(const QByteArray &serverFirst);
    void onProofReady();
    void onResult(const QJsonObject &result);
    // Ends the connection because a password is needed; waits for login().
    void requireLogin(const QString &message);
    void sendJson(quint8 type, const QJsonObject &body);

    QSslSocket *m_socket;
    QByteArray m_buffer;
    QString m_host;
    quint16 m_port;
    QString m_endpoint;
    QTimer *m_reconnectTimer;
    State m_state = State::Disconnected;

    CredentialStore m_credentials;
    Phase m_phase = Phase::Hello;
    Auth m_auth = Auth::Offline;
    QString m_authMessage;
    bool m_promptDismissed = false;
    // The SHA-256 of the certificate on this connection: the pin, and SCRAM's
    // channel binding.
    QByteArray m_peerSha256;
    // From login() until the backend answers the proof (or the attempt fails).
    bool m_loginInFlight = false;
    // Set by login(), cleared as soon as the key is derived or the attempt ends.
    QString m_password;
    scram::ClientStart m_scramStart;
    QByteArray m_expectedServerFinal;
    QFutureWatcher<std::optional<scram::ClientFinal>> *m_proofWatcher;
};

#endif  // FRONTEND_V2_SERVERCLIENT_HH
