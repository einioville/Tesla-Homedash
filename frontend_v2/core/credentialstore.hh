#ifndef FRONTEND_V2_CREDENTIALSTORE_HH
#define FRONTEND_V2_CREDENTIALSTORE_HH

#include <QByteArray>
#include <QHash>
#include <QString>

#include <optional>

/**
 * CredentialStore — what lets a display reconnect without the password (#64).
 *
 * One entry per backend endpoint ("host:port"): the device id and token the
 * backend issued at login, and the SHA-256 of the certificate it presented then
 * (the pin). Kept in frontend_credentials.json beside frontend_config.json, 0600,
 * and deliberately NOT in frontend_config.json: that file is settings, this one
 * is a secret. `TESLA_HOMEDASH_CREDENTIALS_FILE` overrides the path.
 *
 * Not the OS keyring: on the kiosk the dashboard logs in automatically, so no
 * keyring is unlocked, and anything running as this user can read either.
 */
class CredentialStore {
public:
    struct Credential {
        QString deviceId;
        QString token;
        QByteArray certSha256;
    };

    CredentialStore();

    QString path() const { return m_path; }

    std::optional<Credential> find(const QString &endpoint) const;
    void store(const QString &endpoint, const Credential &credential);
    void forget(const QString &endpoint);

private:
    void save() const;

    QString m_path;
    QHash<QString, Credential> m_entries;
};

#endif  // FRONTEND_V2_CREDENTIALSTORE_HH
