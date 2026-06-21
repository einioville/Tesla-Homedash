// GENERATED FILE - do not edit by hand.
// Produced by core/tesla/generate_tesladata.py from tesla_properties.json.
// Re-run via the `regen_tesla_data` CMake target after changing the registry.

#ifndef FRONTEND_V2_TESLADATA_GEN_HH
#define FRONTEND_V2_TESLADATA_GEN_HH

#include <QObject>
#include <QString>
#include <QVariant>
#include <QVariantMap>

// Base class holding the generated Tesla telemetry properties. The
// hand-written TeslaData subclass decodes packets and calls applyValue().
class TeslaDataGen : public QObject {
    Q_OBJECT
    Q_PROPERTY(double aCChargingPower READ aCChargingPower NOTIFY aCChargingPowerChanged)
    Q_PROPERTY(double batteryLevel READ batteryLevel NOTIFY batteryLevelChanged)
    Q_PROPERTY(bool bmsFullchargecomplete READ bmsFullchargecomplete NOTIFY bmsFullchargecompleteChanged)
    Q_PROPERTY(double chargeAmps READ chargeAmps NOTIFY chargeAmpsChanged)
    Q_PROPERTY(QString bMSState READ bMSState NOTIFY bMSStateChanged)
    Q_PROPERTY(double chargeLimitSoc READ chargeLimitSoc NOTIFY chargeLimitSocChanged)
    Q_PROPERTY(double chargeRateMilePerHour READ chargeRateMilePerHour NOTIFY chargeRateMilePerHourChanged)
    Q_PROPERTY(double chargerPhases READ chargerPhases NOTIFY chargerPhasesChanged)
    Q_PROPERTY(double chargerVoltage READ chargerVoltage NOTIFY chargerVoltageChanged)
    Q_PROPERTY(QString detailedChargeState READ detailedChargeState NOTIFY detailedChargeStateChanged)
    Q_PROPERTY(bool driverSeatOccupied READ driverSeatOccupied NOTIFY driverSeatOccupiedChanged)
    Q_PROPERTY(double energyRemaining READ energyRemaining NOTIFY energyRemainingChanged)
    Q_PROPERTY(double estimatedHoursToChargeTermination READ estimatedHoursToChargeTermination NOTIFY estimatedHoursToChargeTerminationChanged)
    Q_PROPERTY(QString gear READ gear NOTIFY gearChanged)
    Q_PROPERTY(bool hvacACEnabled READ hvacACEnabled NOTIFY hvacACEnabledChanged)
    Q_PROPERTY(double hvacLeftTemperatureRequest READ hvacLeftTemperatureRequest NOTIFY hvacLeftTemperatureRequestChanged)
    Q_PROPERTY(double hvacRightTemperatureRequest READ hvacRightTemperatureRequest NOTIFY hvacRightTemperatureRequestChanged)
    Q_PROPERTY(double insideTemp READ insideTemp NOTIFY insideTempChanged)
    Q_PROPERTY(double lifetimeEnergyUsed READ lifetimeEnergyUsed NOTIFY lifetimeEnergyUsedChanged)
    Q_PROPERTY(QVariantMap location READ location NOTIFY locationChanged)
    Q_PROPERTY(bool locked READ locked NOTIFY lockedChanged)
    Q_PROPERTY(double odometer READ odometer NOTIFY odometerChanged)
    Q_PROPERTY(double outsideTemp READ outsideTemp NOTIFY outsideTempChanged)
    Q_PROPERTY(double ratedRange READ ratedRange NOTIFY ratedRangeChanged)
    Q_PROPERTY(double timeToFullCharge READ timeToFullCharge NOTIFY timeToFullChargeChanged)
    Q_PROPERTY(double vehicleSpeed READ vehicleSpeed NOTIFY vehicleSpeedChanged)
    Q_PROPERTY(bool vehicleOnline READ vehicleOnline NOTIFY vehicleOnlineChanged)
    Q_PROPERTY(double drivenToday READ drivenToday NOTIFY drivenTodayChanged)
    Q_PROPERTY(double drivenThisMonth READ drivenThisMonth NOTIFY drivenThisMonthChanged)
    Q_PROPERTY(double gpsHeading READ gpsHeading NOTIFY gpsHeadingChanged)
    Q_PROPERTY(bool autoSeatClimateLeft READ autoSeatClimateLeft NOTIFY autoSeatClimateLeftChanged)
    Q_PROPERTY(bool autoSeatClimateRight READ autoSeatClimateRight NOTIFY autoSeatClimateRightChanged)
    Q_PROPERTY(double climateSeatCoolingFrontLeft READ climateSeatCoolingFrontLeft NOTIFY climateSeatCoolingFrontLeftChanged)
    Q_PROPERTY(double climateSeatCoolingFrontRight READ climateSeatCoolingFrontRight NOTIFY climateSeatCoolingFrontRightChanged)
    Q_PROPERTY(bool defrostForPreconditioning READ defrostForPreconditioning NOTIFY defrostForPreconditioningChanged)
    Q_PROPERTY(QString defrostMode READ defrostMode NOTIFY defrostModeChanged)
    Q_PROPERTY(QString hvacAutoMode READ hvacAutoMode NOTIFY hvacAutoModeChanged)
    Q_PROPERTY(double hvacFanSpeed READ hvacFanSpeed NOTIFY hvacFanSpeedChanged)
    Q_PROPERTY(double hvacFanStatus READ hvacFanStatus NOTIFY hvacFanStatusChanged)
    Q_PROPERTY(QString hvacPower READ hvacPower NOTIFY hvacPowerChanged)
    Q_PROPERTY(double hvacSteeringWheelHeatLevel READ hvacSteeringWheelHeatLevel NOTIFY hvacSteeringWheelHeatLevelChanged)
    Q_PROPERTY(bool preconditioningEnabled READ preconditioningEnabled NOTIFY preconditioningEnabledChanged)
    Q_PROPERTY(bool rearDefrostEnabled READ rearDefrostEnabled NOTIFY rearDefrostEnabledChanged)
    Q_PROPERTY(double seatHeaterLeft READ seatHeaterLeft NOTIFY seatHeaterLeftChanged)
    Q_PROPERTY(double seatHeaterRight READ seatHeaterRight NOTIFY seatHeaterRightChanged)
    Q_PROPERTY(double estBatteryRange READ estBatteryRange NOTIFY estBatteryRangeChanged)

public:
    explicit TeslaDataGen(QObject *parent = nullptr) : QObject(parent) {}

