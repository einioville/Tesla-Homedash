//
// Created by ville on 24.11.2025.
//

#include "mediaplayercard.hh"
#include <QIcon>
#include <QSizePolicy>
#include <QStyleFactory>
#include <QPixmap>
#include <QImage>
#include <QVector>
#include <QVector3D>
#include <QColor>
#include <random>
#include <cmath>
#include <limits>
#include <QFile>
#include <QPainter>
#include <QPainterPath>
#include <QLinearGradient>
#include <QTime>
#include <QFont>

MediaplayerCard::MediaplayerCard(QWidget *parent) : QFrame(parent) {
    setObjectName("spotifyplayer");

    time_font = QFont("Gotham Rounded Medium", 8);
    title_font = QFont("Gotham Rounded Medium", 15);

    layout = new QGridLayout(this);
    layout->setContentsMargins(10, 10, 10, 10);

    cover_art = new QLabel(this);
    cover_art->setAttribute(Qt::WA_TranslucentBackground);
    cover_art->setObjectName("coverart");
    cover_art->setFixedHeight(160);
    cover_art->setFixedWidth(160);
    cover_art->setAlignment(Qt::AlignCenter);
    layout->addWidget(cover_art, 0, 0, 6, 5, Qt::AlignCenter);

    title = new QLabel(this);
    title->setFont(title_font);
    title->setAttribute(Qt::WA_TranslucentBackground);
    title->setObjectName("title");
    title->setAlignment(Qt::AlignCenter);
    title->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Preferred);
    layout->addWidget(title, 6, 0, 1, 5, Qt::AlignCenter);

    artist = new QLabel(this);
    artist->setAttribute(Qt::WA_TranslucentBackground);
    artist->setObjectName("title");
    artist->setFont(time_font);
    artist->setObjectName("title");
    artist->setAlignment(Qt::AlignCenter);
    artist->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Preferred);
    layout->addWidget(artist, 7, 0, 1, 5, Qt::AlignCenter);
    artist->hide();

    skip_backward_button = new QPushButton(this);
    skip_backward_button->setAttribute(Qt::WA_TranslucentBackground);
    skip_backward_button->setObjectName("spotifybutton");
    skip_backward_button->setFixedWidth(36);
    skip_backward_button->setFixedHeight(36);
    skip_backward_button->setIcon(QIcon(":/resources/icons/skip_backward.svg"));
    skip_backward_button->setIconSize(skip_backward_button->size());
    layout->addWidget(skip_backward_button, 8, 1, 1, 1, Qt::AlignCenter);

    pause_play_button = new QPushButton(this);
    pause_play_button->setAttribute(Qt::WA_TranslucentBackground);
    pause_play_button->setObjectName("spotifybutton");
    pause_play_button->setFixedWidth(36);
    pause_play_button->setFixedHeight(36);
    pause_play_button->setIcon(QIcon(":/resources/icons/pause.svg"));
    pause_play_button->setIconSize(pause_play_button->size());
    //connect(pause_play_button, &QPushButton::clicked, this, &MediaplayerCard::updatePauseButton);
    layout->addWidget(pause_play_button, 8, 2, 1, 1, Qt::AlignCenter);

    skip_forward_button = new QPushButton(this);
    skip_forward_button->setAttribute(Qt::WA_TranslucentBackground);
    skip_forward_button->setObjectName("spotifybutton");
    skip_forward_button->setFixedWidth(36);
    skip_forward_button->setFixedHeight(36);
    skip_forward_button->setIcon(QIcon(":/resources/icons/skip_forward.svg"));
    skip_forward_button->setIconSize(skip_forward_button->size());
    layout->addWidget(skip_forward_button, 8, 3, 1, 1, Qt::AlignCenter);

    slider = new QSlider(this);
    slider->setObjectName("spotifyslider");
    slider->setOrientation(Qt::Horizontal);
    layout->addWidget(slider, 9, 0, 1, 5, Qt::AlignVCenter);
    slider->hide();

    progress_label = new QLabel(this);
    progress_label->setFixedHeight(8);
    progress_label->setFont(time_font);
    progress_label->setAttribute(Qt::WA_TranslucentBackground);
    progress_label->setAlignment(Qt::AlignVCenter | Qt::AlignLeft);
    progress_label->setObjectName("timelabel");
    layout->addWidget(progress_label, 10, 0, Qt::AlignVCenter | Qt::AlignLeft);
    progress_label->hide();

    duration_label = new QLabel(this);
    duration_label->setFixedHeight(8);
    duration_label->setFont(time_font);
    duration_label->setAttribute(Qt::WA_TranslucentBackground);
    duration_label->setAlignment(Qt::AlignVCenter | Qt::AlignRight);
    duration_label->setObjectName("timelabel");
    layout->addWidget(duration_label, 10, 4, Qt::AlignVCenter | Qt::AlignRight);
    duration_label->hide();

    QFile style(":/resources/styles/spotifyplayer.qss");
    if (style.open(QFile::ReadOnly | QFile::Text)) {
        QTextStream stream(&style);
        base_style = stream.readAll();
        setStyleSheet(base_style);
    }

    shadow = new QGraphicsDropShadowEffect(this);
    shadow->setBlurRadius(50);
    shadow->setXOffset(10);
    shadow->setYOffset(10);
    shadow->setColor(QColor(0, 0, 0, 150));
    setGraphicsEffect(shadow);

    cover_shadow = new QGraphicsDropShadowEffect(cover_art);
    cover_shadow->setBlurRadius(25);
    cover_shadow->setXOffset(0);
    cover_shadow->setYOffset(0);
    cover_shadow->setColor(QColor(0, 0, 0, 255));
    cover_art->setGraphicsEffect(cover_shadow);

    connect(slider, &QSlider::valueChanged, this, &MediaplayerCard::sliderMoved);
}

