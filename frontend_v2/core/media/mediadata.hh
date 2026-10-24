#ifndef FRONTEND_V2_MEDIADATA_HH
#define FRONTEND_V2_MEDIADATA_HH

#include <QByteArray>
#include <QColor>
#include <QElapsedTimer>
#include <QImage>
#include <QHash>
#include <QList>
#include <QObject>
#include <QSet>
#include <QString>
#include <QUrl>
#include <QVariantList>
#include <memory>

#include "mediaimagecache.hh"

class QNetworkAccessManager;
class ServerClient;

// Result of the off-thread cover-art decode: the image, its content-hash id and
// its k-means colours, computed together in one worker pass.
struct DecodedCover {
    QString id;
    QImage image;
    QColor color;
    QVariantList palette;
};

/**
 * MediaData — the single media datahandler, exposed to QML as the `Media`
 * singleton. Assembles a coherent "now playing" object from the independent
 * media packets (title, artists, progress, duration, play-state, media-type)
 * and bridges cover art to QML through a MediaImageProvider.
 *
 * Cover art arrives as a URL (MEDIA_STREAM_IMAGE_URL) and is fetched here, through
 * a disk cache, and decoded off the GUI thread. A few decoded covers stay in
 * memory, among them the ones a skip would most likely bring (coverAfterSkip).
 */
class MediaData : public QObject {
    Q_OBJECT
    Q_PROPERTY(QString title READ title NOTIFY titleChanged)
    Q_PROPERTY(QString artists READ artists NOTIFY artistsChanged)
    Q_PROPERTY(int progressMs READ progressMs NOTIFY progressMsChanged)
    Q_PROPERTY(int durationMs READ durationMs NOTIFY durationMsChanged)
    Q_PROPERTY(bool isPlaying READ isPlaying NOTIFY isPlayingChanged)
    // 0 = none, 1 = radio, 2 = spotify (protocol MEDIA_TYPE_* values).
    Q_PROPERTY(int mediaType READ mediaType NOTIFY mediaTypeChanged)
    // image://media/<hash> for the current art, or "" before the first image.
    Q_PROPERTY(QString coverArtId READ coverArtId NOTIFY coverArtIdChanged)
    // Which way the latest cover change went, for the Media view's slide: -1 when
    // skipBackward() was pressed shortly before it (the previous track or station),
    // 1 otherwise. Set with coverArtId, so a handler of either reads both new.
    Q_PROPERTY(int coverDirection READ coverDirection NOTIFY coverArtIdChanged)
    // Dominant colour of the current cover art (k-means), drives the card
    // gradient. A deep Tesla blue until the first art is decoded.
    Q_PROPERTY(QColor dominantColor READ dominantColor NOTIFY dominantColorChanged)
    // The cover's main colours for the backdrop (MediaBackdrop): dominantColor, then
    // up to two more that each cover a fair share of the art. Empty until the
    // first art is decoded.
    Q_PROPERTY(QVariantList palette READ palette NOTIFY paletteChanged)
    // What plays after the current track, as the backend last answered requestNext();
    // all empty before an answer, when nothing is queued, and from a track change
    // until the next answer. The cover is a URL the Media view's card loads itself.
    Q_PROPERTY(QString nextTitle READ nextTitle NOTIFY nextChanged)
    Q_PROPERTY(QString nextArtists READ nextArtists NOTIFY nextChanged)
    Q_PROPERTY(QString nextImageUrl READ nextImageUrl NOTIFY nextChanged)

public:
    MediaData(ServerClient *server, std::shared_ptr<MediaImageCache> cache,
              QObject *parent = nullptr);

    QString title() const { return m_title; }
    QString artists() const { return m_artists; }
    int progressMs() const { return m_progressMs; }
    int durationMs() const { return m_durationMs; }
    bool isPlaying() const { return m_isPlaying; }
    int mediaType() const { return m_mediaType; }
    QString coverArtId() const { return m_coverArtId; }
    int coverDirection() const { return m_coverDirection; }
    QColor dominantColor() const { return m_dominantColor; }
    QVariantList palette() const { return m_palette; }
    QString nextTitle() const { return m_nextTitle; }
    QString nextArtists() const { return m_nextArtists; }
    QString nextImageUrl() const { return m_nextImageUrl; }
    // The spectrum of what is playing: band levels 0-1, low to high frequency, new
    // about 30 times a second (spectrumChanged) while it is watched and something
    // plays, a flat frame when it stops. The backend records only while some display
    // watches. Read by SpectrumLevels, MediaSpectrum's C++ half.
    QList<qreal> spectrum() const { return m_spectrum; }
    bool spectrumWatched() const { return m_spectrumWatchers > 0; }

