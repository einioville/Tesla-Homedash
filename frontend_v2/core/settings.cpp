#include "settings.hh"

#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonValue>
#include <QSaveFile>
#include <QStandardPaths>
#include <QtEndian>
#include <QtGlobal>
#include <utility>

#include "dotenv.hh"
#include "logger.hh"
#include "protocol.hh"
#include "serverclient.hh"

namespace {
const Logger logger = Logger::get("settings");

// Bundled schema: defaults, types, bounds and Finnish labels for the local half.
// Compiled into the binary, never written to.
const QString kSchemaResource = QStringLiteral(":/config/settings.json");

// Where the user's overrides are persisted. AppConfigLocation because it is
// writable on every target and survives redeploying the binary; overridable so a
// deployment can point it somewhere else (a tmpfs-backed image, say).
const char *kStorageEnv = "TESLA_HOMEDASH_SETTINGS_FILE";

// Exit code used when the user asks the app to restart itself. Deliberately
// NON-ZERO so the README's `Restart=on-failure` frontend unit brings it back —
// a clean exit(0) would leave a keyboard-less Pi staring at the desktop. Matches
// the backend's config_service.RESTART_EXIT_CODE, which does the same thing.
constexpr int kRestartExitCode = 42;

// Reads a length-prefixed UTF-8 JSON body: status(1B) + len(4B) + bytes. Returns
// an empty document (and leaves *ok false) on any truncation, which is how a
// malformed frame is refused rather than half-parsed.
QJsonDocument readStatusJsonBody(const QByteArray &payload, quint8 *status, bool *ok) {
    *ok = false;
    if (payload.size() < 5) {
        return {};
    }
    *status = static_cast<quint8>(payload.at(0));
    const quint32 length = qFromBigEndian<quint32>(payload.constData() + 1);
    // 64-bit-safe size check: the cast keeps a huge length from wrapping.
    if (static_cast<qint64>(payload.size()) < 5 + static_cast<qint64>(length)) {
        return {};
    }
    QJsonParseError error{};
    const QJsonDocument doc =
        QJsonDocument::fromJson(payload.mid(5, static_cast<int>(length)), &error);
    if (error.error != QJsonParseError::NoError) {
        logger.warning(QStringLiteral("Malformed settings JSON: %1").arg(error.errorString()));
        return {};
    }
    *ok = true;
    return doc;
}

// Environment variables are always strings; convert one to the type its schema
// entry declares so coerceLocal can validate it like any other value.
QVariant envFromString(const QJsonObject &setting, const QString &raw) {
    const QString type = setting.value(QStringLiteral("type")).toString();
    if (type == QLatin1String("bool")) {
        const QString lowered = raw.trimmed().toLower();
        return lowered == QLatin1String("1") || lowered == QLatin1String("true") ||
               lowered == QLatin1String("yes");
    }
    if (type == QLatin1String("int")) {
        return raw.trimmed().toInt();
    }
    if (type == QLatin1String("float")) {
        return raw.trimmed().toDouble();
    }
    return raw;
}

// Frames a JSON request body as len(4B) + UTF-8, the CONFIG_* payload shape.
QByteArray jsonRequestBody(const QJsonObject &object) {
    const QByteArray json = QJsonDocument(object).toJson(QJsonDocument::Compact);
    QByteArray body;
    body.resize(4);
    qToBigEndian<quint32>(static_cast<quint32>(json.size()), body.data());
    body.append(json);
    return body;
}
}  // namespace

Settings::Settings(QObject *parent) : QObject(parent) {
    const QString override = qEnvironmentVariable(kStorageEnv).trimmed();
    if (!override.isEmpty()) {
        m_storagePath = override;
    } else {
        const QString dir = QStandardPaths::writableLocation(QStandardPaths::AppConfigLocation);
        m_storagePath = dir + QStringLiteral("/settings.json");
    }

    loadLocalSchema();
    loadSavedValues();
    rebuildGroups();
}

// ── Local schema + persistence ───────────────────────────────────────────────