    double aCChargingPower() const { return m_aCChargingPower; }
    double batteryLevel() const { return m_batteryLevel; }
    bool bmsFullchargecomplete() const { return m_bmsFullchargecomplete; }
    double chargeAmps() const { return m_chargeAmps; }
    QString bMSState() const { return m_bMSState; }
    double chargeLimitSoc() const { return m_chargeLimitSoc; }
    double chargeRateMilePerHour() const { return m_chargeRateMilePerHour; }
    double chargerPhases() const { return m_chargerPhases; }
    double chargerVoltage() const { return m_chargerVoltage; }
    QString detailedChargeState() const { return m_detailedChargeState; }
    bool driverSeatOccupied() const { return m_driverSeatOccupied; }
    double energyRemaining() const { return m_energyRemaining; }
    double estimatedHoursToChargeTermination() const { return m_estimatedHoursToChargeTermination; }
    QString gear() const { return m_gear; }
    bool hvacACEnabled() const { return m_hvacACEnabled; }
    double hvacLeftTemperatureRequest() const { return m_hvacLeftTemperatureRequest; }
    double hvacRightTemperatureRequest() const { return m_hvacRightTemperatureRequest; }
    double insideTemp() const { return m_insideTemp; }
    double lifetimeEnergyUsed() const { return m_lifetimeEnergyUsed; }
    QVariantMap location() const { return m_location; }
    bool locked() const { return m_locked; }
    double odometer() const { return m_odometer; }
    double outsideTemp() const { return m_outsideTemp; }
    double ratedRange() const { return m_ratedRange; }
    double timeToFullCharge() const { return m_timeToFullCharge; }
    double vehicleSpeed() const { return m_vehicleSpeed; }
    bool vehicleOnline() const { return m_vehicleOnline; }
    double drivenToday() const { return m_drivenToday; }
    double drivenThisMonth() const { return m_drivenThisMonth; }
    double gpsHeading() const { return m_gpsHeading; }
    bool autoSeatClimateLeft() const { return m_autoSeatClimateLeft; }
    bool autoSeatClimateRight() const { return m_autoSeatClimateRight; }
    double climateSeatCoolingFrontLeft() const { return m_climateSeatCoolingFrontLeft; }
    double climateSeatCoolingFrontRight() const { return m_climateSeatCoolingFrontRight; }
    bool defrostForPreconditioning() const { return m_defrostForPreconditioning; }
    QString defrostMode() const { return m_defrostMode; }
    QString hvacAutoMode() const { return m_hvacAutoMode; }
    double hvacFanSpeed() const { return m_hvacFanSpeed; }
    double hvacFanStatus() const { return m_hvacFanStatus; }
    QString hvacPower() const { return m_hvacPower; }
    double hvacSteeringWheelHeatLevel() const { return m_hvacSteeringWheelHeatLevel; }
    bool preconditioningEnabled() const { return m_preconditioningEnabled; }
    bool rearDefrostEnabled() const { return m_rearDefrostEnabled; }
    double seatHeaterLeft() const { return m_seatHeaterLeft; }
    double seatHeaterRight() const { return m_seatHeaterRight; }
    double estBatteryRange() const { return m_estBatteryRange; }

