#ifndef FRONTEND_V2_GEOCODER_HH
#define FRONTEND_V2_GEOCODER_HH

#include <QObject>
#include <QString>
#include <QTimer>
#include <QUrl>
#include <QVariantList>

#include <functional>

class QJsonObject;
class QNetworkAccessManager;
class QNetworkReply;

/**
 * Geocoder — addresses to coordinates and back for the Options view's Koti dialog (QML
 * `Geocoder`), through OpenStreetMap's Nominatim (ODbL, keyless), and the timezone of a
 * point from FMI's timeseries service, which the weather already comes from.
 *
 * Nominatim's usage policy shapes it: a User-Agent naming the application (which QML's
 * XMLHttpRequest may not set), at most one request a second and no search-as-you-type. So
 * `search()` runs when the user submits, and a request waits until a second has passed since
 * the last one went out; a newer one replaces any still waiting. Searches are limited to
 * Finland, where FMI's weather and the road cameras are.
 */
class Geocoder : public QObject {
    Q_OBJECT
    // The last search's hits as { address, lat, lon }, best first.
    Q_PROPERTY(QVariantList results READ results NOTIFY resultsChanged)
    // A search or a reverse lookup is waiting or under way.
    Q_PROPERTY(bool busy READ busy NOTIFY busyChanged)
    // Why the last search or lookup gave nothing, in Finnish; empty after a good one.
    Q_PROPERTY(QString error READ error NOTIFY errorChanged)

public:
    explicit Geocoder(QObject *parent = nullptr);

    QVariantList results() const { return m_results; }
    bool busy() const { return m_pending || m_inFlight; }
    QString error() const { return m_error; }

    Q_INVOKABLE void search(const QString &query);
    // The address at a point, as addressFound.
    Q_INVOKABLE void reverse(double lat, double lon);
    // The point's IANA zone, as zoneFound ("" when FMI could not say).
    Q_INVOKABLE void lookupZone(double lat, double lon);
    // Forgets the last search and drops a request still waiting: the dialog opens afresh.
    Q_INVOKABLE void clear();

signals:
    void resultsChanged();
    void busyChanged();
    void errorChanged();
    void addressFound(double lat, double lon, const QString &address);
    void zoneFound(double lat, double lon, const QString &zone);

private:
    using Handler = std::function<void(const QByteArray &)>;

    // Queues one Nominatim request, replacing any still waiting for its turn.
    void queueNominatim(const QUrl &url, Handler onReply, std::function<void()> onFail);
    void sendNominatim();
    void setError(const QString &error);
    QNetworkReply *get(const QUrl &url);
    // A short address from a Nominatim result: street and number (or, with no street, the
    // place's own name), postcode and town; the whole display name when those are missing.
    static QString shortAddress(const QJsonObject &result);

    QNetworkAccessManager *m_network;
    QVariantList m_results;
    QString m_error;
    QTimer m_turn;
    qint64 m_lastSentMs = 0;
    bool m_pending = false;
    bool m_inFlight = false;
    QUrl m_pendingUrl;
    Handler m_pendingReply;
    std::function<void()> m_pendingFail;
    // Bumped by every new request and by clear(), so a reply that lost its place is dropped.
    int m_generation = 0;
};

#endif  // FRONTEND_V2_GEOCODER_HH
