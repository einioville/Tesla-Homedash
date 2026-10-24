#include "mediadata.hh"

#include "../logger.hh"
#include "../protocol.hh"
#include "../serverclient.hh"

#include <QColor>
#include <QDataStream>
#include <QHash>
#include <QIODevice>
#include <QNetworkAccessManager>
#include <QNetworkDiskCache>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QStandardPaths>
#include <QVector3D>
#include <QtConcurrent>

#include <algorithm>
#include <cmath>
#include <limits>
#include <random>
#include <utility>

namespace {
const Logger logger = Logger::get("media");

// A cover is ~25-150 kB, so this keeps several hundred.
constexpr qint64 kCoverCacheBytes = 50LL * 1024 * 1024;
// Without a byte for this long, a cover fetch gives up.
constexpr int kCoverTimeoutMs = 20 * 1000;

// A payload that is one len(2B) + UTF-8 string; false (out untouched) when truncated.
bool readLenString(const QByteArray &payload, QString &out) {
    QDataStream stream(payload);
    stream.setByteOrder(QDataStream::BigEndian);
    return protocol::readString(stream, out);
}

quint32 readU32(const QByteArray &payload) {
    QDataStream stream(payload);
    stream.setByteOrder(QDataStream::BigEndian);
    quint32 value = 0;
    stream >> value;
    return value;
}
}  // namespace

MediaData::MediaData(ServerClient *server, std::shared_ptr<MediaImageCache> cache, QObject *parent)
    : QObject(parent), m_server(server), m_cache(std::move(cache)),
      m_network(new QNetworkAccessManager(this)) {
    auto *diskCache = new QNetworkDiskCache(m_network);
    diskCache->setCacheDirectory(QStandardPaths::writableLocation(QStandardPaths::GenericCacheLocation)
                                 + QStringLiteral("/Tesla-Homedash/covers"));
    diskCache->setMaximumCacheSize(kCoverCacheBytes);
    m_network->setCache(diskCache);

    connect(server, &ServerClient::packetReceived, this, &MediaData::onPacket);
    // The backend forgets a watcher with its connection.
    connect(server, &ServerClient::connectedChanged, this, [this]() {
        if (m_server->connected() && spectrumWatched()) {
            sendSpectrumWatch();
        }
    });
}

void MediaData::onPacket(quint8 type, const QByteArray &payload) {
    switch (type) {
        case protocol::MEDIA_STREAM_IMAGE_URL: {
            QString value;
            if (readLenString(payload, value)) {
                fetchCover(QUrl(value));
            }
            break;
        }
        case protocol::MEDIA_STREAM_NAME: {
            QString value;
            if (readLenString(payload, value)) {
                setTitle(value);
            }
            break;
        }
        case protocol::MEDIA_STREAM_ARTISTS: {
            QString value;
            if (readLenString(payload, value)) {
                setArtists(value);
            }
            break;
        }
        case protocol::MEDIA_STREAM_PROGRESS:
            if (payload.size() >= 4) {
                setProgressMs(static_cast<int>(readU32(payload)));
            }
            break;
        case protocol::MEDIA_STREAM_DURATION:
            if (payload.size() >= 4) {
                setDurationMs(static_cast<int>(readU32(payload)));
            }
            break;
        case protocol::MEDIA_IS_PLAYING:
            if (!payload.isEmpty()) {
                setIsPlaying(static_cast<quint8>(payload.at(0)) == 1);
            }
            break;
        case protocol::MEDIA_STREAM_TYPE:
            if (!payload.isEmpty()) {
                setMediaType(static_cast<quint8>(payload.at(0)));
            }
            break;
        case protocol::MEDIA_NEXT: {
            QDataStream stream(payload);
            stream.setByteOrder(QDataStream::BigEndian);
            QString title, artists, imageUrl;
            if (protocol::readString(stream, title) && protocol::readString(stream, artists)
                    && protocol::readString(stream, imageUrl)) {
                setNext(title, artists, imageUrl);
            } else {
                logger.warning(QStringLiteral("MEDIA_NEXT truncated | bytes=%1").arg(payload.size()));
            }
            break;
        }
        case protocol::MEDIA_SPECTRUM: {
            const int count = payload.isEmpty() ? 0 : static_cast<quint8>(payload.at(0));
            if (!spectrumWatched() || payload.size() < 1 + count) {
                break;
            }
            QList<qreal> levels;
            levels.reserve(count);
            for (int i = 1; i <= count; i++) {
                levels.append(static_cast<quint8>(payload.at(i)) / 255.0);
            }
            setSpectrum(levels);
            break;
        }
        default:
            break;  // not ours — other datahandlers consume their own types
    }
}

