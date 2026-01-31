//
// Created by ville on 20.11.2025.
//

#ifndef GUI_TESLADATAHANDLER_HH
#define GUI_TESLADATAHANDLER_HH
#include "../vehicle.hh"
#include <QObject>
#include "../widgets/tesladatawidget.hh"
#include <QVector>

class TeslaDataHandler : public QObject {
    Q_OBJECT

public:
    explicit TeslaDataHandler(QObject *parent, Vehicle *veh);

    void connectToDataUpdateSignal(const quint16 &data_id, const TeslaDataWidget *tesla_data_widget) const;

    void connectToDataUpdateSignal(const QVector<quint16> &data_ids,
                                   const TeslaDataMultiWidget *tesla_data_widget) const;

public slots:
    void processStreamData(const QByteArray &packet);

    void plusTargetTemperature();

    void minusTargetTemperature();

    void switchClimateState();

signals:
    void onACChargingPowerUpdate(const double &value, const quint64 &timestamp);

    void onBatteryLevelUpdate(const double &value, const quint64 &timestamp);

    void onBmsFullChargeCompleteUpdate(const bool &value, const quint64 &timestamp);

    void onChargeAmpsUpdate(const double &value, const quint64 &timestamp);

    void onBMSStateUpdate(const QString &value, const quint64 &timestamp);

    void onChargeLimitSocUpdate(const double &value, const quint64 &timestamp);

    void onChargeRateMilePerHourUpdate(const double &value, const quint64 &timestamp);

    void onChargerPhasesUpdate(const double &value, const quint64 &timestamp);

    void onChargerVoltageUpdate(const double &value, const quint64 &timestamp);

    void onDetailedChargeStateUpdate(const QString &value, const quint64 &timestamp);

    void onDriverSeatOccupiedUpdate(const bool &value, const quint64 &timestamp);

    void onEnergyRemainingUpdate(const double &value, const quint64 &timestamp);

    void onEstimatedHoursToChargeTerminationUpdate(const double &value, const quint64 &timestamp);

    void onGearUpdate(const QString &value, const quint64 &timestamp);

    void onHvacACEnabledUpdate(const bool &value, const quint64 &timestamp);

    void onHvacLeftTemperatureRequestUpdate(const double &value, const quint64 &timestamp);

    void onHvacRightTemperatureRequestUpdate(const double &value, const quint64 &timestamp);

    void onInsideTempUpdate(const double &value, const quint64 &timestamp);

    void onLifetimeEnergyUsedUpdate(const double &value, const quint64 &timestamp);

    void onLocationUpdate(const double &value_latitude, const double &value_longitude, const quint64 &timestamp);

    void onLockedUpdate(const bool &value, const quint64 &timestamp);

    void onOdometerUpdate(const double &value, const quint64 &timestamp);

    void onOutsideTempUpdate(const double &value, const quint64 &timestamp);

    void onRatedRangeUpdate(const double &value, const quint64 &timestamp);

    void onTimeToFullChargeUpdate(const double &value, const quint64 &timestamp);

    void onVehicleSpeedUpdate(const double &value, const quint64 &timestamp);

    void onVehicleOnlineUpdate(const bool &value, const quint64 &timestamp);

    void onDrivenTodayUpdate(const double &value, const quint64 &timestamp);

    void onDrivenThisMonthUpdate(const double &value, const quint64 &timestamp);

    void onGpsHeadingUpdate(const double &value, const quint64 &timestamp);

    void onAutoSeatClimateLeftUpdate(const bool &value, const quint64 &timestamp);

    void onAutoSeatClimateRightUpdate(const bool &value, const quint64 &timestamp);

    void onClimateSeatCoolingFrontLeftUpdate(const double &value, const quint64 &timestamp);

    void onClimateSeatCoolingFrontRightUpdate(const double &value, const quint64 &timestamp);

    void onDefrostForPreconditioningUpdate(const bool &value, const quint64 &timestamp);

    void onDefrostModeUpdate(const QString &value, const quint64 &timestamp);

    void onHvacAutoModeUpdate(const QString &value, const quint64 &timestamp);

    void onHvacFanSpeedUpdate(const double &value, const quint64 &timestamp);

    void onHvacFanStatusUpdate(const double &value, const quint64 &timestamp);

    void onHvacPowerUpdate(const QString &value, const quint64 &timestamp);

    void onHvacSteeringWheelHeatLevelUpdate(const double &value, const quint64 &timestamp);

    void onPreconditioningEnabledUpdate(const bool &value, const quint64 &timestamp);

    void onRearDefrostEnabledUpdate(const bool &value, const quint64 &timestamp);

    void onSeatHeaterLeftUpdate(const double &value, const quint64 &timestamp);

    void onSeatHeaterRightUpdate(const double &value, const quint64 &timestamp);

    void onEstBatteryRangeUpdate(const double &value, const quint64 &timestamp);

    void onTeslaRequest(const QByteArray &packet);

private:
    Vehicle *vehicle;
};

#endif //GUI_TESLADATAHANDLER_HH
