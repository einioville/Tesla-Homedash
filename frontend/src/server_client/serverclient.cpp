//
// Created by ville on 20.11.2025.
//

#include "serverclient.hh"
#include <QDebug>
#include <QtEndian>

ServerClient::ServerClient(QObject *parent, TeslaDataHandler *tesla_data_handler,
                           MediaplayerDataHandler *spotify_data_handler, WeatherDataHandler *weather_data_handler,
                           QString server_address,
                           quint16 server_port) {
    socket = new QTcpSocket(this);
    buffer = QByteArray();
    this->tesla_data_handler = tesla_data_handler;
    this->spotify_data_handler = spotify_data_handler;
    this->weather_data_handler = weather_data_handler;
    this->server_address = server_address;
    this->server_port = server_port;
    reconnect_timer = new QTimer(this);
    reconnect_timer->setInterval(10'000);
}

void ServerClient::startClient() {
    connect(socket, &QTcpSocket::connected, this, &ServerClient::onConnect);
    connect(socket, &QTcpSocket::readyRead, this, &ServerClient::onReadyRead);
    connect(socket, &QTcpSocket::disconnected, this, &ServerClient::onDisconnect);
    connect(socket, &QTcpSocket::errorOccurred, this, &ServerClient::onError);

    connect(this, &ServerClient::teslaStreamPacketReady, tesla_data_handler, &TeslaDataHandler::processStreamData);
    connect(tesla_data_handler, &TeslaDataHandler::onTeslaRequest, this, &ServerClient::onSendMessageRequest);

    connect(this, &ServerClient::spotifyCovertArtPacketReady, spotify_data_handler,
            &MediaplayerDataHandler::processCovertArtData);
    connect(this, &ServerClient::spotifySongProgressPacketReady, spotify_data_handler,
            &MediaplayerDataHandler::processSongProgress);
    connect(this, &ServerClient::spotifySongDurationPacketReady, spotify_data_handler,
            &MediaplayerDataHandler::processSongDuration);
    connect(this, &ServerClient::spotifySongTitlePacketReady, spotify_data_handler,
            &MediaplayerDataHandler::processSongTitle);
    connect(this, &ServerClient::spotifyPlayStatePacketReady, spotify_data_handler,
            &MediaplayerDataHandler::processPlayState);
    connect(this, &ServerClient::spotifyArtistsPacketReady, spotify_data_handler,
            &MediaplayerDataHandler::processArtists);
    connect(spotify_data_handler, &MediaplayerDataHandler::onSpotifyRequest, this, &ServerClient::onSendMessageRequest);
    connect(this, &ServerClient::mediaPlayerMediaTypePacketReady, spotify_data_handler,
            &MediaplayerDataHandler::processMediaType);

    connect(this, &ServerClient::mainWeatherPacketReady, weather_data_handler,
            &WeatherDataHandler::onMainForecastUpdate);

    connect(reconnect_timer, &QTimer::timeout, this, &ServerClient::connectToServer);

    connectToServer();
}

void ServerClient::connectToServer() const {
    if (socket->state() == QAbstractSocket::UnconnectedState) {
        qInfo() << "Connecting to host | address: " << server_address << " | port :" << server_port;
        socket->connectToHost(server_address, server_port);
    }
}

void ServerClient::onConnect() const {
    qInfo() << "Connected to server | address : " << server_address << " | port :" << server_port;
    reconnect_timer->stop();
}

void ServerClient::onDisconnect() {
    qWarning() << "Disconnected from server | address: " << server_address << " | port :" << server_port;
    buffer.clear();
    socket->readAll();
    reconnect_timer->start();
}

void ServerClient::onError(QAbstractSocket::SocketError error) const {
    qWarning() << "Socket error | error :" << error;
    reconnect_timer->start();
}

void ServerClient::onReadyRead() {
    buffer.append(socket->readAll());

    while (true) {
        // Check if message length has arrived
        if (buffer.size() < 4) {
            return;
        }

        // Read message length
        quint32 packet_length;
        {
            QByteArray slice = buffer.left(4);
            packet_length = qFromBigEndian<quint32>(slice.constData());
        }

        // Check if the whole message has been received
        if (buffer.size() < 4 + packet_length) {
            return;
        }

        // Read message type
        quint8 packet_type;
        {
            QByteArray slice = buffer.mid(4, 1);
            packet_type = qFromBigEndian<quint8>(slice.constData());
        }

        // Load message into new byte array
        QByteArray packet = buffer.mid(5, packet_length - 1);
        buffer.remove(0, 4 + packet_length);

        // Determine what signal is sent based on packet type
        switch (packet_type) {
            case 0x04:
                emit teslaStreamPacketReady(packet);
                break;

            case 0x14:
                emit spotifyCovertArtPacketReady(packet);
                break;

            case 0x15:
                emit spotifySongTitlePacketReady(packet);
                break;

            case 0x16:
                emit spotifySongProgressPacketReady(packet);
                break;

            case 0x17:
                emit spotifySongDurationPacketReady(packet);
                break;

            case 0x1B:
                emit spotifyPlayStatePacketReady(packet);
                break;

            case 0x1D:
                emit spotifyArtistsPacketReady(packet);
                break;

            case 0x1E:
                emit mediaPlayerMediaTypePacketReady(packet);
                break;

            case 0x30:
                emit mainWeatherPacketReady(packet);
                break;

            default:
                qInfo() << "Received unknown type of packet | packet type :" << packet_type;
                break;
        }
    }
}

void ServerClient::onSendMessageRequest(const QByteArray &packet) const {
    socket->write(packet);
    socket->flush();
    socket->waitForBytesWritten(1000);
}