void Settings::loadLocalSchema() {
    QFile file(kSchemaResource);
    if (!file.open(QIODevice::ReadOnly)) {
        logger.warning(QStringLiteral("Could not open %1; no local settings").arg(kSchemaResource));
        return;
    }
    QJsonParseError error{};
    const QJsonDocument doc = QJsonDocument::fromJson(file.readAll(), &error);
    if (error.error != QJsonParseError::NoError || !doc.isObject()) {
        logger.warning(QStringLiteral("Invalid local settings schema: %1").arg(error.errorString()));
        return;
    }

    const QJsonArray groups = doc.object().value(QStringLiteral("groups")).toArray();
    for (const QJsonValue &groupValue : groups) {
        const QJsonObject group = groupValue.toObject();
        QVariantList settings;
        const QJsonArray entries = group.value(QStringLiteral("settings")).toArray();
        for (const QJsonValue &entryValue : entries) {
            const QJsonObject entry = entryValue.toObject();
            const QString key = entry.value(QStringLiteral("key")).toString();
            if (key.isEmpty()) {
                continue;
            }
            // A setting may name an environment variable that supplies its
            // DEFAULT, so an existing deployment's .env keeps working until the
            // user overrides it here. Full precedence:
            //   schema default  <  env / .env  <  saved user override
            QJsonObject resolved = entry;
            const QString envKey = entry.value(QStringLiteral("env")).toString();
            if (!envKey.isEmpty()) {
                const QString fromEnv = dotenv::valueOr(envKey.toLatin1().constData());
                if (!fromEnv.isEmpty()) {
                    QString envError;
                    const QVariant coerced = coerceLocal(entry, envFromString(entry, fromEnv),
                                                         &envError);
                    if (envError.isEmpty()) {
                        resolved.insert(QStringLiteral("default"),
                                        QJsonValue::fromVariant(coerced));
                    } else {
                        logger.warning(QStringLiteral("Ignoring %1=%2 for %3: %4")
                                           .arg(envKey, fromEnv, key, envError));
                    }
                }
            }

            m_localSchema.insert(key, resolved);
            // Seed the property map with the default so a Theme binding to any
            // schema key resolves from the very first frame — an absent key would
            // read as `undefined` and silently break that binding. `action`
            // entries are buttons, not values, so they get no map entry (and are
            // never persisted or restored).
            if (entry.value(QStringLiteral("type")).toString() != QLatin1String("action")) {
                m_values.insert(key,
                                resolved.value(QStringLiteral("default")).toVariant());
            }
            settings.append(resolved.toVariantMap());
        }
        // Carry every group-level key except "settings" (which was rebuilt
        // above) rather than naming them one by one — the sidebar icon was the
        // first extra field, and the next one should not need a code change.
        QVariantMap groupMap = group.toVariantMap();
        groupMap.insert(QStringLiteral("settings"), settings);
        m_localGroups.append(groupMap);
    }
    logger.info(QStringLiteral("Local settings schema: %1 settings in %2 groups")
                    .arg(m_localSchema.size())
                    .arg(m_localGroups.size()));
}

void Settings::loadSavedValues() {
    QFile file(m_storagePath);
    if (!file.exists()) {
        logger.info(QStringLiteral("No saved settings at %1; using defaults").arg(m_storagePath));
        return;
    }
    if (!file.open(QIODevice::ReadOnly)) {
        logger.warning(QStringLiteral("Could not read settings from %1").arg(m_storagePath));
        return;
    }
    QJsonParseError error{};
    const QJsonDocument doc = QJsonDocument::fromJson(file.readAll(), &error);
    if (error.error != QJsonParseError::NoError || !doc.isObject()) {
        // A corrupt file must not stop the app: fall back to defaults and leave
        // the file alone so it can be inspected.
        logger.warning(QStringLiteral("Ignoring corrupt settings file %1: %2")
                           .arg(m_storagePath, error.errorString()));
        return;
    }

    const QJsonObject saved = doc.object();
    for (auto it = saved.constBegin(); it != saved.constEnd(); ++it) {
        const auto schemaIt = m_localSchema.constFind(it.key());
        if (schemaIt == m_localSchema.constEnd()) {
            // A key from an older/newer build. Keep it out of `values` but do not
            // delete it — a downgrade should not lose the user's setting.
            logger.info(QStringLiteral("Ignoring unknown saved setting %1").arg(it.key()));
            continue;
        }
        QString coerceError;
        const QVariant coerced =
            coerceLocal(schemaIt.value(), it.value().toVariant(), &coerceError);
        if (!coerceError.isEmpty()) {
            logger.warning(
                QStringLiteral("Saved setting %1 rejected: %2").arg(it.key(), coerceError));
            continue;
        }
        m_values.insert(it.key(), coerced);
        m_overridden.insert(it.key());
    }
    logger.info(QStringLiteral("Loaded %1 saved settings from %2")
                    .arg(m_overridden.size())
                    .arg(m_storagePath));
}

