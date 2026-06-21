#ifndef FRONTEND_V2_MEDIADATA_HH
#define FRONTEND_V2_MEDIADATA_HH

#include <QByteArray>
#include <QColor>
#include <QFutureWatcher>
#include <QImage>
#include <QObject>
#include <QString>
#include <memory>

#include "mediaimagecache.hh"

class ServerClient;

// Result of the off-thread cover-art decode: the image plus its k-means
// dominant colour, computed together in one worker pass.
struct DecodedCover {
    QImage image;
    QColor color;
};

/**
 * MediaData — the single media datahandler, exposed to QML as the `Media`
 * singleton. Assembles a coherent "now playing" object from the independent
 * media packets (title, artists, progress, duration, play-state, media-type)
 * and bridges cover art to QML through a MediaImageProvider.
 *
 * Cover art is deduped by content hash and decoded off the GUI thread (to a
 * QImage, never a QPixmap on a worker); a newer image supersedes an in-flight
 * decode. isPlaying follows the server's echo, not the button press.
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
    // Dominant colour of the current cover art (k-means), drives the card
    // gradient. A deep Tesla blue until the first art is decoded.
    Q_PROPERTY(QColor dominantColor READ dominantColor NOTIFY dominantColorChanged)

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
    QColor dominantColor() const { return m_dominantColor; }

    // Transport controls (frontend -> backend). isPlaying follows the server's
    // echo, not the button press, so pausePlay() does not flip it locally.
    Q_INVOKABLE void skipForward();
    Q_INVOKABLE void skipBackward();
    Q_INVOKABLE void pausePlay();
    Q_INVOKABLE void setProgress(int ms);

signals:
    void titleChanged();
    void artistsChanged();
    void progressMsChanged();
    void durationMsChanged();
    void isPlayingChanged();
    void mediaTypeChanged();
    void coverArtIdChanged();
    void dominantColorChanged();

private slots:
    void onPacket(quint8 type, const QByteArray &payload);

private:
    void decodeCoverArt(const QByteArray &packet);
    void setTitle(const QString &value);
    void setArtists(const QString &value);
    void setProgressMs(int value);
    void setDurationMs(int value);
    void setIsPlaying(bool value);
    void setMediaType(int value);
    void setDominantColor(const QColor &value);

    // k-means dominant-colour extraction (RNG seed + hue/value gating preserved
    // verbatim from the Widgets MediaPlayerCard — it defines the visual identity).
    static QColor computeDominantColor(const QImage &image);

    ServerClient *m_server;
    std::shared_ptr<MediaImageCache> m_cache;

    QFutureWatcher<DecodedCover> *m_coverWatcher = nullptr;
    quint64 m_lastCoverHash = 0;

    QString m_title;
    QString m_artists;
    int m_progressMs = 0;
    int m_durationMs = 0;
    bool m_isPlaying = false;
    int m_mediaType = 0;
    QString m_coverArtId;
    QColor m_dominantColor = QColor(0x1E, 0x3A, 0x8A);
};

#endif  // FRONTEND_V2_MEDIADATA_HH
