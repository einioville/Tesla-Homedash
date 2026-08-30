#include "screenpower.hh"

#include "logger.hh"
#include "protocol.hh"
#include "serverclient.hh"

namespace {
const Logger logger = Logger::get("display");

// Never let the panel sleep faster than this, whatever the setting says.
constexpr int kMinTimeoutMs = 30 * 1000;
}  // namespace

ScreenPower::ScreenPower(QObject *parent) : QObject(parent) {
    m_timer.setSingleShot(true);
    m_timer.setInterval(m_timeoutMs);
    connect(&m_timer, &QTimer::timeout, this, &ScreenPower::onTimeout);
}

void ScreenPower::attachServer(ServerClient *client) {
    m_server = client;
    connect(client, &ServerClient::packetReceived, this, &ScreenPower::onPacket);
    // The backend snapshots DISPLAY_POWER_STATE to every new client, so there is
    // nothing to request on connect — `available` simply arrives.
}

void ScreenPower::setEnabled(bool enabled) {
    if (enabled == m_enabled) {
        return;
    }
    m_enabled = enabled;
    emit enabledChanged();
    if (m_enabled) {
        m_timer.start(m_timeoutMs);
        logger.info(QStringLiteral("Display power-off armed | timeout=%1 min")
                        .arg(m_timeoutMs / 60000));
    } else {
        m_timer.stop();
        // Turning the feature off with the panel dark would strand it.
        request(false);
        logger.info(QStringLiteral("Display power-off disabled"));
    }
}

void ScreenPower::setTimeoutMs(int timeoutMs) {
    const int clamped = qMax(kMinTimeoutMs, timeoutMs);
    if (clamped == m_timeoutMs) {
        return;
    }
    m_timeoutMs = clamped;
    emit timeoutMsChanged();
    if (m_enabled) {
        m_timer.start(m_timeoutMs);  // apply from now
    }
    logger.info(QStringLiteral("Display power-off timeout set to %1 min").arg(m_timeoutMs / 60000));
}

void ScreenPower::onActivity() {
    if (m_off) {
        // The tap that wakes the panel is NOT swallowed — this is a passive
        // observer, like IdleWatcher. In the normal setup the screensaver overlay
        // is already up and consumes it as its dismiss tap; with the screensaver
        // off, the tap also lands on whatever is under the finger.
        request(false);
    }
    if (m_enabled) {
        m_timer.start(m_timeoutMs);
    }
}

void ScreenPower::wake() {
    onActivity();
}

void ScreenPower::onTimeout() {
    if (!m_enabled || m_off) {
        return;
    }
    request(true);
}

void ScreenPower::request(bool off) {
    // `available` is the backend's answer about the HOST, so a host without wlopm
    // never gets a request at all. Nothing is assumed about the outcome either:
    // m_off changes only when DISPLAY_POWER_STATE says it did.
    if (!m_available || m_server == nullptr || !m_server->connected()) {
        return;
    }
    QByteArray payload(1, static_cast<char>(off ? 0 : 1));
    m_server->sendPacket(protocol::frame(protocol::DISPLAY_SET_POWER, payload));
    logger.info(QStringLiteral("Requested display %1")
                    .arg(off ? QStringLiteral("off") : QStringLiteral("on")));
}

void ScreenPower::onPacket(quint8 type, const QByteArray &payload) {
    if (type != protocol::DISPLAY_POWER_STATE) {
        return;
    }
    if (payload.size() < 2) {
        logger.warning(QStringLiteral("DISPLAY_POWER_STATE: payload too short (%1 bytes)")
                           .arg(payload.size()));
        return;
    }
    const bool available = payload.at(0) != 0;
    const bool off = payload.at(1) != 0;
    if (available == m_available && off == m_off) {
        return;
    }
    if (available != m_available) {
        logger.info(available ? QStringLiteral("Display power control available")
                              : QStringLiteral("Display power control unavailable on the host"));
    }
    m_available = available;
    m_off = off;
    emit stateChanged();
}
