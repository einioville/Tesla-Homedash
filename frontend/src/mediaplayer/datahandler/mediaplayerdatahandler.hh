//
// Created by ville on 24.11.2025.
//

#ifndef GUI_MEDIAPLAYERDATAHANDLER_HH
#define GUI_MEDIAPLAYERDATAHANDLER_HH
#include <QObject>
#include <QByteArray>
#include "../widgets/mediaplayercard.hh"
#include <QImage>
#include <QFutureWatcher>

/**
 * MediaPlayerDataHandler — parses incoming media-player packets (cover
 * art, song title/artists, progress/duration, play state, media type) and
 * re-emits each as a Qt signal. Also formats outbound transport commands
 * (skip / pause-play / seek) and emits them via onSpotifyRequest.
 *
 * Cover-art packets are deduplicated by content hash and decoded on the
 * global thread pool so the GUI thread is never blocked by JPEG/PNG decode.
 */
class MediaPlayerDataHandler : public QObject {
    Q_OBJECT

public:
    explicit MediaPlayerDataHandler(QObject *parent);

    void connectPlayer(MediaPlayerCard *player);

public slots:
    void processCovertArtData(const QByteArray &packet);

    void processSongProgress(const QByteArray &packet);

    void processSongDuration(const QByteArray &packet);

    void processSongTitle(const QByteArray &packet);

    void processPlayState(const QByteArray &packet);

    void processArtists(const QByteArray &packet);

    void processMediaType(const QByteArray &packet);

    void skipBackwards();

    void skipForwards();

    void pausePlay();

    void setProgress();

signals:
    void onSpotifyRequest(const QByteArray &packet);

    void onCovertArtUpdate(QImage cover_art_image);

    void onSongProgressUpdate(quint32 progress);

    void onSongDurationUpdate(quint32 duration);

    void onSongTitleUpdate(QString name);

    void onPlayStateUpdate(bool is_playing);

    void onArtistsUpdate(QString artists);

    void onMediaTypeUpdate(uint8_t media_type);

private:
    QSlider *slider;

    // Cover-art dedup + async decode. Repeated cover-art packets for the same
    // image are common (Spotify polls every few seconds); we hash the packet
    // bytes and skip decoding entirely when the hash matches. Fresh packets
    // are decoded on the global thread pool so the GUI thread is never
    // blocked by JPEG/PNG decode.
    quint64 m_last_cover_hash = 0;
    // Decoded off the GUI thread as a QImage (NOT QPixmap): QPixmap is a paint
    // device and must only be constructed/used on the GUI thread. The QImage is
    // converted to a QPixmap on the GUI thread by MediaPlayerCard.
    QFutureWatcher<QImage> *m_cover_watcher = nullptr;
};
#endif //GUI_MEDIAPLAYERDATAHANDLER_HH
