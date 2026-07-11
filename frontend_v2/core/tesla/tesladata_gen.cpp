// GENERATED FILE - do not edit by hand.
// Produced by core/tesla/generate_tesladata.py from tesla_properties.json.
// Re-run via the `regen_tesla_data` CMake target after changing the registry.

#include "tesladata_gen.hh"

#include <QHash>

int TeslaDataGen::valueTypeForStream(quint16 streamId) {
    switch (streamId) {
        case 0: return 0;
        case 1: return 0;
        case 2: return 2;
        case 3: return 0;
        case 4: return 1;
        case 5: return 0;
        case 6: return 0;
        case 7: return 0;
        case 8: return 0;
        case 9: return 1;
        case 10: return 2;
        case 11: return 0;
        case 12: return 0;
        case 13: return 1;
        case 14: return 2;
        case 15: return 0;
        case 16: return 0;
        case 17: return 0;
        case 18: return 0;
        case 19: return 3;
        case 20: return 2;
        case 21: return 0;
        case 22: return 0;
        case 23: return 0;
        case 24: return 0;
        case 25: return 0;
        case 26: return 2;
        case 27: return 0;
        case 28: return 0;
        case 29: return 0;
        case 30: return 2;
        case 31: return 2;
        case 32: return 0;
        case 33: return 0;
        case 34: return 2;
        case 35: return 1;
        case 36: return 1;
        case 37: return 0;
        case 38: return 0;
        case 39: return 1;
        case 40: return 0;
        case 41: return 2;
        case 42: return 2;
        case 43: return 0;
        case 44: return 0;
        case 45: return 0;
        case 46: return 0;
        default: return -1;
    }
}

QString TeslaDataGen::unitOf(const QString &propertyName) const {
    static const QHash<QString, QString> units = {
        { QStringLiteral("aCChargingPower"), QStringLiteral("W") },
        { QStringLiteral("batteryLevel"), QStringLiteral("%") },
        { QStringLiteral("chargeAmps"), QStringLiteral("A") },
        { QStringLiteral("chargeLimitSoc"), QStringLiteral("%") },
        { QStringLiteral("chargeRateMilePerHour"), QStringLiteral("km/h") },
        { QStringLiteral("chargerVoltage"), QStringLiteral("V") },
        { QStringLiteral("energyRemaining"), QStringLiteral("kWh") },
        { QStringLiteral("estimatedHoursToChargeTermination"), QStringLiteral("h") },
        { QStringLiteral("hvacLeftTemperatureRequest"), QStringLiteral("°C") },
        { QStringLiteral("hvacRightTemperatureRequest"), QStringLiteral("°C") },
        { QStringLiteral("insideTemp"), QStringLiteral("°C") },
        { QStringLiteral("lifetimeEnergyUsed"), QStringLiteral("kWh") },
        { QStringLiteral("odometer"), QStringLiteral("km") },
        { QStringLiteral("outsideTemp"), QStringLiteral("°C") },
        { QStringLiteral("ratedRange"), QStringLiteral("km") },
        { QStringLiteral("timeToFullCharge"), QStringLiteral("h") },
        { QStringLiteral("vehicleSpeed"), QStringLiteral("km/h") },
        { QStringLiteral("drivenToday"), QStringLiteral("km") },
        { QStringLiteral("drivenThisMonth"), QStringLiteral("km") },
        { QStringLiteral("estBatteryRange"), QStringLiteral("km") },
        { QStringLiteral("aCChargingEnergyIn"), QStringLiteral("kWh") },
    };
    return units.value(propertyName);
}

