#include "placenames.hh"

#include "../logger.hh"

#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QSaveFile>
#include <QStandardPaths>
#include <QUrl>
#include <QVariantMap>

#include <algorithm>
#include <cmath>

namespace {
const Logger logger = Logger::get("map");

// Public Overpass servers, tried in turn when one fails: the main one is often too busy to
// answer (502, 504), and a server's answer is as good as another's for names. GET, because
// kumi.systems answers a POST with a 500.
const char *const kServers[] = {
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
};

struct Kind {
    const char *tag;
    double minZoom;   // the map zoom it is labelled from
    int rank;         // 0 the most important
};
// The place=* values fetched; a tile tier below names which tiles carry each.
constexpr Kind kKinds[] = {
    {"city", 5.0, 0},
    {"town", 8.5, 1},
    {"village", 11.0, 2},
    {"suburb", 12.0, 2},
    {"borough", 12.0, 2},
    {"island", 12.0, 3},
    {"quarter", 13.0, 3},
    {"hamlet", 13.0, 4},
    {"neighbourhood", 14.0, 4},
    {"islet", 14.5, 5},
    {"locality", 15.0, 6},
    {"isolated_dwelling", 16.0, 6},
};

struct Tier {
    int tileZoom;
    double minZoom;       // the smallest of its kinds' minZoom
    const char *select;   // Overpass statements; %1 is the bbox
};
// A tile of each tier is about a screen of the map at its minZoom, so a view needs a
// handful. Islands are areas as often as points, hence nwr and `out center`.
constexpr Tier kTiers[] = {
    {6, 5.0, R"(node["place"~"^(city|town)$"]["name"](%1);)"},
    {9, 11.0, R"(node["place"~"^(village|suburb|borough|quarter)$"]["name"](%1);)"
              R"(nwr["place"="island"]["name"](%1);)"},
    {12, 13.0, R"(node["place"~"^(hamlet|neighbourhood|locality|isolated_dwelling)$"]["name"](%1);)"
               R"(nwr["place"="islet"]["name"](%1);)"},
};

// More tiles than this in one view means it is zoomed out past the tier's use.
constexpr int kMaxTilesPerTier = 24;
constexpr qint64 kRefreshMs = 180LL * 24 * 60 * 60 * 1000;
constexpr qint64 kForgetMs = 2 * 60 * 1000;
constexpr int kSpacingMs = 2000;
constexpr int kMinBackoffMs = 30 * 1000;
constexpr int kMaxBackoffMs = 10 * 60 * 1000;
constexpr int kTimeoutMs = 120 * 1000;

int kindOf(const QString &tag) {
    for (int i = 0; i < int(std::size(kKinds)); ++i) {
        if (tag == QLatin1String(kKinds[i].tag))
            return i;
    }
    return -1;
}

int lonToX(double lon, int z) {
    const int n = 1 << z;
    return std::clamp(int(std::floor((lon + 180.0) / 360.0 * n)), 0, n - 1);
}

int latToY(double lat, int z) {
    const int n = 1 << z;
    const double rad = std::clamp(lat, -85.05, 85.05) * M_PI / 180.0;
    return std::clamp(int(std::floor((1.0 - std::asinh(std::tan(rad)) / M_PI) / 2.0 * n)), 0, n - 1);
}

double xToLon(int x, int z) {
    return x / double(1 << z) * 360.0 - 180.0;
}

double yToLat(int y, int z) {
    return std::atan(std::sinh(M_PI * (1.0 - 2.0 * y / double(1 << z)))) * 180.0 / M_PI;
}

int tileZ(quint64 k) { return int(k >> 48); }
int tileX(quint64 k) { return int((k >> 24) & 0xFFFFFF); }
int tileY(quint64 k) { return int(k & 0xFFFFFF); }

QString tileName(quint64 k) {
    return QStringLiteral("%1-%2-%3").arg(tileZ(k)).arg(tileX(k)).arg(tileY(k));
}
}

PlaceNames::PlaceNames(QObject *parent)
    : QObject(parent), m_network(new QNetworkAccessManager(this)) {
    m_cacheDir = QStandardPaths::writableLocation(QStandardPaths::GenericCacheLocation)
                 + QStringLiteral("/Tesla-Homedash/place-names");
    QDir().mkpath(m_cacheDir);
    m_next.setSingleShot(true);
    connect(&m_next, &QTimer::timeout, this, &PlaceNames::fetchNext);
}

quint64 PlaceNames::key(int z, int x, int y) {
    return (quint64(z) << 48) | (quint64(x) << 24) | quint64(y);
}

