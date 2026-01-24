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

    void updatePlayState(bool is_playing);

    void updatePauseButton();

    void updateVirtualProgress();

    void sliderMoved(int value);

    void updateArtists(QString artists);

    void updateMediaType(uint8_t media_type);

private:
    void setBackgroundColor(const QPixmap *cover_art_image);

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
};

#endif //GUI_PLAYER_HH