void MediaData::fetchCover(const QUrl &url) {
    if (!url.isValid()) {
        return;
    }
    if (m_coverReply) {
        if (m_coverReply->request().url() == url) {
            return;
        }
        QNetworkReply *older = std::exchange(m_coverReply, nullptr);
        older->disconnect(this);
        older->abort();
        older->deleteLater();
    }
    // The snapshot after a reconnect, or the next track off the same album.
    if (url == m_coverUrl) {
        return;
    }

    QNetworkRequest request(url);
    request.setHeader(QNetworkRequest::UserAgentHeader, QStringLiteral("Tesla-Homedash/1.0"));
    request.setTransferTimeout(kCoverTimeoutMs);
    // A cover URL names one picture for good (Spotify's are content hashes), so a
    // cached copy is served without asking the server again.
    request.setAttribute(QNetworkRequest::CacheLoadControlAttribute, QNetworkRequest::PreferCache);
    QNetworkReply *reply = m_network->get(request);
    m_coverReply = reply;
    connect(reply, &QNetworkReply::finished, this, [this, reply]() {
        reply->deleteLater();
        m_coverReply = nullptr;
        // The picture shown stays, as it would for a cover the backend could not name.
        if (reply->error() != QNetworkReply::NoError) {
            logger.warning(QStringLiteral("Cover art fetch failed | url=%1 error=%2")
                               .arg(reply->request().url().toString(), reply->errorString()));
            return;
        }
        m_coverUrl = reply->request().url();
        decodeCoverArt(reply->readAll());
    });
}

void MediaData::decodeCoverArt(const QByteArray &bytes) {
    // Two URLs can serve the picture already shown.
    const quint64 hash = qHash(bytes);
    if (hash == m_lastCoverHash) {
        return;
    }
    m_lastCoverHash = hash;

    // Drop any in-flight decode — its result would be stale by the time it lands.
    if (m_coverWatcher) {
        m_coverWatcher->disconnect();
        m_coverWatcher->cancel();
        m_coverWatcher->deleteLater();
        m_coverWatcher = nullptr;
    }

    const QString id = QString::number(hash);
    m_coverWatcher = new QFutureWatcher<DecodedCover>(this);
    connect(m_coverWatcher, &QFutureWatcher<DecodedCover>::finished, this, [this, id]() {
        const DecodedCover result = m_coverWatcher->result();
        m_coverWatcher->deleteLater();
        m_coverWatcher = nullptr;
        if (result.image.isNull()) {
            logger.warning(QStringLiteral("Cover art decode produced a null image"));
            return;
        }
        m_cache->put(id, result.image);
        m_coverArtId = QStringLiteral("image://media/") + id;
        emit coverArtIdChanged();
        setDominantColor(result.color);
        setPalette(result.palette);
    });

    // Decode to QImage (thread-safe) off the GUI thread — never a QPixmap on a
    // worker (QPixmap is GUI-thread-only). The same worker pass also runs the
    // k-means dominant-colour extraction so the card gradient never blocks the
    // GUI thread. The provider serves the QImage; the colours drive the gradients.
    m_coverWatcher->setFuture(QtConcurrent::run([bytes]() {
        DecodedCover out;
        out.image.loadFromData(bytes);
        computeCoverColors(out);
        return out;
    }));
}

void MediaData::setTitle(const QString &value) {
    if (m_title == value) {
        return;
    }
    m_title = value;
    emit titleChanged();
    // A new track: what was next is now playing, or was skipped past.
    setNext({}, {}, {});
}

void MediaData::setArtists(const QString &value) {
    if (m_artists == value) {
        return;
    }
    m_artists = value;
    emit artistsChanged();
}

void MediaData::setProgressMs(int value) {
    if (m_progressMs == value) {
        return;
    }
    m_progressMs = value;
    emit progressMsChanged();
}

void MediaData::setDurationMs(int value) {
    if (m_durationMs == value) {
        return;
    }
    m_durationMs = value;
    emit durationMsChanged();
    // Two tracks can share a title (a cover, a remaster); rarely a length as well.
    setNext({}, {}, {});
}

void MediaData::setIsPlaying(bool value) {
    if (m_isPlaying == value) {
        return;
    }
    m_isPlaying = value;
    emit isPlayingChanged();
}

void MediaData::setMediaType(int value) {
    if (m_mediaType == value) {
        return;
    }
    m_mediaType = value;
    emit mediaTypeChanged();

    // Radio only sends name/image/play-state, so clear the Spotify-only fields
    // on a switch to radio — otherwise stale track metadata bleeds across.
    if (value == protocol::MEDIA_TYPE_RADIO) {
        setArtists(QString());
        setProgressMs(0);
        setDurationMs(0);
    }
}

