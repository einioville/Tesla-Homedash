#include "connectionprobe.hh"

#include "logger.hh"

namespace {
const Logger logger = Logger::get("probe");

// Long enough for a busy Pi on wifi, short enough that the row does not sit on
// "checking" while the user waits for an answer.
constexpr int kTimeoutMs = 3000;
}  // namespace

ConnectionProbe::ConnectionProbe(QObject *parent) : QObject(parent) {
    m_timeout.setSingleShot(true);
    m_timeout.setInterval(kTimeoutMs);

    connect(&m_socket, &QTcpSocket::connected, this, [this]() {
        // Reachable. Drop the connection immediately — this is a check, not a
        // session; ServerClient owns the real one.
        m_socket.abort();
        finish(QStringLiteral("reachable"), QString());
    });
    connect(&m_socket, &QTcpSocket::errorOccurred, this, [this](QAbstractSocket::SocketError) {
        const QString reason = m_socket.errorString();
        m_socket.abort();
        finish(QStringLiteral("unreachable"), reason);
    });
    connect(&m_timeout, &QTimer::timeout, this, [this]() {
        m_socket.abort();
        finish(QStringLiteral("unreachable"), QStringLiteral("Aikakatkaisu"));
    });
}

void ConnectionProbe::check(const QString &host, int port) {
    const QString trimmed = host.trimmed();
    m_target = QStringLiteral("%1:%2").arg(trimmed).arg(port);

    // Abort whatever was in flight: the address changed under it, so its verdict
    // would be about the wrong target.
    m_timeout.stop();
    m_socket.abort();

    if (trimmed.isEmpty() || port < 1 || port > 65535) {
        finish(QStringLiteral("unreachable"), QStringLiteral("Virheellinen osoite"));
        return;
    }

    m_state = QStringLiteral("checking");
    m_detail.clear();
    emit stateChanged();

    m_socket.connectToHost(trimmed, static_cast<quint16>(port));
    m_timeout.start();
}

void ConnectionProbe::finish(const QString &state, const QString &detail) {
    m_timeout.stop();
    // No "unchanged" early-out: `target` is notified by this same signal, so two
    // identical verdicts about DIFFERENT addresses must still refresh the view.
    m_state = state;
    m_detail = detail;
    emit stateChanged();
    logger.info(QStringLiteral("Probe %1 → %2%3")
                    .arg(m_target, state,
                         detail.isEmpty() ? QString() : QStringLiteral(" (%1)").arg(detail)));
}
