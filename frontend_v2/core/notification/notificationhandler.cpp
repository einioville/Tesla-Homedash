#include "notificationhandler.hh"

#include "../serverclient.hh"
#include "../tesla/tesladata.hh"

#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonParseError>
#include <QLoggingCategory>
#include <QMetaMethod>
#include <QMetaProperty>
#include <QRegularExpression>
#include <QRegularExpressionMatchIterator>

namespace {
Q_LOGGING_CATEGORY(lcNotify, "frontend_v2.notifications")
}

NotificationHandler::NotificationHandler(TeslaData *tesla, ServerClient *server, QObject *parent)
    : QObject(parent), m_tesla(tesla), m_server(server) {
    loadConfig();

    // Observe every configured Tesla source via its NOTIFY signal.
    for (auto it = m_teslaRules.constBegin(); it != m_teslaRules.constEnd(); ++it) {
        wireTeslaSource(it.key());
    }

    // Observe the application-core connection state.
    if (!m_connectionRules.isEmpty() && m_server) {
        connect(m_server, &ServerClient::connectedChanged, this,
                &NotificationHandler::onConnectionChanged);
    }
}

QString NotificationHandler::qmlName(const QString &registryName) {
    // Registry names are PascalCase; the generated Q_PROPERTYs lower-case only
    // the first character (Locked -> locked, RatedRange -> ratedRange).
    if (registryName.isEmpty()) {
        return registryName;
    }
    return registryName.left(1).toLower() + registryName.mid(1);
}

void NotificationHandler::loadConfig() {
    // The frontend notification config is separate from the backend's config.json.
    // Prefer an external file (env override) so it can be edited per-deployment,
    // falling back to the bundled default.
    QByteArray data;
    const QString override = qEnvironmentVariable("TESLA_HOMEDASH_NOTIFICATIONS_CONFIG");
    if (!override.isEmpty()) {
        QFile f(override);
        if (f.open(QIODevice::ReadOnly)) {
            data = f.readAll();
        } else {
            qCWarning(lcNotify) << "Could not open notification config" << override;
        }
    }
    if (data.isEmpty()) {
        QFile f(QStringLiteral(":/config/notifications.json"));
        if (f.open(QIODevice::ReadOnly)) {
            data = f.readAll();
        }
    }
    if (data.isEmpty()) {
        qCWarning(lcNotify) << "No notification config found; notifications disabled";
        return;
    }

    QJsonParseError err;
    const QJsonDocument doc = QJsonDocument::fromJson(data, &err);
    if (err.error != QJsonParseError::NoError || !doc.isObject()) {
        qCWarning(lcNotify) << "Invalid notification config:" << err.errorString();
        return;
    }

    const QJsonObject root = doc.object();
    if (root.contains("graceMs")) {
        m_graceMs = root.value("graceMs").toInt(m_graceMs);
    }

    const QJsonArray notifs = root.value("notifications").toArray();
    for (const QJsonValue &nv : notifs) {
        const QJsonObject n = nv.toObject();
        Rule rule;
        rule.id = n.value("id").toString();
        rule.format = n.value("format").toObject().toVariantMap();

        if (n.contains("sources")) {
            // Tesla source(s): a list of data-property ids.
            for (const QJsonValue &sv : n.value("sources").toArray()) {
                m_teslaRules[sv.toString()].append(rule);
            }
        } else if (n.contains("source")) {
            // Application-core source.
            const QString src = n.value("source").toString();
            if (src == QStringLiteral("server.connection.state")) {
                m_connectionRules.append(rule);
            } else {
                qCWarning(lcNotify) << "Unknown core notification source:" << src;
            }
        }
    }
    qCInfo(lcNotify) << "Loaded notification config: graceMs=" << m_graceMs
                     << "tesla sources=" << m_teslaRules.size()
                     << "connection rules=" << m_connectionRules.size();
}

