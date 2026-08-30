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
#include <QUrl>
#include <QStringList>
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

// Where the user's overrides are persisted. Overridable so a deployment can point
// it somewhere else (a tmpfs-backed image, say).
const char *kStorageEnv = "TESLA_HOMEDASH_SETTINGS_FILE";

// GenericConfigLocation + the project's own directory, so this file lands beside
// the BACKEND's backend_config.json in ~/.config/Tesla-Homedash/ rather than in an
// app-name directory nobody can guess. Resolves per-platform (%APPDATA% on
// Windows), so it stays correct off Linux.
QString defaultStoragePath() {
    return QStandardPaths::writableLocation(QStandardPaths::GenericConfigLocation) +
           QStringLiteral("/Tesla-Homedash/frontend_config.json");
}

// The pre-move location: AppConfigLocation/settings.json, which with no
// organisation or application name set resolves to ~/.config/appfrontend_v2/.
QString legacyStoragePath() {
    return QStandardPaths::writableLocation(QStandardPaths::AppConfigLocation) +
           QStringLiteral("/settings.json");
}

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

// A group's subsections. Tolerates the pre-subsection schema shape (a bare
// `settings` array) by synthesizing one section from it, so a frontend and a
// backend that disagree about the schema version still render.
QVariantList sectionsOf(const QVariantMap &group) {
    const QVariantList sections = group.value(QStringLiteral("sections")).toList();
    if (!sections.isEmpty()) {
        return sections;
    }
    const QVariantList settings = group.value(QStringLiteral("settings")).toList();
    if (settings.isEmpty()) {
        return {};
    }
    QVariantMap synthetic;
    synthetic.insert(QStringLiteral("id"), group.value(QStringLiteral("id")));
    synthetic.insert(QStringLiteral("label"), group.value(QStringLiteral("label")));
    synthetic.insert(QStringLiteral("settings"), settings);
    return {synthetic};
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
        m_storagePath = defaultStoragePath();
        migrateLegacyStorage();
    }

    loadLocalSchema();
    loadSavedValues();
    captureLocalRestartBaseline();
    rebuildGroups();
}

// Carries an existing settings file over from the pre-move location, once. Copies
// rather than moves: if anything about the new path is wrong the user's overrides
// are still where they were. A failed copy is not fatal — it just means starting
// from defaults, which is what would have happened anyway.
void Settings::migrateLegacyStorage() {
    if (QFile::exists(m_storagePath)) {
        return;
    }
    const QString legacy = legacyStoragePath();
    if (legacy == m_storagePath || !QFile::exists(legacy)) {
        return;
    }
    const QFileInfo info(m_storagePath);
    if (!QDir().mkpath(info.absolutePath()) || !QFile::copy(legacy, m_storagePath)) {
        logger.warning(QStringLiteral("Could not migrate settings from %1").arg(legacy));
        return;
    }
    logger.info(QStringLiteral("Migrated settings from %1").arg(legacy));
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
        QVariantList sections;

        for (const QJsonValue &sectionValue : group.value(QStringLiteral("sections")).toArray()) {
            const QJsonObject section = sectionValue.toObject();
            QVariantList settings;

            for (const QJsonValue &entryValue : section.value(QStringLiteral("settings")).toArray()) {
                const QJsonObject entry = entryValue.toObject();
                const QString key = entry.value(QStringLiteral("key")).toString();
                if (key.isEmpty()) {
                    continue;
                }
                // A setting may name an environment variable that supplies its
                // DEFAULT, so an existing deployment's .env keeps working until
                // the user overrides it here. Full precedence:
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
                // Seed the property map with the default so a Theme binding to
                // any schema key resolves from the very first frame — an absent
                // key would read as `undefined` and silently break that binding.
                // `action` entries are buttons, not values, so they get no map
                // entry (and are never persisted or restored).
                if (entry.value(QStringLiteral("type")).toString() != QLatin1String("action")) {
                    m_values.insert(key, resolved.value(QStringLiteral("default")).toVariant());
                }
                settings.append(resolved.toVariantMap());
            }

            // Carry every subsection-level key except "settings" (rebuilt above)
            // rather than naming them one by one, for the same reason as the
            // group level below.
            QVariantMap sectionMap = section.toVariantMap();
            sectionMap.insert(QStringLiteral("settings"), settings);
            sections.append(sectionMap);
        }

        // Carry every group-level key except "sections" (rebuilt above) rather
        // than naming them one by one — the sidebar icon was the first extra
        // field, and the next one should not need a code change. A group with no
        // subsections at all is kept: it is the placeholder that fixes a
        // backend-only section's position, label and icon.
        QVariantMap groupMap = group.toVariantMap();
        groupMap.insert(QStringLiteral("sections"), sections);
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
        // A nullable string may be cleared back to "not configured" — for the
        // screensaver folder that is the difference between "no photos" and a
        // directory literally named "".
        if (text.isEmpty() && !setting.value(QStringLiteral("nullable")).toBool()) {
            *error = QStringLiteral("arvo ei voi olla tyhjä");
            return {};
        }
        return text;
    }

    *error = QStringLiteral("tuntematon asetustyyppi: %1").arg(type);
    return {};
}