void Settings::saveLocalValues() {
    const QFileInfo info(m_storagePath);
    if (!QDir().mkpath(info.absolutePath())) {
        logger.warning(QStringLiteral("Could not create %1").arg(info.absolutePath()));
        return;
    }

    // Only overridden keys are written. Defaults stay implicit, so changing a
    // default in a later release still reaches installs that never touched it.
    QJsonObject out;
    for (const QString &key : m_overridden) {
        out.insert(key, QJsonValue::fromVariant(m_values.value(key)));
    }

    // QSaveFile writes to a temp file and renames on commit, so a power cut
    // mid-write leaves the previous settings intact rather than a truncated file
    // — the embedded target loses power without a shutdown.
    QSaveFile file(m_storagePath);
    if (!file.open(QIODevice::WriteOnly | QIODevice::Text)) {
        logger.warning(QStringLiteral("Could not write settings to %1").arg(m_storagePath));
        return;
    }
    file.write(QJsonDocument(out).toJson(QJsonDocument::Indented));
    if (!file.commit()) {
        logger.warning(QStringLiteral("Could not commit settings to %1").arg(m_storagePath));
    }
}

QVariant Settings::savedValue(const QString &key) const {
    if (!m_overridden.contains(key)) {
        return {};
    }
    return m_values.value(key);
}

// ── Validation ───────────────────────────────────────────────────────────────

QVariant Settings::coerceLocal(const QJsonObject &setting, const QVariant &value,
                               QString *error) const {
    error->clear();
    const QString type = setting.value(QStringLiteral("type")).toString();

    if (type == QLatin1String("bool")) {
        if (value.typeId() != QMetaType::Bool) {
            *error = QStringLiteral("odotettiin tosi/epätosi-arvoa");
            return {};
        }
        return value.toBool();
    }

    if (type == QLatin1String("int") || type == QLatin1String("float")) {
        bool ok = false;
        const double number = value.toDouble(&ok);
        if (!ok || value.typeId() == QMetaType::Bool) {
            *error = QStringLiteral("odotettiin numeroa");
            return {};
        }
        // Clamp rather than reject: the editors (slider / stepper) already
        // constrain input, so an out-of-range value here means a stale saved file
        // or a schema whose bounds tightened — snapping is friendlier than
        // dropping the setting back to its default.
        double clamped = number;
        if (setting.contains(QStringLiteral("min"))) {
            clamped = qMax(clamped, setting.value(QStringLiteral("min")).toDouble());
        }
        if (setting.contains(QStringLiteral("max"))) {
            clamped = qMin(clamped, setting.value(QStringLiteral("max")).toDouble());
        }
        if (type == QLatin1String("int")) {
            return static_cast<int>(qRound(clamped));
        }
        return clamped;
    }

    if (type == QLatin1String("string") || type == QLatin1String("enum")) {
        if (value.typeId() != QMetaType::QString) {
            *error = QStringLiteral("odotettiin tekstiä");
            return {};
        }
        const QString text = value.toString().trimmed();
        if (text.isEmpty()) {
            *error = QStringLiteral("arvo ei voi olla tyhjä");
            return {};
        }
        return text;
    }

    *error = QStringLiteral("tuntematon asetustyyppi: %1").arg(type);
    return {};
}

// ── Groups (the UI description) ──────────────────────────────────────────────