void MediaData::skipForward() {
    m_server->sendPacket(protocol::frame(protocol::MEDIA_SKIP));
    logger.info(QStringLiteral("Skip forward command issued"));
}

void MediaData::skipBackward() {
    m_server->sendPacket(protocol::frame(protocol::MEDIA_SKIP_BACKWARD));
    logger.info(QStringLiteral("Skip backward command issued"));
}

void MediaData::pausePlay() {
    m_server->sendPacket(protocol::frame(protocol::MEDIA_PAUSE_PLAY));
    logger.info(QStringLiteral("Pause/play command issued"));
}

void MediaData::setProgress(int ms) {
    QByteArray payload;
    QDataStream stream(&payload, QIODevice::WriteOnly);
    stream.setByteOrder(QDataStream::BigEndian);
    stream << static_cast<quint32>(ms);
    m_server->sendPacket(protocol::frame(protocol::MEDIA_SET_PROGRESS, payload));
    logger.info(QStringLiteral("Seek command issued | position=%1ms").arg(ms));
}

void MediaData::requestNext() {
    m_server->sendPacket(protocol::frame(protocol::MEDIA_GET_NEXT));
    logger.debug(QStringLiteral("Next track requested"));
}

void MediaData::setNext(const QString &title, const QString &artists, const QString &imageUrl) {
    if (m_nextTitle == title && m_nextArtists == artists && m_nextImageUrl == imageUrl) {
        return;
    }
    m_nextTitle = title;
    m_nextArtists = artists;
    m_nextImageUrl = imageUrl;
    emit nextChanged();
}

void MediaData::setDominantColor(const QColor &value) {
    if (m_dominantColor == value) {
        return;
    }
    m_dominantColor = value;
    emit dominantColorChanged();
}

void MediaData::setPalette(const QVariantList &value) {
    if (m_palette == value) {
        return;
    }
    m_palette = value;
    emit paletteChanged();
}

void MediaData::setSpectrum(const QList<qreal> &value) {
    m_spectrum = value;
    emit spectrumChanged();
}

void MediaData::retainSpectrum() {
    if (++m_spectrumWatchers > 1) {
        return;
    }
    if (m_server->connected()) {
        sendSpectrumWatch();
    }
}

void MediaData::releaseSpectrum() {
    if (m_spectrumWatchers == 0) {
        logger.warning(QStringLiteral("releaseSpectrum() without a matching retainSpectrum()"));
        return;
    }
    if (--m_spectrumWatchers > 0) {
        return;
    }
    if (m_server->connected()) {
        sendSpectrumWatch();
    }
    setSpectrum({});
}

void MediaData::sendSpectrumWatch() {
    m_server->sendPacket(protocol::frame(protocol::MEDIA_SPECTRUM_WATCH,
                                         QByteArray(1, spectrumWatched() ? 1 : 0)));
}