bool TeslaDataGen::applyValue(quint16 streamId, const QVariant &value) {
    switch (streamId) {
        case 0: m_aCChargingPower = value.toDouble(); emit aCChargingPowerChanged(); return true;
        case 1: m_batteryLevel = value.toDouble(); emit batteryLevelChanged(); return true;
        case 2: m_bmsFullchargecomplete = value.toBool(); emit bmsFullchargecompleteChanged(); return true;
        case 3: m_chargeAmps = value.toDouble(); emit chargeAmpsChanged(); return true;
        case 4: m_bMSState = value.toString(); emit bMSStateChanged(); return true;
        case 5: m_chargeLimitSoc = value.toDouble(); emit chargeLimitSocChanged(); return true;
        case 6: m_chargeRateMilePerHour = value.toDouble(); emit chargeRateMilePerHourChanged(); return true;
        case 7: m_chargerPhases = value.toDouble(); emit chargerPhasesChanged(); return true;
        case 8: m_chargerVoltage = value.toDouble(); emit chargerVoltageChanged(); return true;
        case 9: m_detailedChargeState = value.toString(); emit detailedChargeStateChanged(); return true;
        case 10: m_driverSeatOccupied = value.toBool(); emit driverSeatOccupiedChanged(); return true;
        case 11: m_energyRemaining = value.toDouble(); emit energyRemainingChanged(); return true;
        case 12: m_estimatedHoursToChargeTermination = value.toDouble(); emit estimatedHoursToChargeTerminationChanged(); return true;
        case 13: m_gear = value.toString(); emit gearChanged(); return true;
        case 14: m_hvacACEnabled = value.toBool(); emit hvacACEnabledChanged(); return true;
        case 15: m_hvacLeftTemperatureRequest = value.toDouble(); emit hvacLeftTemperatureRequestChanged(); return true;
        case 16: m_hvacRightTemperatureRequest = value.toDouble(); emit hvacRightTemperatureRequestChanged(); return true;
        case 17: m_insideTemp = value.toDouble(); emit insideTempChanged(); return true;
        case 18: m_lifetimeEnergyUsed = value.toDouble(); emit lifetimeEnergyUsedChanged(); return true;
        case 19: m_location = value.toMap(); emit locationChanged(); return true;
        case 20: m_locked = value.toBool(); emit lockedChanged(); return true;
        case 21: m_odometer = value.toDouble(); emit odometerChanged(); return true;
        case 22: m_outsideTemp = value.toDouble(); emit outsideTempChanged(); return true;
        case 23: m_ratedRange = value.toDouble(); emit ratedRangeChanged(); return true;
        case 24: m_timeToFullCharge = value.toDouble(); emit timeToFullChargeChanged(); return true;
        case 25: m_vehicleSpeed = value.toDouble(); emit vehicleSpeedChanged(); return true;
        case 26: m_vehicleOnline = value.toBool(); emit vehicleOnlineChanged(); return true;
        case 27: m_drivenToday = value.toDouble(); emit drivenTodayChanged(); return true;
        case 28: m_drivenThisMonth = value.toDouble(); emit drivenThisMonthChanged(); return true;
        case 29: m_gpsHeading = value.toDouble(); emit gpsHeadingChanged(); return true;
        case 30: m_autoSeatClimateLeft = value.toBool(); emit autoSeatClimateLeftChanged(); return true;
        case 31: m_autoSeatClimateRight = value.toBool(); emit autoSeatClimateRightChanged(); return true;
        case 32: m_climateSeatCoolingFrontLeft = value.toDouble(); emit climateSeatCoolingFrontLeftChanged(); return true;
        case 33: m_climateSeatCoolingFrontRight = value.toDouble(); emit climateSeatCoolingFrontRightChanged(); return true;
        case 34: m_defrostForPreconditioning = value.toBool(); emit defrostForPreconditioningChanged(); return true;
        case 35: m_defrostMode = value.toString(); emit defrostModeChanged(); return true;
        case 36: m_hvacAutoMode = value.toString(); emit hvacAutoModeChanged(); return true;
        case 37: m_hvacFanSpeed = value.toDouble(); emit hvacFanSpeedChanged(); return true;
        case 38: m_hvacFanStatus = value.toDouble(); emit hvacFanStatusChanged(); return true;
        case 39: m_hvacPower = value.toString(); emit hvacPowerChanged(); return true;
        case 40: m_hvacSteeringWheelHeatLevel = value.toDouble(); emit hvacSteeringWheelHeatLevelChanged(); return true;
        case 41: m_preconditioningEnabled = value.toBool(); emit preconditioningEnabledChanged(); return true;
        case 42: m_rearDefrostEnabled = value.toBool(); emit rearDefrostEnabledChanged(); return true;
        case 43: m_seatHeaterLeft = value.toDouble(); emit seatHeaterLeftChanged(); return true;
        case 44: m_seatHeaterRight = value.toDouble(); emit seatHeaterRightChanged(); return true;
        case 45: m_estBatteryRange = value.toDouble(); emit estBatteryRangeChanged(); return true;
        case 46: m_aCChargingEnergyIn = value.toDouble(); emit aCChargingEnergyInChanged(); return true;
        default: return false;
    }
}