void Settings::rebuildGroups() {
    QVariantList groups;

    // Local groups, with the live value folded into each setting.
    for (const QVariant &groupValue : std::as_const(m_localGroups)) {
        QVariantMap group = groupValue.toMap();
        QVariantList settings;
        const QVariantList entries = group.value(QStringLiteral("settings")).toList();
        for (const QVariant &entryValue : entries) {
            QVariantMap entry = entryValue.toMap();
            const QString key = entry.value(QStringLiteral("key")).toString();
            entry.insert(QStringLiteral("value"), m_values.value(key));
            entry.insert(QStringLiteral("origin"), QStringLiteral("local"));
            entry.insert(QStringLiteral("modified"), m_overridden.contains(key));
            settings.append(entry);
        }
        group.insert(QStringLiteral("settings"), settings);
        group.insert(QStringLiteral("origin"), QStringLiteral("local"));
        groups.append(group);
    }

    // Backend groups verbatim — the backend already folds in current values and
    // its own effective apply tier, so nothing is recomputed here.
    for (const QVariant &groupValue : std::as_const(m_backendGroups)) {
        QVariantMap group = groupValue.toMap();
        QVariantList settings;
        const QVariantList entries = group.value(QStringLiteral("settings")).toList();
        for (const QVariant &entryValue : entries) {
            QVariantMap entry = entryValue.toMap();
            entry.insert(QStringLiteral("origin"), QStringLiteral("backend"));
            settings.append(entry);
        }
        group.insert(QStringLiteral("settings"), settings);
        group.insert(QStringLiteral("origin"), QStringLiteral("backend"));
        groups.append(group);
    }

    m_groups = groups;
    emit groupsChanged();
}

// ── Writes ───────────────────────────────────────────────────────────────────

void Settings::setLocal(const QString &key, const QVariant &value) {
    m_values.insert(key, value);
    m_overridden.insert(key);
    saveLocalValues();
    rebuildGroups();
}

void Settings::setValue(const QString &key, const QVariant &value) {
    const auto schemaIt = m_localSchema.constFind(key);
    if (schemaIt != m_localSchema.constEnd()) {
        QString error;
        const QVariant coerced = coerceLocal(schemaIt.value(), value, &error);
        if (!error.isEmpty()) {
            logger.warning(QStringLiteral("Rejected %1: %2").arg(key, error));
            emit writeFailed(key, error);
            return;
        }
        setLocal(key, coerced);
        const QString applied = schemaIt.value().value(QStringLiteral("apply")).toString();
        logger.info(QStringLiteral("Setting %1 = %2 (%3)")
                        .arg(key, coerced.toString(), applied));
        if (applied == QLatin1String("restart") && !m_appRestartPending) {
            m_appRestartPending = true;
            emit appRestartPendingChanged();
        }
        emit writeSucceeded(key, applied);
        return;
    }

    // Not local: assume a backend key and let the backend's schema validate it.
    // Sending an unknown key is harmless — it replies with a rejection we surface.
    if (m_server == nullptr || !m_server->connected()) {
        emit writeFailed(key, QStringLiteral("Ei yhteyttä palvelimeen"));
        return;
    }
    QJsonObject request;
    request.insert(QStringLiteral("key"), key);
    request.insert(QStringLiteral("value"), QJsonValue::fromVariant(value));
    logger.info(QStringLiteral("CONFIG_SET %1 = %2").arg(key, value.toString()));
    m_server->sendPacket(protocol::frame(protocol::CONFIG_SET, jsonRequestBody(request)));
}

void Settings::resetToDefault(const QString &key) {
    const auto schemaIt = m_localSchema.constFind(key);
    if (schemaIt == m_localSchema.constEnd()) {
        logger.warning(QStringLiteral("resetToDefault on non-local key %1").arg(key));
        return;
    }
    m_values.insert(key, schemaIt.value().value(QStringLiteral("default")).toVariant());
    m_overridden.remove(key);
    saveLocalValues();
    rebuildGroups();
    logger.info(QStringLiteral("Setting %1 reset to default").arg(key));
    emit writeSucceeded(key, schemaIt.value().value(QStringLiteral("apply")).toString());
}

