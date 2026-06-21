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
 * Malformed/unknown/value-type-mismatched packets are dropped (a single
 * mis-applied packet would corrupt a bound property).
 */
class TeslaData : public TeslaDataGen {
    Q_OBJECT

public:
    explicit TeslaData(ServerClient *server, QObject *parent = nullptr);

    // HVAC controls (frontend -> backend). plus/minus adjust a pre-conditioning
    // setpoint the backend only pushes to the car on the next climate toggle.
    Q_INVOKABLE void switchClimate();
    Q_INVOKABLE void plusTemp();
    Q_INVOKABLE void minusTemp();

private slots:
    void onPacket(quint8 type, const QByteArray &payload);

private:
    ServerClient *m_server;
};

#endif  // FRONTEND_V2_TESLADATA_HH