QString PlaceNames::cachePath(quint64 tileKey) const {
    return m_cacheDir + QLatin1Char('/') + tileName(tileKey) + QStringLiteral(".json");
}

const PlaceNames::Tile *PlaceNames::cached(quint64 tileKey) {
    const auto it = m_tiles.constFind(tileKey);
    if (it != m_tiles.constEnd())
        return &it.value();
    if (m_notOnDisk.contains(tileKey))
        return nullptr;

    QFile file(cachePath(tileKey));
    if (!file.open(QIODevice::ReadOnly)) {
        m_notOnDisk.insert(tileKey);
        return nullptr;
    }
    const QJsonObject root = QJsonDocument::fromJson(file.readAll()).object();
    if (root.isEmpty()) {
        logger.warning(QStringLiteral("Unreadable place-name cache %1").arg(file.fileName()));
        m_notOnDisk.insert(tileKey);
        return nullptr;
    }
    Tile tile;
    tile.fetchedMs = qint64(root.value(QStringLiteral("fetched")).toDouble());
    const QJsonArray places = root.value(QStringLiteral("places")).toArray();
    tile.places.reserve(places.size());
    for (const QJsonValue &value : places) {
        const QJsonArray row = value.toArray();
        const int kind = kindOf(row.at(1).toString());
        if (row.size() < 4 || kind < 0)
            continue;
        tile.places.append({row.at(0).toString(), kind, row.at(2).toDouble(), row.at(3).toDouble()});
    }
    return &m_tiles.insert(tileKey, tile).value();
}

QVariantList PlaceNames::query(double south, double west, double north, double east, double zoom) {
    QVariantList out;
    QList<quint64> missing;
    QList<quint64> stale;
    const qint64 now = QDateTime::currentMSecsSinceEpoch();

    for (const Tier &tier : kTiers) {
        if (zoom < tier.minZoom)
            continue;
        const int z = tier.tileZoom;
        const int x0 = lonToX(west, z);
        const int x1 = lonToX(east, z);
        const int y0 = latToY(north, z);
        const int y1 = latToY(south, z);
        if ((x1 - x0 + 1) * (y1 - y0 + 1) > kMaxTilesPerTier)
            continue;
        for (int x = x0; x <= x1; ++x) {
            for (int y = y0; y <= y1; ++y) {
                const quint64 k = key(z, x, y);
                const Tile *tile = cached(k);
                if (!tile) {
                    missing.append(k);
                    continue;
                }
                if (now - tile->fetchedMs > kRefreshMs)
                    stale.append(k);
                for (const Place &place : tile->places) {
                    const Kind &kind = kKinds[place.kind];
                    if (zoom < kind.minZoom || place.lat < south || place.lat > north
                        || place.lon < west || place.lon > east)
                        continue;
                    out.append(QVariantMap{{QStringLiteral("name"), place.name},
                                           {QStringLiteral("lat"), place.lat},
                                           {QStringLiteral("lon"), place.lon},
                                           {QStringLiteral("rank"), kind.rank}});
                }
            }
        }
    }
    if (!missing.isEmpty() || !stale.isEmpty())
        enqueue(missing, stale);
    return out;
}

void PlaceNames::enqueue(const QList<quint64> &missing, const QList<quint64> &stale) {
    const qint64 now = QDateTime::currentMSecsSinceEpoch();
    for (const quint64 k : missing + stale) {
        m_wantedMs.insert(k, now);
        m_queue.removeAll(k);
    }
    m_queue = missing + m_queue + stale;
    if (!m_busy && !m_next.isActive())
        fetchNext();
}

void PlaceNames::fetchNext() {
    if (m_busy)
        return;
    const qint64 now = QDateTime::currentMSecsSinceEpoch();
    quint64 k = 0;
    while (!m_queue.isEmpty()) {
        const quint64 candidate = m_queue.takeFirst();
        if (now - m_wantedMs.value(candidate) <= kForgetMs) {
            k = candidate;
            break;
        }
        m_wantedMs.remove(candidate);
    }
    if (k == 0)
        return;

    const int z = tileZ(k);
    const QString bbox = QStringLiteral("%1,%2,%3,%4")
                             .arg(yToLat(tileY(k) + 1, z), 0, 'f', 6)
                             .arg(xToLon(tileX(k), z), 0, 'f', 6)
                             .arg(yToLat(tileY(k), z), 0, 'f', 6)
                             .arg(xToLon(tileX(k) + 1, z), 0, 'f', 6);
    const Tier *tier = std::find_if(std::begin(kTiers), std::end(kTiers),
                                    [z](const Tier &t) { return t.tileZoom == z; });
    const QString query = QStringLiteral("[out:json][timeout:90];(")
                          + QString::fromLatin1(tier->select).arg(bbox)
                          + QStringLiteral(");out tags center qt;");

    QUrl url(QString::fromLatin1(kServers[m_server]));
    url.setQuery(QStringLiteral("data=") + QString::fromLatin1(QUrl::toPercentEncoding(query)),
                 QUrl::StrictMode);
    QNetworkRequest request(url);
    request.setHeader(QNetworkRequest::UserAgentHeader, QStringLiteral("Tesla-Homedash/1.0"));
    request.setTransferTimeout(kTimeoutMs);
    QNetworkReply *reply = m_network->get(request);
    m_busy = true;
    connect(reply, &QNetworkReply::finished, this, [this, reply, k]() { onReply(reply, k); });
}

