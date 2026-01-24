//
// Created by ville on 20.11.2025.
//

#ifndef GUI_SERVER_CLIENT_HH
#define GUI_SERVER_CLIENT_HH
#include <QTcpSocket>
#include <QByteArray>
#include <QObject>
#include "../tesla/datahandler/tesladatahandler.hh"
#include <QString>
#include <QTimer>
#include <QAbstractSocket>
#include "../mediaplayer/datahandler/mediaplayerdatahandler.hh"
#include "../weather/datahandler/weatherdatahandler.hh"

class ServerClient : public QObject {
    Q_OBJECT

public:
    explicit ServerClient(QObject *parent, TeslaDataHandler *tesla_data_handler,
                          MediaplayerDataHandler *spotify_data_handler, WeatherDataHandler *weather_data_handler,
                          QString server_address,
                          quint16 server_port);

    void startClient();

private slots:
    void onConnect() const;

    void onDisconnect();

    void onReadyRead();

    void onError(QAbstractSocket::SocketError error) const;

    void onSendMessageRequest(const QByteArray &packet) const;

signals:
    void teslaStreamPacketReady(const QByteArray &packet);

    void spotifyCovertArtPacketReady(const QByteArray &packet);

    void spotifySongProgressPacketReady(const QByteArray &packet);

    void spotifySongDurationPacketReady(const QByteArray &packet);

    void spotifySongTitlePacketReady(const QByteArray &packet);

    void spotifyPlayStatePacketReady(const QByteArray &packet);

    void spotifyArtistsPacketReady(const QByteArray &packet);

    void mainWeatherPacketReady(const QByteArray &packet);

    void mediaPlayerMediaTypePacketReady(const QByteArray &packet);

    void couldNotConnect();

    void connectionLost();

    void reconnecting();

private:
    void connectToServer() const;

    QTcpSocket *socket;
    QByteArray buffer;
    TeslaDataHandler *tesla_data_handler;
    MediaplayerDataHandler *spotify_data_handler;
    WeatherDataHandler *weather_data_handler;
    QString server_address;
    quint16 server_port;
    QTimer *reconnect_timer;
};

#endif //GUI_SERVER_CLIENT_HH