void MediaplayerCard::updateCoverArt(QPixmap cover_art_image) {
    QPixmap scaled = cover_art_image.scaled(cover_art->size(), Qt::KeepAspectRatio, Qt::SmoothTransformation);

    QPixmap dest(scaled.size());
    dest.fill(Qt::transparent);

    QPainter painter(&dest);
    painter.setRenderHint(QPainter::Antialiasing);
    painter.setRenderHint(QPainter::SmoothPixmapTransform);

    QPainterPath path;
    path.addRoundedRect(dest.rect(), 5, 5);

    painter.setClipPath(path);
    painter.drawPixmap(0, 0, scaled);

    cover_art->setPixmap(dest);
    setBackgroundColor(&cover_art_image);
}

void MediaplayerCard::updateSongProgress(quint32 progress) {
    this->progress = progress;

    if (slider->isSliderDown()) {
        return;
    }

    slider->setValue(progress);

    QTimer::singleShot(1000, this, &MediaplayerCard::updateVirtualProgress);
}

void MediaplayerCard::sliderMoved(int value) {
    QTime time(0, 0, 0);
    time = time.addMSecs(value);

    QString time_string = time.toString("mm:ss");
    progress_label->setText(time_string);
}

void MediaplayerCard::updateVirtualProgress() {
    if (slider->isSliderDown()) {
        return;
    }

    if (!is_playing) {
        return;
    }

    progress = progress + 1000;

    slider->setValue(progress);
}

void MediaplayerCard::updateSongDuration(quint32 duration) {
    slider->setMaximum(duration);

    QTime time(0, 0, 0);
    time = time.addMSecs(duration);

    QString time_string = time.toString("mm:ss");
    duration_label->setText(time_string);
}

void MediaplayerCard::updateSongTitle(QString name) {
    const QString elided = title->fontMetrics().elidedText(name, Qt::ElideRight, width() - 20);
    title->setText(elided);
}

void MediaplayerCard::updateArtists(QString artists) {
    QString elided = artist->fontMetrics().elidedText(artists, Qt::ElideRight, width() - 20);
    artist->setText(elided);
}

void MediaplayerCard::updatePlayState(bool is_playing) {
    this->is_playing = is_playing;
    if (is_playing) {
        pause_play_button->setIcon(QIcon(":/resources/icons/pause.svg"));
    } else {
        pause_play_button->setIcon(QIcon(":/resources/icons/play.svg"));
    }
}

void MediaplayerCard::updatePauseButton() {
    if (is_playing) {
        pause_play_button->setIcon(QIcon(":/resources/icons/play.svg"));
    } else {
        pause_play_button->setIcon(QIcon(":/resources/icons/pause.svg"));
    }
    is_playing = !is_playing;
}

void MediaplayerCard::setBackgroundColor(const QPixmap *cover_art_image) {
    const QImage image = cover_art_image->scaled(100, 100, Qt::KeepAspectRatio, Qt::SmoothTransformation).toImage();

    int k = 7;
    QVector<QVector3D> samples;
    samples.reserve(10'000);

    for (int y = 0; y < 100; y++) {
        for (int x = 0; x < 100; x++) {
            QColor color = image.pixelColor(x, y);
            samples.emplace_back(color.red(), color.green(), color.blue());
        }
    }

    QVector<QVector3D> centers;
    centers.reserve(5);

    std::mt19937 random_engine{69420};
    std::uniform_int_distribution<> distribution(0, samples.size() - 1);

    for (int i = 0; i < k; i++) {
        centers.push_back(samples[distribution(random_engine)]);
    }

    QVector<int> counts(k, 0);

    for (int i = 0; i < 10; i++) {
        QVector<QVector3D> new_centers(k, QVector3D(0, 0, 0));
        std::fill(counts.begin(), counts.end(), 0);

        for (const QVector3D &pixel: samples) {
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

    QVector<QColor> result;
    result.reserve(k);

    for (const auto &c: info) {
        result.emplace_back(
            std::clamp<int>(c.center.x(), 0, 255),
            std::clamp<int>(c.center.y(), 0, 255),
            std::clamp<int>(c.center.z(), 0, 255)
        );
    }

    dominant_color = result[4];
    update();
}

void MediaplayerCard::paintEvent(QPaintEvent *event) {
    QFrame::paintEvent(event);

    QPainter painter(this);
    painter.setRenderHint(QPainter::Antialiasing);

    QPainterPath clip;
    clip.addRoundedRect(rect(), 5, 5);
    painter.setClipPath(clip);

    QLinearGradient gradient(0, 0, 0, height());
    gradient.setColorAt(0.0, dominant_color);
    gradient.setColorAt(0.45, dominant_color);
    gradient.setColorAt(1.0, Qt::black);

    painter.fillRect(rect(), gradient);
}

QVector<QPushButton *> MediaplayerCard::getButtonPointers() {
    QVector<QPushButton *> buttons;
    buttons.reserve(3);
    buttons.push_back(skip_backward_button);
    buttons.push_back(pause_play_button);
    buttons.push_back(skip_forward_button);
    return buttons;
}

QSlider *MediaplayerCard::getSlider() {
    return slider;
}

void MediaplayerCard::updateMediaType(uint8_t media_type) {
    qDebug() << media_type << "media_type";
    bool show_extras = media_type == 0x01;
    artist->setVisible(!show_extras);
    slider->setVisible(!show_extras);
    progress_label->setVisible(!show_extras);
    duration_label->setVisible(!show_extras);
}