// ── Groups (the UI description) ──────────────────────────────────────────────

QVariant Settings::valueOf(const QString &key) const {
    if (m_localSchema.contains(key)) {
        return m_values.value(key);
    }
    return m_backendValues.value(key);
}

// Flattens the last CONFIG_SCHEMA into key -> value, and seeds the restart
// baseline from it. The seeding is INSERT-IF-ABSENT, and that is the
// load-bearing part: the backend re-broadcasts its schema after every accepted
// write, so taking the new value as the baseline would erase the very
// difference the banner exists to report. The baseline is dropped only when the
// process identity changes — see parseBackendSchema.
void Settings::rebuildBackendValueIndex() {
    m_backendValues.clear();
    QSet<QString> restartTier;
    for (const QVariant &groupValue : std::as_const(m_backendGroups)) {
        const QVariantList sections = sectionsOf(groupValue.toMap());
        for (const QVariant &sectionValue : sections) {
            const QVariantList entries =
                sectionValue.toMap().value(QStringLiteral("settings")).toList();
            for (const QVariant &entryValue : entries) {
                const QVariantMap entry = entryValue.toMap();
                const QString key = entry.value(QStringLiteral("key")).toString();
                if (key.isEmpty()) {
                    continue;
                }
                const QVariant value = entry.value(QStringLiteral("value"));
                m_backendValues.insert(key, value);
                if (entry.value(QStringLiteral("apply")).toString() !=
                    QLatin1String("restart")) {
                    continue;
                }
                restartTier.insert(key);
                if (!m_backendRestartBaseline.contains(key)) {
                    m_backendRestartBaseline.insert(key, value);
                }
            }
        }
    }
    // A setting can STOP being restart-tier between schemas: the backend
    // downgrades a hook setting to restart only while its service is absent, so
    // a Zappi coming back makes myenergi.* hook-tier again. Stop diffing those.
    for (auto it = m_backendRestartBaseline.begin(); it != m_backendRestartBaseline.end();) {
        if (restartTier.contains(it.key())) {
            ++it;
        } else {
            it = m_backendRestartBaseline.erase(it);
        }
    }
}

// Snapshots the restart-tier local settings as they stand at startup — which is
// exactly what AppConfig reads a moment later (main.cpp builds Settings first
// for that reason), so "differs from this" means "differs from what the running
// app is using", not merely "differs from the schema default".
void Settings::captureLocalRestartBaseline() {
    m_localRestartBaseline.clear();
    for (auto it = m_localSchema.constBegin(); it != m_localSchema.constEnd(); ++it) {
        if (it.value().value(QStringLiteral("apply")).toString() == QLatin1String("restart")) {
            m_localRestartBaseline.insert(it.key(), m_values.value(it.key()));
        }
    }
}