    // Counted like SystemHistory's retain(): the Media view and the equalizer
    // each draw one, and a view coming live overlaps one going.
    void retainSpectrum();
    void releaseSpectrum();

    // Transport controls (frontend -> backend). isPlaying follows the server's
    // echo, not the button press, so pausePlay() does not flip it locally.
    Q_INVOKABLE void skipForward();
    Q_INVOKABLE void skipBackward();
    Q_INVOKABLE void pausePlay();
    Q_INVOKABLE void setProgress(int ms);
    // Asks the backend what plays next; the answer lands in the next* properties.
    // Spotify's queue is read per ask, so a caller asks once a track, when it needs it.
    Q_INVOKABLE void requestNext();
    // The cover a skip that way (1 forward, -1 back) will most likely bring, as a
    // coverArtId, when it is decoded in memory and can be shown at once; "" when it
    // is not known or not loaded. The current cover when the skip keeps it: back
    // more than 5 s into a Spotify track starts it over, and a track off the same
    // album shares it.
    Q_INVOKABLE QString coverAfterSkip(int direction) const;

signals:
    void titleChanged();
    void artistsChanged();
    void progressMsChanged();
    void durationMsChanged();
    void isPlayingChanged();
    void mediaTypeChanged();
    void coverArtIdChanged();
    void dominantColorChanged();
    void paletteChanged();
    void nextChanged();
    void spectrumChanged();

private slots:
    void onPacket(quint8 type, const QByteArray &payload);

private:
    // A decoded cover kept in memory; its picture is in MediaImageCache under `id`.
    struct MemoryCover {
        QString id;
        QColor color;
        QVariantList palette;
    };

    void showCoverFrom(const QUrl &url);
    void loadCover(const QUrl &url);
    void keepCover(const QUrl &url, const DecodedCover &cover);
    void showCover(const QUrl &url);
    void learnNeighbours(const QUrl &url);
    QUrl neighbourCoverUrl(int direction) const;
    void loadNeighbourCovers();
    int changeDirection() const;
    void setTitle(const QString &value);
    void setArtists(const QString &value);
    void setProgressMs(int value);
    void setDurationMs(int value);
    void setIsPlaying(bool value);
    void setMediaType(int value);
    void setDominantColor(const QColor &value);
    void setPalette(const QVariantList &value);
    void setNext(const QString &title, const QString &artists, const QString &imageUrl);
    void setSpectrum(const QList<qreal> &value);
    void sendSpectrumWatch();

    // k-means colour extraction from cover.image into cover.color and
    // cover.palette, run on the cover-art decode worker.
    static void computeCoverColors(DecodedCover &cover);

    ServerClient *m_server;
    std::shared_ptr<MediaImageCache> m_cache;

    QNetworkAccessManager *m_network;
    // The URL whose picture is shown, and the one the backend named last, shown
    // as soon as it is loaded.
    QUrl m_coverUrl;
    QUrl m_wantedCoverUrl;
    QHash<QUrl, MemoryCover> m_covers;
    // m_covers' URLs, least recently shown or loaded first.
    QList<QUrl> m_coverUse;
    // Being fetched or decoded.
    QSet<QUrl> m_coverLoads;

    // The item (title + artists) the shown cover belongs to, its player, and the
    // covers seen either side of each item: a cover named under a new item
    // records the two as neighbours, the way coverDirection says it went.
    QString m_itemKey;
    int m_itemType = 0;
    QUrl m_itemCoverUrl;
    QHash<QString, QUrl> m_nextCovers;
    QHash<QString, QUrl> m_previousCovers;

    QString m_title;
    QString m_artists;
    int m_progressMs = 0;
    int m_durationMs = 0;
    bool m_isPlaying = false;
    int m_mediaType = 0;
    QString m_coverArtId;
    int m_coverDirection = 1;
    // Running from a skipBackward() until the cover change it brings.
    QElapsedTimer m_skipBackward;
    QColor m_dominantColor = QColor(0x1E, 0x3A, 0x8A);
    QVariantList m_palette;
    QString m_nextTitle;
    QString m_nextArtists;
    QString m_nextImageUrl;
    QList<qreal> m_spectrum;
    int m_spectrumWatchers = 0;
};

#endif  // FRONTEND_V2_MEDIADATA_HH
