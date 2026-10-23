#include "geocoder.hh"

#include "../logger.hh"

#include <QDateTime>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QSet>
#include <QUrlQuery>
#include <QVariantMap>

#include <algorithm>

namespace {
const Logger logger = Logger::get("map");

const char *const kNominatim = "https://nominatim.openstreetmap.org";
// Nominatim's policy: an application User-Agent, at most one request a second.
const char *const kUserAgent = "Tesla-Homedash/1.0 (+https://github.com/einioville/Tesla-Homedash)";
constexpr int kSpacingMs = 1000;
constexpr int kTimeoutMs = 15000;
// Asked for more than are shown, since one address comes back several times.
constexpr int kResults = 10;

QUrlQuery nominatimQuery() {
    QUrlQuery q;
    q.addQueryItem(QStringLiteral("format"), QStringLiteral("jsonv2"));
    q.addQueryItem(QStringLiteral("addressdetails"), QStringLiteral("1"));
    q.addQueryItem(QStringLiteral("accept-language"), QStringLiteral("fi"));
    return q;
}
}  // namespace

Geocoder::Geocoder(QObject *parent) : QObject(parent), m_network(new QNetworkAccessManager(this)) {
    m_turn.setSingleShot(true);
    connect(&m_turn, &QTimer::timeout, this, &Geocoder::sendNominatim);
}

void Geocoder::search(const QString &query) {
    const QString text = query.trimmed();
    if (text.isEmpty())
        return;
    QUrl url(QString::fromLatin1(kNominatim) + QStringLiteral("/search"));
    QUrlQuery q = nominatimQuery();
    q.addQueryItem(QStringLiteral("q"), text);
    q.addQueryItem(QStringLiteral("countrycodes"), QStringLiteral("fi"));
    q.addQueryItem(QStringLiteral("limit"), QString::number(kResults));
    url.setQuery(q);
    queueNominatim(
        url,
        [this, text](const QByteArray &body) {
            QVariantList hits;
            // One address often comes back several times — the building, its entrance,
            // a shop in it — and the first is as good as the rest.
            QSet<QString> seen;
            for (const QJsonValue &v : QJsonDocument::fromJson(body).array()) {
                const QJsonObject r = v.toObject();
                const QString address = shortAddress(r);
                if (seen.contains(address))
                    continue;
                seen.insert(address);
                QVariantMap hit;
                hit.insert(QStringLiteral("address"), address);
                hit.insert(QStringLiteral("lat"), r.value(QStringLiteral("lat")).toString().toDouble());
                hit.insert(QStringLiteral("lon"), r.value(QStringLiteral("lon")).toString().toDouble());
                hits.append(hit);
            }
            m_results = hits;
            emit resultsChanged();
            setError(hits.isEmpty() ? tr("Haulla \"%1\" ei löytynyt osoitetta").arg(text) : QString());
            logger.info(QStringLiteral("Address search: %1 hit(s)").arg(hits.size()));
        },
        [this]() {
            m_results.clear();
            emit resultsChanged();
            setError(tr("Haku epäonnistui. Tarkista verkkoyhteys."));
        });
}

void Geocoder::reverse(double lat, double lon) {
    QUrl url(QString::fromLatin1(kNominatim) + QStringLiteral("/reverse"));
    QUrlQuery q = nominatimQuery();
    q.addQueryItem(QStringLiteral("lat"), QString::number(lat, 'f', 6));
    q.addQueryItem(QStringLiteral("lon"), QString::number(lon, 'f', 6));
    q.addQueryItem(QStringLiteral("zoom"), QStringLiteral("18"));
    url.setQuery(q);
    queueNominatim(
        url,
        [this, lat, lon](const QByteArray &body) {
            const QJsonObject r = QJsonDocument::fromJson(body).object();
            // Out at sea or off the map, Nominatim answers {"error": "Unable to geocode"}.
            if (r.contains(QStringLiteral("error")) || r.isEmpty()) {
                setError(tr("Kohdalle ei löytynyt osoitetta"));
                emit addressFound(lat, lon, QString());
                return;
            }
            setError(QString());
            emit addressFound(lat, lon, shortAddress(r));
        },
        [this, lat, lon]() {
            setError(tr("Osoitteen haku epäonnistui. Tarkista verkkoyhteys."));
            emit addressFound(lat, lon, QString());
        });
}

