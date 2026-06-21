#include "serverclient.hh"

#include "protocol.hh"

#include <QLoggingCategory>
#include <QtEndian>
#include <utility>

namespace {
Q_LOGGING_CATEGORY(lcServer, "frontend_v2.serverclient")
}

ServerClient::ServerClient(QString host, quint16 port, QObject *parent)
    : QObject(parent),
      m_socket(new QTcpSocket(this)),
      m_host(std::move(host)),
      m_port(port),
      m_reconnectTimer(new QTimer(this)) {
    m_reconnectTimer->setInterval(10'000);
}

QString ServerClient::stateText() const {
    switch (m_state) {
        case State::Disconnected: return QStringLiteral("Disconnected");
        case State::Connecting:   return QStringLiteral("Connecting");
        case State::Connected:    return QStringLiteral("Connected");
        case State::Reconnecting: return QStringLiteral("Reconnecting");
    }
    return QStringLiteral("Disconnected");
}

void ServerClient::start() {
    connect(m_socket, &QTcpSocket::connected, this, &ServerClient::onConnect);
    connect(m_socket, &QTcpSocket::readyRead, this, &ServerClient::onReadyRead);
    connect(m_socket, &QTcpSocket::disconnected, this, &ServerClient::onDisconnect);
    connect(m_socket, &QTcpSocket::errorOccurred, this, &ServerClient::onError);
    connect(m_reconnectTimer, &QTimer::timeout, this, &ServerClient::connectToServer);

    connectToServer();
}

void ServerClient::connectToServer() {
    if (m_socket->state() == QAbstractSocket::UnconnectedState) {
        qCInfo(lcServer) << "Connecting to" << m_host << m_port;
        setState(State::Connecting);
        m_socket->connectToHost(m_host, m_port);
    }
}

void ServerClient::onConnect() {
    qCInfo(lcServer) << "Connected to" << m_host << m_port;
    m_reconnectTimer->stop();
    setState(State::Connected);
}

void ServerClient::onDisconnect() {
    qCWarning(lcServer) << "Disconnected - reconnect armed (10s)";
    m_buffer.clear();
    m_socket->readAll();
    setState(State::Reconnecting);
    m_reconnectTimer->start();
}

void ServerClient::onError(QAbstractSocket::SocketError error) {
    qCWarning(lcServer) << "Socket error:" << static_cast<int>(error);
    setState(State::Reconnecting);
    m_reconnectTimer->start();
}

void ServerClient::setState(State state) {
    if (m_state == state) {
        return;
    }
    const bool wasConnected = (m_state == State::Connected);
    m_state = state;
    emit stateTextChanged();
    if ((state == State::Connected) != wasConnected) {
        emit connectedChanged();
    }
}

void ServerClient::sendPacket(const QByteArray &framed) {
    // Non-blocking write. Qt drains the kernel send buffer on the next event-loop
    // iteration; control packets are <= 6 bytes so back-pressure never builds. Do
    // NOT reintroduce flush()/waitForBytesWritten — it caused up to 1s of GUI
    // stall (and visible click latency) on slow networks.
    m_socket->write(framed);
    qCDebug(lcServer) << "Sent outbound packet | size=" << framed.size();
}

void ServerClient::onReadyRead() {
    m_buffer.append(m_socket->readAll());

    while (true) {
        // Wait for the full 4-byte length prefix.
        if (m_buffer.size() < 4) {
            return;
        }

        quint32 packetLength;
        {
            const QByteArray slice = m_buffer.left(4);
            packetLength = qFromBigEndian<quint32>(slice.constData());
        }

        // Defensive bound (protocol::MAX_PACKET_LENGTH): a corrupt or hostile
        // length prefix must not wrap the size arithmetic or grow the buffer
        // without limit. Reset the connection on violation so the reconnect
        // timer re-establishes a clean, frame-aligned stream.
        if (packetLength == 0 || static_cast<qint64>(packetLength) > protocol::MAX_PACKET_LENGTH) {
            qCWarning(lcServer) << "Invalid packet length" << packetLength << "- resetting connection";
            m_buffer.clear();
            m_socket->abort();
            return;
        }

        // Wait for the whole frame (64-bit comparison so the add cannot overflow).
        if (m_buffer.size() < static_cast<qint64>(packetLength) + 4) {
            return;
        }

        quint8 packetType;
        {
            const QByteArray slice = m_buffer.mid(4, 1);
            packetType = qFromBigEndian<quint8>(slice.constData());
        }

        // Payload = frame minus the 1 type byte; advance past [length][type][payload].
        const QByteArray payload = m_buffer.mid(5, packetLength - 1);
        m_buffer.remove(0, 4 + packetLength);

        qCDebug(lcServer) << "Received packet | type=0x" << QString::number(packetType, 16)
                          << "| size=" << payload.size();

        emit packetReceived(packetType, payload);
    }
}
