//
// Created by ville on 24.11.2025.
//

#ifndef GUI_SPOTIFYDATAHANDLER_HH
#define GUI_SPOTIFYDATAHANDLER_HH
#include <QObject>
#include <QByteArray>
#include "../widgets/mediaplayercard.hh"
#include <QPixmap>

class MediaplayerDataHandler : public QObject {
    Q_OBJECT

public:
    explicit MediaplayerDataHandler(QObject *parent);

    void connectPlayer(MediaplayerCard *player);

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

    void onCovertArtUpdate(QPixmap cover_art_image);

    void onSongProgressUpdate(quint32 progress);

    void onSongDurationUpdate(quint32 duration);

    void onSongTitleUpdate(QString name);

    void onPlayStateUpdate(bool is_playing);

    void onArtistsUpdate(QString artists);

    void onMediaTypeUpdate(uint8_t media_type);

private:
    QSlider *slider;
};
#endif //GUI_SPOTIFYDATAHANDLER_HH