void Settings::refreshAppRestartPending() {
    bool pending = false;
    for (auto it = m_localRestartBaseline.constBegin();
         it != m_localRestartBaseline.constEnd(); ++it) {
        if (m_values.value(it.key()) != it.value()) {
            pending = true;
            break;
        }
    }
    if (pending == m_appRestartPending) {
        return;
    }
    m_appRestartPending = pending;
    emit appRestartPendingChanged();
}

void Settings::refreshBackendRestartPending() {
    bool pending = false;
    for (auto it = m_backendRestartBaseline.constBegin();
         it != m_backendRestartBaseline.constEnd(); ++it) {
        if (m_backendValues.value(it.key()) != it.value()) {
            pending = true;
            break;
        }
    }
    if (pending == m_restartPending) {
        return;
    }
    m_restartPending = pending;
    emit restartPendingChanged();
}

QVariantList Settings::decorateSections(const QVariantList &sections, bool local) const {
    const QString origin = local ? QStringLiteral("local") : QStringLiteral("backend");
    QVariantList out;
    for (const QVariant &sectionValue : sections) {
        QVariantMap section = sectionValue.toMap();
        QVariantList settings;
        const QVariantList entries = section.value(QStringLiteral("settings")).toList();
        for (const QVariant &entryValue : entries) {
            QVariantMap entry = entryValue.toMap();
            entry.insert(QStringLiteral("origin"), origin);
            // The backend folds its own current value and effective apply tier
            // into the schema it sends, so only the local half needs them here.
            if (local) {
                const QString key = entry.value(QStringLiteral("key")).toString();
                entry.insert(QStringLiteral("value"), m_values.value(key));
                entry.insert(QStringLiteral("modified"), m_overridden.contains(key));
            }
            settings.append(entry);
        }
        // A subsection with no rows is normally a mistake, but not when it names
        // a runtime status widget: the system-status card is entirely a status
        // widget and has no settings at all.
        if (settings.isEmpty() &&
            section.value(QStringLiteral("status")).toString().isEmpty()) {
            continue;
        }
        section.insert(QStringLiteral("settings"), settings);
        section.insert(QStringLiteral("origin"), origin);
        out.append(section);
    }
    return out;
}

void Settings::rebuildGroups() {
    // Index the backend's groups by id: a group defined in BOTH halves merges
    // into one sidebar section holding both sets of subsections, rather than
    // appearing twice. That is what puts the local screensaver card and the
    // backend's location card together under "Yleinen".
    QHash<QString, QVariantMap> backendById;
    QStringList backendOrder;
    for (const QVariant &groupValue : std::as_const(m_backendGroups)) {
        const QVariantMap group = groupValue.toMap();
        const QString id = group.value(QStringLiteral("id")).toString();
        backendById.insert(id, group);
        backendOrder.append(id);
    }

    QVariantList groups;
    // The local schema is canonical for a section's order, label and icon.
    for (const QVariant &groupValue : std::as_const(m_localGroups)) {
        QVariantMap group = groupValue.toMap();
        const QString id = group.value(QStringLiteral("id")).toString();
        QVariantList sections = decorateSections(sectionsOf(group), true);
        if (backendById.contains(id)) {
            sections.append(decorateSections(sectionsOf(backendById.take(id)), false));
        }
        // Empty means a placeholder that exists only to fix this group's
        // position and name (media / tesla hold no local settings of their own),
        // and its backend half has not arrived — hide it rather than show an
        // empty section.
        if (sections.isEmpty()) {
            continue;
        }
        group.insert(QStringLiteral("sections"), sections);
        group.remove(QStringLiteral("settings"));
        groups.append(group);
    }

    // Then anything the local schema does not know about, in the backend's own
    // order, so a section added there still reaches the view unchanged.
    for (const QString &id : std::as_const(backendOrder)) {
        if (!backendById.contains(id)) {
            continue;
        }
        QVariantMap group = backendById.take(id);
        const QVariantList sections = decorateSections(sectionsOf(group), false);
        if (sections.isEmpty()) {
            continue;
        }
        group.insert(QStringLiteral("sections"), sections);
        group.remove(QStringLiteral("settings"));
        groups.append(group);
    }

    m_groups = groups;
    // Every value change in either half funnels through here, so one counter is
    // enough to make every valueOf() binding live.
    ++m_valuesRevision;
    emit groupsChanged();
}

