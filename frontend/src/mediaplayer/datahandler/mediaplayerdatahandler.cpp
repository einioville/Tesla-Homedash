//
// Created by ville on 24.11.2025.
//

#include "mediaplayerdatahandler.hh"
#include <QDataStream>

MediaplayerDataHandler::MediaplayerDataHandler(QObject *parent) : QObject{parent} {
    return;
}

void MediaplayerDataHandler::processCovertArtData(const QByteArray &packet) {
    QPixmap pixmap;
    pixmap.loadFromData(packet);
    emit onCovertArtUpdate(pixmap);
}

void MediaplayerDataHandler::processSongProgress(const QByteArray &packet) {
    QDataStream stream(packet);
    stream.setByteOrder(QDataStream::BigEndian);
    quint32 progress;
    stream >> progress;
    emit onSongProgressUpdate(progress);
}

void MediaplayerDataHandler::processSongDuration(const QByteArray &packet) {
    QDataStream stream(packet);
    stream.setByteOrder(QDataStream::BigEndian);
    quint32 duration;
    stream >> duration;
    emit onSongDurationUpdate(duration);
}

void MediaplayerDataHandler::processSongTitle(const QByteArray &packet) {
    QDataStream stream(packet);
    stream.setByteOrder(QDataStream::BigEndian);

    quint16 length;
    stream >> length;

    QByteArray raw(length, Qt::Uninitialized);
    stream.readRawData(raw.data(), length);
    QString title = QString::fromUtf8(raw);

    emit onSongTitleUpdate(title);
}

void MediaplayerDataHandler::processArtists(const QByteArray &packet) {
    QDataStream stream(packet);
    stream.setByteOrder(QDataStream::BigEndian);

    quint16 length;
    stream >> length;

    QByteArray raw(length, Qt::Uninitialized);
    stream.readRawData(raw.data(), length);
    QString artists = QString::fromUtf8(raw);

    emit onArtistsUpdate(artists);
}

void MediaplayerDataHandler::processPlayState(const QByteArray &packet) {
    QDataStream stream(packet);
    stream.setByteOrder(QDataStream::BigEndian);

    quint8 value_int_bool;
    stream >> value_int_bool;

    bool state;
    if (value_int_bool == 1) {
        state = true;
    } else {
        state = false;
    }

    emit onPlayStateUpdate(state);
}

void MediaplayerDataHandler::skipBackwards() {
    quint32 packet_length = 1;
    quint8 msg_type = 0x19;
    QByteArray packet;
    QDataStream stream(&packet, QIODevice::WriteOnly);
    stream << packet_length;
    stream << msg_type;
    emit onSpotifyRequest(packet);
}

void MediaplayerDataHandler::skipForwards() {
    quint32 packet_length = 1;
    quint8 msg_type = 0x18;
    QByteArray packet;
    QDataStream stream(&packet, QIODevice::WriteOnly);
    stream << packet_length;
    stream << msg_type;
    emit onSpotifyRequest(packet);
}

void MediaplayerDataHandler::pausePlay() {
    quint32 packet_length = 1;
    quint8 msg_type = 0x1A;
    QByteArray packet;
    QDataStream stream(&packet, QIODevice::WriteOnly);
    stream << packet_length;
    stream << msg_type;
    emit onSpotifyRequest(packet);
}

void MediaplayerDataHandler::setProgress() {
    quint32 value = slider->value();
    quint8 msg_type = 0x1C;
    quint32 packet_length = 5;
    QByteArray packet;
    QDataStream stream(&packet, QIODevice::WriteOnly);
    stream << packet_length;
    stream << msg_type;
    stream << value;
    emit onSpotifyRequest(packet);
}

void MediaplayerDataHandler::processMediaType(const QByteArray &packet) {
    QDataStream stream(packet);

    uint8_t media_type;
    stream >> media_type;

    emit onMediaTypeUpdate(media_type);
}

void MediaplayerDataHandler::connectPlayer(MediaplayerCard *player) {
    connect(this, &MediaplayerDataHandler::onCovertArtUpdate, player, &MediaplayerCard::updateCoverArt);
    connect(this, &MediaplayerDataHandler::onSongProgressUpdate, player, &MediaplayerCard::updateSongProgress);
    connect(this, &MediaplayerDataHandler::onSongDurationUpdate, player, &MediaplayerCard::updateSongDuration);
    connect(this, &MediaplayerDataHandler::onSongTitleUpdate, player, &MediaplayerCard::updateSongTitle);
    connect(this, &MediaplayerDataHandler::onPlayStateUpdate, player, &MediaplayerCard::updatePlayState);
    connect(this, &MediaplayerDataHandler::onArtistsUpdate, player, &MediaplayerCard::updateArtists);
    connect(this, &MediaplayerDataHandler::onMediaTypeUpdate, player, &MediaplayerCard::updateMediaType);

    QVector<QPushButton *> buttons = player->getButtonPointers();
    connect(buttons[0], &QPushButton::clicked, this, &MediaplayerDataHandler::skipBackwards);
    connect(buttons[1], &QPushButton::clicked, this, &MediaplayerDataHandler::pausePlay);
    connect(buttons[2], &QPushButton::clicked, this, &MediaplayerDataHandler::skipForwards);

    slider = player->getSlider();
    connect(slider, &QSlider::sliderReleased, this, &MediaplayerDataHandler::setProgress);
}