void PlaceNames::onReply(QNetworkReply *reply, quint64 tileKey) {
    reply->deleteLater();
    m_busy = false;
    const int status = reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
    if (reply->error() == QNetworkReply::NoError && status == 200 && store(tileKey, reply->readAll())) {
        m_failures = 0;
        m_backoffMs = 0;
        ++m_revision;
        emit revisionChanged();
        m_next.start(kSpacingMs);
        return;
    }
    // The next server gets the tile at once; once every one has failed in a row, they are
    // all busy or the network is down, and asking again at once would only fail again.
    const QString failed = QString::fromLatin1(kServers[m_server]);
    m_server = (m_server + 1) % int(std::size(kServers));
    m_queue.prepend(tileKey);
    if (++m_failures < int(std::size(kServers))) {
        // One multi-arg pass: the reply's error text quotes the URL, whose %-escapes a
        // chained arg() would take for its own markers.
        logger.info(QStringLiteral("Place names for tile %1 failed at %2 (HTTP %3) — trying %4")
                        .arg(tileName(tileKey), failed, QString::number(status),
                             QString::fromLatin1(kServers[m_server])));
        m_next.start(kSpacingMs);
        return;
    }
    m_failures = 0;
    m_backoffMs = m_backoffMs == 0 ? kMinBackoffMs : std::min(m_backoffMs * 2, kMaxBackoffMs);
    logger.warning(QStringLiteral("Place names for tile %1 failed on every server (last HTTP %2: %3) — next try in %4 s")
                       .arg(tileName(tileKey), QString::number(status), reply->errorString(),
                            QString::number(m_backoffMs / 1000)));
    m_next.start(m_backoffMs);
}

bool PlaceNames::store(quint64 tileKey, const QByteArray &json) {
    const QJsonObject root = QJsonDocument::fromJson(json).object();
    // A query that ran out of time still answers 200, with what it found so far and a
    // remark saying so.
    if (root.isEmpty() || root.value(QStringLiteral("remark")).toString().contains(QStringLiteral("error")))
        return false;

    Tile tile;
    tile.fetchedMs = QDateTime::currentMSecsSinceEpoch();
    QJsonArray rows;
    for (const QJsonValue &value : root.value(QStringLiteral("elements")).toArray()) {
        const QJsonObject element = value.toObject();
        const QJsonObject tags = element.value(QStringLiteral("tags")).toObject();
        const QString tag = tags.value(QStringLiteral("place")).toString();
        const int kind = kindOf(tag);
        // The UI is Finnish, and a bilingual place's plain name may be the Swedish one.
        QString name = tags.value(QStringLiteral("name:fi")).toString();
        if (name.isEmpty())
            name = tags.value(QStringLiteral("name")).toString();
        const QJsonObject at = element.contains(QStringLiteral("center"))
                                   ? element.value(QStringLiteral("center")).toObject()
                                   : element;
        if (kind < 0 || name.isEmpty() || !at.contains(QStringLiteral("lat")))
            continue;
        const double lat = at.value(QStringLiteral("lat")).toDouble();
        const double lon = at.value(QStringLiteral("lon")).toDouble();
        tile.places.append({name, kind, lat, lon});
        rows.append(QJsonArray{name, tag, lat, lon});
    }

    QSaveFile file(cachePath(tileKey));
    if (file.open(QIODevice::WriteOnly)) {
        const QJsonObject out{{QStringLiteral("fetched"), double(tile.fetchedMs)},
                              {QStringLiteral("places"), rows}};
        file.write(QJsonDocument(out).toJson(QJsonDocument::Compact));
        if (!file.commit())
            logger.warning(QStringLiteral("Could not write %1").arg(file.fileName()));
    }
    logger.info(QStringLiteral("Place names fetched | tile=%1 places=%2")
                    .arg(tileName(tileKey))
                    .arg(tile.places.size()));
    m_notOnDisk.remove(tileKey);
    m_tiles.insert(tileKey, tile);
    return true;
}