void Settings::restartApp() {
    logger.warning(QStringLiteral("Restarting the dashboard (exit %1) at the user's request")
                       .arg(kRestartExitCode));
    // exit() unwinds QGuiApplication::exec() rather than killing the process, so
    // the socket closes cleanly and settings already written are flushed.
    QCoreApplication::exit(kRestartExitCode);
}

void Settings::invokeAction(const QString &key) {
    if (key == QLatin1String("restartApp")) {
        restartApp();
    } else if (key == QLatin1String("restartBackend")) {
        requestBackendRestart();
    } else {
        logger.warning(QStringLiteral("Unknown settings action: %1").arg(key));
    }
}

void Settings::requestBackendRestart() {
    if (m_server == nullptr || !m_server->connected()) {
        emit writeFailed(QString(), QStringLiteral("Ei yhteyttä palvelimeen"));
        return;
    }
    logger.info(QStringLiteral("Requesting backend restart"));
    m_server->sendPacket(protocol::frame(protocol::CONFIG_RESTART));
    if (m_restartPending) {
        m_restartPending = false;
        emit restartPendingChanged();
    }
}

// ── Backend traffic ──────────────────────────────────────────────────────────

void Settings::attachServer(ServerClient *client) {
    m_server = client;
    connect(client, &ServerClient::packetReceived, this, &Settings::onPacket);
    // The backend snapshots the schema to every new client on connect, so an
    // explicit request is only needed if that snapshot is ever missed; asking on
    // each (re)connect makes the view self-healing after a backend restart —
    // which the restart button deliberately causes.
    connect(client, &ServerClient::connectedChanged, this, [this, client]() {
        if (client->connected()) {
            client->sendPacket(protocol::frame(protocol::CONFIG_GET_SCHEMA));
        }
    });
}

void Settings::onPacket(quint8 type, const QByteArray &payload) {
    switch (type) {
    case protocol::CONFIG_SCHEMA:
        parseBackendSchema(payload);
        break;
    case protocol::CONFIG_SET_RESULT:
        parseSetResult(payload);
        break;
    default:
        break;
    }
}

void Settings::parseBackendSchema(const QByteArray &payload) {
    quint8 status = protocol::CONFIG_STATUS_ERROR;
    bool ok = false;
    const QJsonDocument doc = readStatusJsonBody(payload, &status, &ok);
    if (!ok || status != protocol::CONFIG_STATUS_OK || !doc.isObject()) {
        logger.warning(QStringLiteral("CONFIG_SCHEMA unusable; keeping previous"));
        return;
    }

    QVariantList groups;
    const QJsonArray array = doc.object().value(QStringLiteral("groups")).toArray();
    for (const QJsonValue &group : array) {
        groups.append(group.toObject().toVariantMap());
    }
    m_backendGroups = groups;
    logger.info(QStringLiteral("Backend settings schema: %1 groups").arg(groups.size()));
    rebuildGroups();
}

void Settings::parseSetResult(const QByteArray &payload) {
    quint8 status = protocol::CONFIG_STATUS_ERROR;
    bool ok = false;
    const QJsonDocument doc = readStatusJsonBody(payload, &status, &ok);
    if (!ok || !doc.isObject()) {
        logger.warning(QStringLiteral("Malformed CONFIG_SET_RESULT"));
        return;
    }
    const QJsonObject result = doc.object();
    const QString key = result.value(QStringLiteral("key")).toString();
    const QString message = result.value(QStringLiteral("message")).toString();
    const QString applied = result.value(QStringLiteral("applied")).toString();

    if (status != protocol::CONFIG_STATUS_OK) {
        logger.warning(QStringLiteral("Backend rejected %1: %2").arg(key, message));
        emit writeFailed(key, message);
        return;
    }

    logger.info(QStringLiteral("Backend applied %1 (%2)").arg(key, applied));
    if (applied == QLatin1String("restart") && !m_restartPending) {
        m_restartPending = true;
        emit restartPendingChanged();
    }
    emit writeSucceeded(key, applied);
}
