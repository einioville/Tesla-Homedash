#ifndef FRONTEND_V2_NOTIFICATIONHANDLER_HH
#define FRONTEND_V2_NOTIFICATIONHANDLER_HH

#include <QHash>
#include <QObject>
#include <QString>
#include <QVariant>
#include <QVariantMap>
#include <QVector>

class TeslaData;
class ServerClient;

/**
 * NotificationHandler — the frontend-owned notification engine, exposed to QML
 * as the `Notifications` singleton.
 *
 * The backend is a pure data pipe; notifications are entirely a frontend UI
 * concern with their OWN config (config/notifications.json, separate from the
 * backend's config.json). This handler is the single class the data layer feeds:
 * it observes the existing data handlers — each configured Tesla property's
 * NOTIFY signal (resolved generically through the meta-object, so no TeslaData
 * change is needed) and the ServerClient connection state — evaluates the
 * configured format rules, and emits notify(id, message) for the QML overlay.
 *
 * A rule's `format` map is { "general": template, "<value>": template, ... }: a
 * specific-value key matching the source's new value wins, otherwise `general`
 * is used, and `{Placeholder}` tokens are substituted ({state} = the triggering
 * value, {SomeTeslaProperty} = that property's current value).
 *
 * post() lets any other data handler (or QML) raise a notification directly.
 */
class NotificationHandler : public QObject {
    Q_OBJECT
    Q_PROPERTY(int graceMs READ graceMs CONSTANT)

public:
    NotificationHandler(TeslaData *tesla, ServerClient *server, QObject *parent = nullptr);

    int graceMs() const { return m_graceMs; }

    // Raise a notification directly, bypassing the config rules.
    Q_INVOKABLE void post(const QString &id, const QString &message);

signals:
    void notify(const QString &id, const QString &message);

private slots:
    // Routed for every wired Tesla source; senderSignalIndex() maps back to which.
    void onTeslaSourceChanged();
    void onConnectionChanged();

private:
    struct Rule {
        QString id;
        QVariantMap format;  // "general" + specific-value templates
    };

    void loadConfig();
    void wireTeslaSource(const QString &sourceName);
    QString render(const Rule &rule, const QString &triggerValue) const;
    QString substitute(const QString &templ, const QString &triggerValue) const;
    static QString qmlName(const QString &registryName);

    TeslaData *m_tesla;
    ServerClient *m_server;
    int m_graceMs = 5000;

    QHash<QString, QVector<Rule>> m_teslaRules;  // source name -> rules watching it
    QHash<int, QString> m_signalToSource;        // notify-signal index -> source name
    QHash<QString, QVariant> m_lastValues;       // source name -> last value (dedup)
    QVector<Rule> m_connectionRules;             // "server.connection.state" rules
};

#endif  // FRONTEND_V2_NOTIFICATIONHANDLER_HH
