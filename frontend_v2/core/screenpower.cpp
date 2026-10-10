#include "screenpower.hh"

#include "logger.hh"
#include "protocol.hh"
#include "serverclient.hh"

namespace {
const Logger logger = Logger::get("display");

// Never let the panel sleep faster than this, whatever the setting says.
constexpr int kMinTimeoutMs = 30 * 1000;

// Spacing between activity-driven wake requests while the panel is reported off.
// A wake that works is answered in milliseconds and ends the retries, so this
// only ever bites while waking keeps failing.
constexpr int kWakeRetryMs = 2000;
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
    if (m_off && (!m_lastWake.isValid() || m_lastWake.hasExpired(kWakeRetryMs))) {
        // The tap that wakes the panel is NOT swallowed — this is a passive
        // observer, like IdleWatcher. In the normal setup the screensaver overlay
        // is already up and consumes it as its dismiss tap; with the screensaver
        // off, the tap also lands on whatever is under the finger.
        m_lastWake.start();
        request(false);
    }
    if (m_enabled) {
        m_timer.start(m_timeoutMs);
    }
}

void ScreenPower::wake() {
    // Deliberate, so not subject to the activity throttle.
    if (m_off) {
        request(false);
    }
    if (m_enabled) {
        m_timer.start(m_timeoutMs);
    }
}

void ScreenPower::onTimeout() {
    if (!m_enabled || m_off) {
        return;
    }
    // The backend refuses this anyway once an output has been lost; skipping it
    // here just saves the round trip every timeout.
    if (m_fault == protocol::DISPLAY_FAULT_OUTPUT_LOST) {
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
    // The wire byte is `on` (1 = lit), the opposite sense of m_off. Read as `off`
    // it left a lit panel looking dark forever, and onActivity() then sent a
    // wake request on every single input event (#44).
    const bool off = payload.at(1) == 0;
    // Optional: a backend from before the fault byte sends two bytes.
    const int fault = payload.size() >= 3 ? static_cast<quint8>(payload.at(2))
                                          : protocol::DISPLAY_FAULT_NONE;
    if (available == m_available && off == m_off && fault == m_fault) {
        return;
    }
    if (available != m_available) {
        logger.info(available ? QStringLiteral("Display power control available")
                              : QStringLiteral("Display power control unavailable on the host"));
    }
    if (fault != m_fault && fault != protocol::DISPLAY_FAULT_NONE) {
        logger.warning(QStringLiteral("Display power fault reported by the backend: %1")
                           .arg(fault == protocol::DISPLAY_FAULT_OUTPUT_LOST
                                    ? QStringLiteral("output lost after wake")
                                    : QStringLiteral("power change refused")));
    }
    m_available = available;
    m_off = off;
    m_fault = fault;
    emit stateChanged();
}
