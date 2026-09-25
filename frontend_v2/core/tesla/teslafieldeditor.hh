#ifndef FRONTEND_V2_TESLAFIELDEDITOR_HH
#define FRONTEND_V2_TESLAFIELDEDITOR_HH

#include <QObject>
#include <QString>
#include <QVariant>
#include <QVariantList>

class ServerClient;

/**
 * TeslaFieldEditor — the Options view's telemetry-field table (issue #29).
 *
 * Edits the per-field flags of the backend's config.json `tesla data` table that
 * are safe to change at runtime: `log` (written to InfluxDB, and so offered in the
 * History dropdown), `line_mode` and `zero_based` (History-graph render hints).
 * Everything else in that table is mirrored by this binary's generated registry
 * (tesladata_gen), so it is shown, never edited.
 *
 * This side holds no copy it edits: a change is sent as TESLA_SET_PROPERTY, and
 * the table the rows render is always the backend's, re-broadcast after every
 * accepted change. A refusal (a field Trips or Charging needs the history of, a
 * failed save) comes back as `lastError`.
 *
 * Registered with the QML engine as the singleton `TeslaFields` (see main.cpp),
 * rendered by items/settings/TeslaFieldTable.qml.
 */
class TeslaFieldEditor : public QObject {
    Q_OBJECT
    // One map per field: {id, category, unit, log, line_mode, zero_based,
    // numeric (true/false, or null until it has streamed), requiredBy}.
    Q_PROPERTY(QVariantList fields READ fields NOTIFY fieldsChanged)
    Q_PROPERTY(bool loaded READ loaded NOTIFY fieldsChanged)
    // The backend's reason for the last refused change; empty after a success.
    Q_PROPERTY(QString lastError READ lastError NOTIFY lastErrorChanged)

public:
    explicit TeslaFieldEditor(QObject *parent = nullptr);

    QVariantList fields() const { return m_fields; }
    bool loaded() const { return m_loaded; }
    QString lastError() const { return m_lastError; }

    // Wires the TESLA_*_PROPERTY traffic once the socket exists (main.cpp).
    void attachServer(ServerClient *client);

    // Asks for the table. Called by the card when it is built; a reconnect while
    // it has been asked for once re-requests it.
    Q_INVOKABLE void refresh();

    // Sends one change: `field` is "log", "line_mode" or "zero_based".
    Q_INVOKABLE void setField(const QString &id, const QString &field, const QVariant &value);

signals:
    void fieldsChanged();
    void lastErrorChanged();

private:
    void onPacket(quint8 type, const QByteArray &payload);
    void setLastError(const QString &message);

    ServerClient *m_server = nullptr;
    QVariantList m_fields;
    bool m_loaded = false;
    bool m_wanted = false;
    QString m_lastError;
};

#endif  // FRONTEND_V2_TESLAFIELDEDITOR_HH
