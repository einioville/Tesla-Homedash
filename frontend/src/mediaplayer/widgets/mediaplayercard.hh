//
// Created by ville on 24.11.2025.
//

#ifndef GUI_PLAYER_HH
#define GUI_PLAYER_HH
#include <QFrame>
#include <QGridLayout>
#include <QPushButton>
#include <QProgressBar>
#include <QLabel>
#include <QWidget>
#include <QByteArray>
#include <QString>
#include <QColor>
#include <QGraphicsDropShadowEffect>
#include <QTimer>
#include <QSlider>
#include <QPixmap>
#include <QFutureWatcher>

/**
 * MediaplayerCard — bottom-left card showing the currently playing track:
 * album art, title, artist, progress slider, transport buttons.
 *
 * The dominant colour of the album art drives a vertical gradient
 * background. The k-means clustering used to derive that colour is
 * intentionally heavy (kept functionally identical to the original
 * implementation) and is therefore dispatched to the global thread pool
 * via QtConcurrent; the GUI thread only receives the final QColor.
 *
 * The rendered gradient is cached as a QPixmap so paintEvent is a single
 * drawPixmap call. The cache is invalidated on resize or when the dominant
 * colour changes.
 */
class MediaplayerCard : public QFrame {
    Q_OBJECT

public:
    explicit MediaplayerCard(QWidget *parent);

    QVector<QPushButton *> getButtonPointers();

    QSlider *getSlider();

public slots:
    void updateCoverArt(QPixmap cover_art_image);

    void updateSongProgress(quint32 progress);

    void updateSongDuration(quint32 duration);

    void updateSongTitle(QString name);

    void paintEvent(QPaintEvent *event) override;

    void resizeEvent(QResizeEvent *event) override;

    void updatePlayState(bool is_playing);

    void updatePauseButton();

    void updateVirtualProgress();

    void sliderMoved(int value);

    void updateArtists(QString artists);

    void updateMediaType(uint8_t media_type);

private:
    // Pure function: k-means + hue gating over the album art. Safe to invoke
    // on a worker thread; returns the dominant QColor.
    static QColor computeDominantColor(QPixmap cover_art_image);

    void rebuildBackgroundCache();

    QString base_style;
    QGridLayout *layout;
    QPushButton *skip_backward_button;
    QPushButton *pause_play_button;
    QPushButton *skip_forward_button;
    QSlider *slider;
    QLabel *title;
    QLabel *artist;
    QLabel *cover_art;
    QColor dominant_color;
    QGraphicsDropShadowEffect *shadow;
    QGraphicsDropShadowEffect *cover_shadow;
    bool is_playing = false;
    quint32 progress = 0;
    QLabel *progress_label;
    QLabel *duration_label;
    QFont time_font;
    QFont title_font;
    QFont artist_font;

    // Cover-art dedup: skip re-processing if the same QPixmap comes in twice.
    qint64 m_last_processed_key = 0;

    // Cached gradient background. Rebuilt only on resize or dominant-color
    // change to avoid per-frame QPainterPath + QLinearGradient allocation.
    QPixmap m_background_cache;
    QSize m_cached_size;
    bool m_background_dirty = true;

    // Rolling worker for dominant-color computation. Cancelled if a newer
    // cover-art update arrives before the previous worker completes.
    QFutureWatcher<QColor> *m_color_watcher = nullptr;
};

#endif //GUI_PLAYER_HH