void NotificationHandler::wireTeslaSource(const QString &sourceName) {
    if (!m_tesla) {
        return;
    }
    const QByteArray prop = qmlName(sourceName).toUtf8();
    const QMetaObject *mo = m_tesla->metaObject();
    const int propIdx = mo->indexOfProperty(prop.constData());
    if (propIdx < 0) {
        qCWarning(lcNotify) << "Notification source is not a Tesla property:" << sourceName;
        return;
    }
    const QMetaProperty mp = mo->property(propIdx);
    if (!mp.hasNotifySignal()) {
        qCWarning(lcNotify) << "Tesla property has no NOTIFY:" << sourceName;
        return;
    }
    const QMetaMethod sig = mp.notifySignal();

    const QMetaObject *selfMo = metaObject();
    const int slotIdx = selfMo->indexOfSlot("onTeslaSourceChanged()");
    const QMetaMethod slot = selfMo->method(slotIdx);

    connect(m_tesla, sig, this, slot);
    m_signalToSource.insert(sig.methodIndex(), sourceName);
}

void NotificationHandler::onTeslaSourceChanged() {
    const QString source = m_signalToSource.value(senderSignalIndex());
    if (source.isEmpty()) {
        return;
    }
    const QVariant value = m_tesla->property(qmlName(source).toUtf8().constData());

    // Fire only on an actual change; treat the first observation as a baseline so
    // a burst of "current state" notifications doesn't appear on connect.
    if (!m_lastValues.contains(source)) {
        m_lastValues.insert(source, value);
        return;
    }
    if (m_lastValues.value(source) == value) {
        return;
    }
    m_lastValues.insert(source, value);

    const QString triggerValue = value.toString();
    for (const Rule &rule : m_teslaRules.value(source)) {
        const QString message = render(rule, triggerValue);
        if (!message.isEmpty()) {
            emit notify(rule.id, message);
        }
    }
}

void NotificationHandler::onConnectionChanged() {
    // connectedChanged only fires on a real transition, and the first connect
    // should notify, so there is no baseline suppression here.
    const QString state = m_server->connected() ? QStringLiteral("connected")
                                                 : QStringLiteral("disconnected");
    for (const Rule &rule : m_connectionRules) {
        const QString message = render(rule, state);
        if (!message.isEmpty()) {
            emit notify(rule.id, message);
        }
    }
}

QString NotificationHandler::render(const Rule &rule, const QString &triggerValue) const {
    // Specific-value key (case-insensitive) wins over the "general" template.
    QString templ;
    for (auto it = rule.format.constBegin(); it != rule.format.constEnd(); ++it) {
        if (it.key().compare(QStringLiteral("general"), Qt::CaseInsensitive) == 0) {
            continue;
        }
        if (it.key().compare(triggerValue, Qt::CaseInsensitive) == 0) {
            templ = it.value().toString();
            break;
        }
    }
    if (templ.isEmpty()) {
        templ = rule.format.value(QStringLiteral("general")).toString();
    }
    if (templ.isEmpty()) {
        return QString();
    }
    return substitute(templ, triggerValue);
}

QString NotificationHandler::substitute(const QString &templ, const QString &triggerValue) const {
    // Replace {state} with the triggering value and {SomeTeslaProperty} with that
    // property's current value.
    static const QRegularExpression token(QStringLiteral("\\{(\\w+)\\}"));
    QString out = templ;
    QRegularExpressionMatchIterator it = token.globalMatch(templ);
    while (it.hasNext()) {
        const QRegularExpressionMatch m = it.next();
        const QString name = m.captured(1);
        QString value;
        if (name.compare(QStringLiteral("state"), Qt::CaseInsensitive) == 0) {
            value = triggerValue;
        } else if (m_tesla) {
            const QVariant v = m_tesla->property(qmlName(name).toUtf8().constData());
            value = v.isValid() ? v.toString() : QString();
        }
        out.replace(QStringLiteral("{") + name + QStringLiteral("}"), value);
    }
    return out;
}

void NotificationHandler::post(const QString &id, const QString &message) {
    emit notify(id, message);
}
