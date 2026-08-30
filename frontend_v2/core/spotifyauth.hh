#ifndef FRONTEND_V2_SPOTIFYAUTH_HH
#define FRONTEND_V2_SPOTIFYAUTH_HH

#include <QByteArray>
#include <QJsonObject>
#include <QObject>
#include <QString>

class ServerClient;

/**
 * SpotifyAuth — drives the Options view's Spotify re-authorization from this side.
 *
 * This side does almost nothing on purpose. The BACKEND builds the authorize URL,
 * opens it in the host's real browser, catches Spotify's redirect on its own
 * loopback listener and performs the token exchange (it holds
 * SPOTIFY_CLIENT_SECRET). No authorization code, access token or refresh token
 * ever crosses this link — only "started" and "finished".
 *
 * That split is not merely tidy: RFC 8252 §8.12 says a native app MUST NOT use an
 * embedded user-agent for authorization, and Spotify enforces it — the embedded
 * WebEngineView this class used to drive could never get past the login page's
 * reCAPTCHA gate, even with WebGL and compositing both working.
 *
 * `phase` is a plain string state machine so QML can switch on it without any
 * enum registration:
 *   "idle"       nothing in progress
 *   "requesting" waiting for the backend to open the browser
 *   "consent"    the page is open in the browser; the user is logging in
 *   "done"       a grant was written
 *   "error"      see `message`
 *
 * Registered with the QML engine as the singleton `SpotifyAuth` (see main.cpp).
 */
class SpotifyAuth : public QObject {
    Q_OBJECT
    Q_PROPERTY(QString phase READ phase NOTIFY phaseChanged)
    Q_PROPERTY(QString message READ message NOTIFY phaseChanged)
    // Backend-reported grant state, refreshed on connect and after every exchange.
    Q_PROPERTY(bool authorized READ authorized NOTIFY statusChanged)
    Q_PROPERTY(QString reason READ reason NOTIFY statusChanged)
    Q_PROPERTY(QString scope READ scope NOTIFY statusChanged)
    Q_PROPERTY(QString cachePath READ cachePath NOTIFY statusChanged)
    // The backend says a NEW AUTHORIZATION is what would fix things — the grant
    // expired (Spotify's refresh tokens last 6 months), was revoked, or was never
    // stored. Deliberately not just !authorized: a config the backend cannot read
    // is also unauthorized, and re-authorizing would not help.
    Q_PROPERTY(bool needsReauth READ needsReauth NOTIFY statusChanged)
    // Whether the app-wide re-auth prompt should be on screen: needed, not
    // dismissed, and no flow already running.
    Q_PROPERTY(bool alertVisible READ alertVisible NOTIFY alertVisibleChanged)

public:
    explicit SpotifyAuth(QObject *parent = nullptr);

    QString phase() const { return m_phase; }
    QString message() const { return m_message; }
    bool authorized() const { return m_authorized; }
    QString reason() const { return m_reason; }
    QString scope() const { return m_scope; }
    QString cachePath() const { return m_cachePath; }
    bool needsReauth() const { return m_needsReauth; }
    bool alertVisible() const { return m_alertVisible; }

    void attachServer(ServerClient *client);

    // Starts a flow: asks the backend to open the consent page.
    Q_INVOKABLE void begin();
    // Closes the dialog. The backend is told nothing — its pending flow and the
    // loopback listener expire on their own, and a code is worthless either way.
    Q_INVOKABLE void cancel();
    // Hides the prompt without acting on it. It stays hidden until the grant
    // becomes valid again and then fails afresh — "ignore" has to mean ignore, or
    // a dashboard nobody can re-authorize right now becomes unusable.
    Q_INVOKABLE void dismissAlert();

signals:
    void phaseChanged();
    void statusChanged();
    void alertVisibleChanged();

private:
    void onPacket(quint8 type, const QByteArray &payload);
    void setPhase(const QString &phase, const QString &message = QString());
    // Recomputes alertVisible from needsReauth / dismissed / phase and emits only
    // on a real change, so the three inputs have one place that resolves them.
    void updateAlert();

    ServerClient *m_server = nullptr;
    QString m_phase = QStringLiteral("idle");
    QString m_message;
    QString m_reason;
    QString m_scope;
    QString m_cachePath;
    bool m_authorized = false;
    bool m_needsReauth = false;
    bool m_alertDismissed = false;
    bool m_alertVisible = false;
    // True only between begin() and the flow ending. Without it a reply that
    // lands after cancel() reopens the popup — and a SPOTIFY_AUTH_URL doing that
    // constructs a whole Chromium for a flow nobody is running any more.
    bool m_flowActive = false;
};

#endif  // FRONTEND_V2_SPOTIFYAUTH_HH
