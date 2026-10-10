#include "idlewatcher.hh"

#include <QEvent>
#include <QGuiApplication>

#include "logger.hh"

namespace {
const Logger logger = Logger::get("idle");

// The event types that count as "the user is here". Deliberately excludes hover
// moves (a bare cursor pass shouldn't count) — a real touch/press/key/wheel does.
bool isActivityEvent(QEvent::Type type) {
    switch (type) {
        case QEvent::MouseButtonPress:
        case QEvent::MouseButtonRelease:
        case QEvent::MouseButtonDblClick:
        case QEvent::MouseMove:
        case QEvent::Wheel:
        case QEvent::TouchBegin:
        case QEvent::TouchUpdate:
        case QEvent::TouchEnd:
        case QEvent::TouchCancel:
        case QEvent::KeyPress:
        case QEvent::KeyRelease:
        case QEvent::TabletPress:
        case QEvent::TabletMove:
        case QEvent::TabletRelease:
            return true;
        default:
            return false;
    }
}
}  // namespace

IdleWatcher::IdleWatcher(int timeoutMs, QObject *parent)
    : QObject(parent), m_timeoutMs(qMax(1000, timeoutMs)) {
    m_timer.setSingleShot(true);
    m_timer.setInterval(m_timeoutMs);
    connect(&m_timer, &QTimer::timeout, this, &IdleWatcher::onTimeout);

    // Watch every event routed through the application (all input to every window).
    if (qApp != nullptr) {
        qApp->installEventFilter(this);
    }
    m_timer.start();
    logger.info(QStringLiteral("Idle watcher armed | timeout=%1 ms").arg(m_timeoutMs));
}

void IdleWatcher::setTimeoutMs(int timeoutMs) {
    const int clamped = qMax(1000, timeoutMs);
    if (clamped == m_timeoutMs) {
        return;
    }
    m_timeoutMs = clamped;
    m_timer.setInterval(m_timeoutMs);
    m_timer.start();  // apply the new timeout from now
    emit timeoutMsChanged();
    logger.info(QStringLiteral("Idle timeout set to %1 ms").arg(m_timeoutMs));
}

void IdleWatcher::poke() {
    registerActivity();
}

bool IdleWatcher::eventFilter(QObject *watched, QEvent *event) {
    if (event != nullptr && isActivityEvent(event->type())) {
        registerActivity();
    }
    // Never consume — this is a passive observer.
    return QObject::eventFilter(watched, event);
}

void IdleWatcher::registerActivity() {
    m_timer.start();  // restart the countdown
    emit activity();
    if (m_idle) {
        m_idle = false;
        emit idleChanged();
        logger.info(QStringLiteral("Activity detected — leaving idle"));
    }
}

void IdleWatcher::onTimeout() {
    if (!m_idle) {
        m_idle = true;
        emit idleChanged();
        logger.info(QStringLiteral("Inactivity timeout reached — entering idle"));
    }
}
