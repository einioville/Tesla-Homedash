#ifndef FRONTEND_V2_TESLADATA_HH
#define FRONTEND_V2_TESLADATA_HH

#include "tesladata_gen.hh"

class ServerClient;

/**
 * TeslaData — the single Tesla telemetry datahandler, exposed to QML as the
 * `Tesla` singleton. Subscribes to the ServerClient packet stream, decodes
 * MSG_STREAM telemetry into the generated typed properties (TeslaDataGen), and
 * sends HVAC commands back.
 *
 * Parsing runs on the GUI thread — the bound properties are not thread-safe.
 * Packets with an unknown stream id, a mismatched value type or a truncated
 * string are dropped (a single mis-applied packet would corrupt a bound
 * property).
 */
class TeslaData : public TeslaDataGen {
    Q_OBJECT
    // When the car stopped being online (epoch ms, the backend's state event); 0 while it is
    // online or has not said. A repeated offline event leaves it where it is.
    Q_PROPERTY(qint64 asleepSince READ asleepSince NOTIFY asleepSinceChanged)

public:
    explicit TeslaData(ServerClient *server, QObject *parent = nullptr);

    // HVAC controls (frontend -> backend). plus/minus adjust a pre-conditioning
    // setpoint the backend only pushes to the car on the next climate toggle.
    Q_INVOKABLE void switchClimate();
    Q_INVOKABLE void plusTemp();
    Q_INVOKABLE void minusTemp();

    // The Q_PROPERTY name of a registry id: the first character lower-cased
    // (ACChargingPower -> aCChargingPower), as generate_tesladata.py's qml_name.
    static QString qmlName(const QString &registryName) {
        return registryName.left(1).toLower() + registryName.mid(1);
    }

    qint64 asleepSince() const { return m_asleepSince; }

signals:
    void asleepSinceChanged();

private slots:
    void onPacket(quint8 type, const QByteArray &payload);

private:
    void trackSleep();

    ServerClient *m_server;
    // The timestamp of the packet being applied, for the NOTIFY handlers it sets off.
    qint64 m_packetTime = 0;
    qint64 m_asleepSince = 0;
};

#endif  // FRONTEND_V2_TESLADATA_HH