// ── Writes ───────────────────────────────────────────────────────────────────

void Settings::setLocal(const QString &key, const QVariant &value) {
    m_values.insert(key, value);
    m_overridden.insert(key);
    saveLocalValues();
    rebuildGroups();
    refreshAppRestartPending();
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
    // resetToDefault bypasses setLocal, and resetting backendPort to its default
    // is itself a revert that must clear the banner.
    refreshAppRestartPending();
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

QString Settings::toFileUrl(const QString &path) const {
    const QString trimmed = path.trimmed();
    if (trimmed.isEmpty()) {
        return {};
    }
    // Already a URL (a saved value copied from elsewhere) passes through; a bare
    // path goes through QUrl so it is escaped and prefixed correctly rather than
    // by string concatenation, which gets Windows drive letters wrong.
    if (trimmed.startsWith(QLatin1String("file:"))) {
        return trimmed;
    }
    return QUrl::fromLocalFile(trimmed).toString();
}

void Settings::invokeAction(const QString &key) {
    if (key == QLatin1String("restartApp")) {
        restartApp();
    } else if (key == QLatin1String("restartBackend")) {
        requestBackendRestart();
    } else {
        // Not ours: something in QML owns this one. Nothing warns here — a key
        // with no listener at all is a schema mistake, not a runtime error, and
        // the row simply does nothing.
        logger.info(QStringLiteral("Settings action delegated to the view: %1").arg(key));
        emit actionRequested(key);
    }
}

void Settings::requestBackendRestart() {
    if (m_server == nullptr || !m_server->connected()) {
        emit writeFailed(QString(), QStringLiteral("Ei yhteyttä palvelimeen"));
        return;
    }
    logger.info(QStringLiteral("Requesting backend restart"));
    m_server->sendPacket(protocol::frame(protocol::CONFIG_RESTART));
    // A current backend stamps every schema with startedAt, so the banner clears
    // by itself when the RESTARTED process's schema arrives — strictly more
    // honest than clearing here, which would hide the change if the restart never
    // happened. Only an older backend that sends no stamp needs the optimistic
    // clear this used to do unconditionally.
    if (m_backendStartedAt == 0 && !m_backendRestartBaseline.isEmpty()) {
        m_backendRestartBaseline.clear();
        refreshBackendRestartPending();
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

    // A DIFFERENT process is running: whatever it reports is by definition what
    // it consumed at startup, so the old baseline is stale. The same value (a
    // reconnect, or the re-broadcast after a write) keeps the baseline —
    // otherwise a still-pending change would go quiet the moment the socket
    // flapped.
    const qint64 startedAt =
        static_cast<qint64>(doc.object().value(QStringLiteral("startedAt")).toDouble());
    if (startedAt != 0 && startedAt != m_backendStartedAt) {
        m_backendStartedAt = startedAt;
        m_backendRestartBaseline.clear();
    }
    rebuildBackendValueIndex();
    refreshBackendRestartPending();

    // Optional: an older backend sends no path. Only overwrite when one is
    // present, so a malformed or partial document cannot blank a path the view
    // is already showing.
    const QString path = doc.object().value(QStringLiteral("path")).toString();
    if (!path.isEmpty()) {
        m_backendStoragePath = path;
    }
    logger.info(QStringLiteral("Backend settings schema: %1 groups (%2)")
                    .arg(QString::number(groups.size()),
                         m_backendStoragePath.isEmpty() ? QStringLiteral("path unknown")
                                                        : m_backendStoragePath));
    // rebuildGroups() emits groupsChanged, which also notifies backendStoragePath.
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

    // No latch here: every accepted, value-changing write is followed by a
    // schema broadcast, and parseBackendSchema re-derives the flag from it.
    logger.info(QStringLiteral("Backend applied %1 (%2)").arg(key, applied));
    emit writeSucceeded(key, applied);
}