void Geocoder::clear() {
    ++m_generation;
    m_turn.stop();
    const bool wasBusy = busy();
    m_pending = false;
    m_inFlight = false;
    if (!m_results.isEmpty()) {
        m_results.clear();
        emit resultsChanged();
    }
    setError(QString());
    if (wasBusy)
        emit busyChanged();
}

void Geocoder::queueNominatim(const QUrl &url, Handler onReply, std::function<void()> onFail) {
    const bool wasBusy = busy();
    ++m_generation;
    m_pendingUrl = url;
    m_pendingReply = std::move(onReply);
    m_pendingFail = std::move(onFail);
    m_pending = true;
    if (!wasBusy)
        emit busyChanged();
    const qint64 wait = m_lastSentMs + kSpacingMs - QDateTime::currentMSecsSinceEpoch();
    m_turn.start(int(std::max<qint64>(0, wait)));
}

void Geocoder::sendNominatim() {
    if (!m_pending)
        return;
    m_pending = false;
    m_inFlight = true;
    m_lastSentMs = QDateTime::currentMSecsSinceEpoch();
    const int generation = m_generation;
    Handler onReply = std::move(m_pendingReply);
    std::function<void()> onFail = std::move(m_pendingFail);
    QNetworkReply *reply = get(m_pendingUrl);
    connect(reply, &QNetworkReply::finished, this, [this, reply, generation, onReply, onFail]() {
        reply->deleteLater();
        // A newer request (or clear()) took over: this answer is for something nobody wants.
        if (generation != m_generation)
            return;
        m_inFlight = false;
        const int status = reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
        if (reply->error() == QNetworkReply::NoError && status == 200) {
            onReply(reply->readAll());
        } else {
            logger.warning(QStringLiteral("Nominatim request failed: HTTP %1, %2")
                               .arg(status).arg(reply->errorString()));
            onFail();
        }
        emit busyChanged();
    });
}

void Geocoder::setError(const QString &error) {
    if (error == m_error)
        return;
    m_error = error;
    emit errorChanged();
}

QNetworkReply *Geocoder::get(const QUrl &url) {
    QNetworkRequest request(url);
    request.setHeader(QNetworkRequest::UserAgentHeader, QString::fromLatin1(kUserAgent));
    request.setTransferTimeout(kTimeoutMs);
    return m_network->get(request);
}

QString Geocoder::shortAddress(const QJsonObject &result) {
    const QJsonObject a = result.value(QStringLiteral("address")).toObject();
    auto field = [&a](std::initializer_list<const char *> keys) {
        for (const char *key : keys) {
            const QString v = a.value(QLatin1String(key)).toString();
            if (!v.isEmpty())
                return v;
        }
        return QString();
    };
    QStringList parts;
    const QString road = field({"road", "pedestrian", "footway", "path"});
    if (!road.isEmpty()) {
        const QString number = field({"house_number"});
        parts << (number.isEmpty() ? road : road + QLatin1Char(' ') + number);
    } else {
        // No street: a landmark or a village, known by its name.
        const QString name = result.value(QStringLiteral("name")).toString();
        if (!name.isEmpty())
            parts << name;
    }
    const QString town = field({"city", "town", "village", "municipality", "hamlet", "suburb"});
    const QString postcode = field({"postcode"});
    const QString area = (postcode + QLatin1Char(' ') + town).trimmed();
    if (!area.isEmpty())
        parts << area;
    if (parts.isEmpty())
        return result.value(QStringLiteral("display_name")).toString();
    return parts.join(QStringLiteral(", "));
}