void MediaData::computeCoverColors(DecodedCover &cover) {
    // k-means on the album art with a hue/value gate that biases against
    // yellow and brown. Ported verbatim from the Widgets MediaPlayerCard
    // (RNG seed 69420, gating, scoring) — these inputs define the dashboard's
    // visual identity and must not change; the palette is drawn from the same
    // clusters after the dominant colour is chosen. Runs on a worker thread.
    const QImage image = cover.image.convertToFormat(QImage::Format_RGB888);

    const int img_width = image.width();
    const int img_height = image.height();
    int k = 5;
    QVector<QVector3D> samples;

    auto scan = [&](bool vibrant_only) {
        samples.clear();
        for (int y = 0; y < img_height; y++) {
            const uchar *line = image.constScanLine(y);
            for (int x = 0; x < img_width; x++) {
                const float r = line[x * 3];
                const float g = line[x * 3 + 1];
                const float b = line[x * 3 + 2];

                if (vibrant_only) {
                    const float max_c = std::max({r, g, b});
                    const float min_c = std::min({r, g, b});
                    const float v = max_c / 255.0f;
                    const float s = (max_c > 0) ? (max_c - min_c) / max_c : 0.0f;
                    if (s < 0.35f || v < 0.25f || v > 0.95f) continue;
                }

                samples.emplace_back(r, g, b);
            }
        }
    };

    scan(true);
    if (samples.size() < k) {
        scan(false);
    }

    // Degenerate art (e.g. a 0-pixel decode) leaves no samples. Bail out with
    // the default gradient blue rather than building a distribution over an
    // empty range (size()-1 underflows → out-of-bounds indexing / UB).
    if (samples.isEmpty()) {
        cover.color = QColor(0x1E, 0x3A, 0x8A);
        return;
    }

    QVector<QVector3D> centers;
    centers.reserve(k);

    std::mt19937 random_engine{69420};
    std::uniform_int_distribution<> distribution(0, samples.size() - 1);

    centers.push_back(samples[distribution(random_engine)]);
    for (int i = 1; i < k; i++) {
        QVector<float> distances(samples.size());
        float total = 0.0f;
        for (int j = 0; j < samples.size(); j++) {
            float min_dist = std::numeric_limits<float>::max();
            for (const QVector3D &c : centers) {
                float d = (samples[j] - c).lengthSquared();
                if (d < min_dist) min_dist = d;
            }
            distances[j] = min_dist;
            total += min_dist;
        }
        std::uniform_real_distribution<float> real_dist(0.0f, total);
        float threshold = real_dist(random_engine);
        float cumulative = 0.0f;
        int chosen = samples.size() - 1;
        for (int j = 0; j < samples.size(); j++) {
            cumulative += distances[j];
            if (cumulative >= threshold) { chosen = j; break; }
        }
        centers.push_back(samples[chosen]);
    }

    QVector<int> counts(k, 0);

    for (int i = 0; i < 10; i++) {
        QVector<QVector3D> new_centers(k, QVector3D(0, 0, 0));
        std::fill(counts.begin(), counts.end(), 0);

        for (const QVector3D &pixel : samples) {
            float best_distance = std::numeric_limits<float>::max();
            int best_index = 0;

            for (int ci = 0; ci < k; ci++) {
                float distance = (pixel - centers[ci]).lengthSquared();
                if (distance < best_distance) {
                    best_distance = distance;
                    best_index = ci;
                }
            }

            new_centers[best_index] += pixel;
            counts[best_index]++;
        }

        for (int ci = 0; ci < k; ci++) {
            if (counts[ci] > 0) {
                new_centers[ci] /= counts[ci];
            } else {
                new_centers[ci] = samples[distribution(random_engine)];
            }
        }

        centers = new_centers;
    }

    struct ClusterInfo {
        int count;
        QVector3D center;
    };

    QVector<ClusterInfo> info;
    info.reserve(k);

    for (int ci = 0; ci < k; ci++) {
        info.push_back({counts[ci], centers[ci]});
    }

    std::sort(info.begin(), info.end(), [](const ClusterInfo &a, const ClusterInfo &b) {
        return a.count > b.count;
    });

    auto color_of = [](const ClusterInfo &c) {
        return QColor(
            std::clamp<int>(c.center.x(), 0, 255),
            std::clamp<int>(c.center.y(), 0, 255),
            std::clamp<int>(c.center.z(), 0, 255)
        );
    };
    auto shunned = [](const QColor &color) {
        const int hue = color.hsvHue();
        if (hue == -1)
            return false;
        return (hue >= 45 && hue <= 65)                               // yellow (light or bright)
            || (hue >= 10 && hue <= 40 && color.valueF() < 0.60f);    // brown
    };

    int best_index = 0;
    float best_score = -1.0f;

    for (int i = 0; i < info.size(); i++) {
        const QColor color = color_of(info[i]);
        float score = color.hsvSaturationF() * color.valueF();
        if (shunned(color))
            score *= 0.2f;
        if (score > best_score) {
            best_score = score;
            best_index = i;
        }
    }

    cover.color = color_of(info[best_index]);

    // The rest of the palette, largest share first. Each colour takes a part of the
    // backdrop, so a speck in the art (under min_share of the samples) does not get
    // one; nor does a grey, a near-black, or a yellow or brown, which darken to mud.
    // k-means splits a large flat area into near-twins (JPEG noise), so a cluster
    // within min_distance (RGB, 0-255) of a colour already taken is the same colour.
    constexpr float min_share = 0.1f;
    constexpr float min_distance = 60.0f;
    constexpr int palette_size = 3;
    QVector<QVector3D> taken{info[best_index].center};
    cover.palette = {cover.color};
    for (int i = 0; i < info.size() && cover.palette.size() < palette_size; i++) {
        const QColor color = color_of(info[i]);
        const bool twin = std::any_of(taken.cbegin(), taken.cend(), [&](const QVector3D &t) {
            return (t - info[i].center).length() < min_distance;
        });
        if (twin || info[i].count < min_share * samples.size()
                || color.hsvSaturationF() < 0.2f || color.valueF() < 0.15f || shunned(color))
            continue;
        taken.append(info[i].center);
        cover.palette.append(color);
    }
}