    // Expected protocol value_type (0=double,1=string,2=bool,3=location)
    // for a stream id, or -1 if the id is not in the registry.
    static int valueTypeForStream(quint16 streamId);

    // Unit string for a property's QML name, or "" if unknown/unitless.
    Q_INVOKABLE QString unitOf(const QString &propertyName) const;

signals:
    void aCChargingPowerChanged();
    void batteryLevelChanged();
    void bmsFullchargecompleteChanged();
    void chargeAmpsChanged();
    void bMSStateChanged();
    void chargeLimitSocChanged();
    void chargeRateMilePerHourChanged();
    void chargerPhasesChanged();
    void chargerVoltageChanged();
    void detailedChargeStateChanged();
    void driverSeatOccupiedChanged();
    void energyRemainingChanged();
    void estimatedHoursToChargeTerminationChanged();
    void gearChanged();
    void hvacACEnabledChanged();
    void hvacLeftTemperatureRequestChanged();
    void hvacRightTemperatureRequestChanged();
    void insideTempChanged();
    void lifetimeEnergyUsedChanged();
    void locationChanged();
    void lockedChanged();
    void odometerChanged();
    void outsideTempChanged();
    void ratedRangeChanged();
    void timeToFullChargeChanged();
    void vehicleSpeedChanged();
    void vehicleOnlineChanged();
    void drivenTodayChanged();
    void drivenThisMonthChanged();
    void gpsHeadingChanged();
    void autoSeatClimateLeftChanged();
    void autoSeatClimateRightChanged();
    void climateSeatCoolingFrontLeftChanged();
    void climateSeatCoolingFrontRightChanged();
    void defrostForPreconditioningChanged();
    void defrostModeChanged();
    void hvacAutoModeChanged();
    void hvacFanSpeedChanged();
    void hvacFanStatusChanged();
    void hvacPowerChanged();
    void hvacSteeringWheelHeatLevelChanged();
    void preconditioningEnabledChanged();
    void rearDefrostEnabledChanged();
    void seatHeaterLeftChanged();
    void seatHeaterRightChanged();
    void estBatteryRangeChanged();

protected:
    // Sets the field bound to streamId from value (interpreted per the
    // field's type) and emits its NOTIFY. Returns false if id is unknown.
    bool applyValue(quint16 streamId, const QVariant &value);

private:
    double m_aCChargingPower = 0.0;
    double m_batteryLevel = 0.0;
    bool m_bmsFullchargecomplete = false;
    double m_chargeAmps = 0.0;
    QString m_bMSState;
    double m_chargeLimitSoc = 0.0;
    double m_chargeRateMilePerHour = 0.0;
    double m_chargerPhases = 0.0;
    double m_chargerVoltage = 0.0;
    QString m_detailedChargeState;
    bool m_driverSeatOccupied = false;
    double m_energyRemaining = 0.0;
    double m_estimatedHoursToChargeTermination = 0.0;
    QString m_gear;
    bool m_hvacACEnabled = false;
    double m_hvacLeftTemperatureRequest = 0.0;
    double m_hvacRightTemperatureRequest = 0.0;
    double m_insideTemp = 0.0;
    double m_lifetimeEnergyUsed = 0.0;
    QVariantMap m_location;
    bool m_locked = false;
    double m_odometer = 0.0;
    double m_outsideTemp = 0.0;
    double m_ratedRange = 0.0;
    double m_timeToFullCharge = 0.0;
    double m_vehicleSpeed = 0.0;
    bool m_vehicleOnline = false;
    double m_drivenToday = 0.0;
    double m_drivenThisMonth = 0.0;
    double m_gpsHeading = 0.0;
    bool m_autoSeatClimateLeft = false;
    bool m_autoSeatClimateRight = false;
    double m_climateSeatCoolingFrontLeft = 0.0;
    double m_climateSeatCoolingFrontRight = 0.0;
    bool m_defrostForPreconditioning = false;
    QString m_defrostMode;
    QString m_hvacAutoMode;
    double m_hvacFanSpeed = 0.0;
    double m_hvacFanStatus = 0.0;
    QString m_hvacPower;
    double m_hvacSteeringWheelHeatLevel = 0.0;
    bool m_preconditioningEnabled = false;
    bool m_rearDefrostEnabled = false;
    double m_seatHeaterLeft = 0.0;
    double m_seatHeaterRight = 0.0;
    double m_estBatteryRange = 0.0;
};

#endif  // FRONTEND_V2_TESLADATA_GEN_HH
