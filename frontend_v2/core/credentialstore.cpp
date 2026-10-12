#include "credentialstore.hh"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QJsonObject>
#include <QSaveFile>
#include <QStandardPaths>
#include <QtGlobal>

#include "logger.hh"

namespace {
const Logger logger = Logger::get("credentials");

const char *kPathEnv = "TESLA_HOMEDASH_CREDENTIALS_FILE";

// Beside frontend_config.json and the backend's backend_config.json.
QString defaultPath() {
    return QStandardPaths::writableLocation(QStandardPaths::GenericConfigLocation) +
           QStringLiteral("/Tesla-Homedash/frontend_credentials.json");
}
}  // namespace

CredentialStore::CredentialStore() {
    const QString overridden = qEnvironmentVariable(kPathEnv);
    m_path = overridden.isEmpty() ? defaultPath() : overridden;

    QFile file(m_path);
    if (!file.open(QIODevice::ReadOnly)) {
        return;
    }
    const QJsonObject root = QJsonDocument::fromJson(file.readAll()).object();
    for (auto it = root.constBegin(); it != root.constEnd(); ++it) {
        const QJsonObject entry = it.value().toObject();
        Credential credential{
            entry.value(QStringLiteral("deviceId")).toString(),
            entry.value(QStringLiteral("token")).toString(),
            QByteArray::fromHex(entry.value(QStringLiteral("certSha256")).toString().toLatin1()),
        };
        if (!credential.deviceId.isEmpty() && !credential.token.isEmpty() &&
            credential.certSha256.size() == 32) {
            m_entries.insert(it.key(), credential);
        }
    }
}

std::optional<CredentialStore::Credential> CredentialStore::find(const QString &endpoint) const {
    const auto it = m_entries.constFind(endpoint);
    if (it == m_entries.constEnd()) {
        return std::nullopt;
    }
    return *it;
}

void CredentialStore::store(const QString &endpoint, const Credential &credential) {
    m_entries.insert(endpoint, credential);
    save();
}

void CredentialStore::forget(const QString &endpoint) {
    if (m_entries.remove(endpoint) > 0) {
        save();
    }
}

void CredentialStore::save() const {
    QJsonObject root;
    for (auto it = m_entries.constBegin(); it != m_entries.constEnd(); ++it) {
        root.insert(it.key(), QJsonObject{
                                  {QStringLiteral("deviceId"), it->deviceId},
                                  {QStringLiteral("token"), it->token},
                                  {QStringLiteral("certSha256"),
                                   QString::fromLatin1(it->certSha256.toHex())},
                              });
    }
    QDir().mkpath(QFileInfo(m_path).absolutePath());
    // Atomic like the settings file (the Pi loses power without a shutdown), and
    // owner-only from the start: the permissions go on the temp file before any
    // byte of the token is written, and the rename keeps them.
    QSaveFile file(m_path);
    if (!file.open(QIODevice::WriteOnly) ||
        !file.setPermissions(QFileDevice::ReadOwner | QFileDevice::WriteOwner)) {
        logger.warning(QStringLiteral("Could not write %1").arg(m_path));
        return;
    }
    file.write(QJsonDocument(root).toJson(QJsonDocument::Indented));
    if (!file.commit()) {
        logger.warning(QStringLiteral("Could not commit %1").arg(m_path));
    }
}
