#include "vehicle.hh"

Vehicle::Vehicle(QObject *parent) : QObject{parent} {
    properties["ACChargingPower"] = {.data_stream_id = 0, .data_id = "ACChargingPower", .unit = "W", .value_type = 0};
    properties["BatteryLevel"] = {.data_stream_id = 1, .data_id = "BatteryLevel", .unit = "%", .value_type = 0};
    properties["BmsFullchargecomplete"] = {
        .data_stream_id = 2, .data_id = "BmsFullchargecomplete", .unit = "", .value_type = 2
    };
    properties["ChargeAmps"] = {.data_stream_id = 3, .data_id = "ChargeAmps", .unit = "A", .value_type = 0};
    properties["BMSState"] = {.data_stream_id = 4, .data_id = "BMSState", .unit = "", .value_type = 1};
    properties["ChargeLimitSoc"] = {.data_stream_id = 5, .data_id = "ChargeLimitSoc", .unit = "%", .value_type = 0};
    properties["ChargeRateMilePerHour"] = {
        .data_stream_id = 6, .data_id = "ChargeRateMilePerHour", .unit = "km/h", .value_type = 0
    };
    properties["ChargerPhases"] = {.data_stream_id = 7, .data_id = "ChargerPhases", .unit = "", .value_type = 0};
    properties["ChargerVoltage"] = {.data_stream_id = 8, .data_id = "ChargerVoltage", .unit = "V", .value_type = 0};
    properties["DetailedChargeState"] = {
        .data_stream_id = 9, .data_id = "DetailedChargeState", .unit = "", .value_type = 1
    };
    properties["DriverSeatOccupied"] = {
        .data_stream_id = 10, .data_id = "DriverSeatOccupied", .unit = "", .value_type = 2
    };
    properties["EnergyRemaining"] = {
        .data_stream_id = 11, .data_id = "EnergyRemaining", .unit = "kWh", .value_type = 0
    };
    properties["EstimatedHoursToChargeTermination"] = {
        .data_stream_id = 12, .data_id = "EstimatedHoursToChargeTermination", .unit = "h", .value_type = 0
    };
    properties["Gear"] = {.data_stream_id = 13, .data_id = "Gear", .unit = "", .value_type = 1};
    properties["HvacACEnabled"] = {.data_stream_id = 14, .data_id = "HvacACEnabled", .unit = "", .value_type = 2};
    properties["HvacLeftTemperatureRequest"] = {
        .data_stream_id = 15, .data_id = "HvacLeftTemperatureRequest", .unit = "°C", .value_type = 0
    };
    properties["HvacRightTemperatureRequest"] = {
        .data_stream_id = 16, .data_id = "HvacRightTemperatureRequest", .unit = "°C", .value_type = 0
    };
    properties["InsideTemp"] = {.data_stream_id = 17, .data_id = "InsideTemp", .unit = "°C", .value_type = 0};
    properties["LifetimeEnergyUsed"] = {
        .data_stream_id = 18, .data_id = "LifetimeEnergyUsed", .unit = "kWh", .value_type = 0
    };
    properties["Location"] = {.data_stream_id = 19, .data_id = "Location", .unit = "", .value_type = 3};
    properties["Locked"] = {.data_stream_id = 20, .data_id = "Locked", .unit = "", .value_type = 2};
    properties["Odometer"] = {.data_stream_id = 21, .data_id = "Odometer", .unit = "km", .value_type = 0};
    properties["OutsideTemp"] = {.data_stream_id = 22, .data_id = "OutsideTemp", .unit = "°C", .value_type = 0};
    properties["RatedRange"] = {.data_stream_id = 23, .data_id = "RatedRange", .unit = "km", .value_type = 0};
    properties["TimeToFullCharge"] = {
        .data_stream_id = 24, .data_id = "TimeToFullCharge", .unit = "h", .value_type = 0
    };
    properties["VehicleSpeed"] = {.data_stream_id = 25, .data_id = "VehicleSpeed", .unit = "km/h", .value_type = 0};
    properties["VehicleOnline"] = {.data_stream_id = 26, .data_id = "VehicleOnline", .unit = "", .value_type = 2};
    properties["DrivenToday"] = {.data_stream_id = 27, .data_id = "DrivenToday", .unit = "km", .value_type = 0};
    properties["DrivenThisMonth"] = {.data_stream_id = 28, .data_id = "DrivenThisMonth", .unit = "km", .value_type = 0};
    properties["GpsHeading"] = {.data_stream_id = 29, .data_id = "GpsHeading", .unit = "", .value_type = 0};
    properties["AutoSeatClimateLeft"] = {
        .data_stream_id = 30, .data_id = "AutoSeatClimateLeft", .unit = "", .value_type = 2
    };
    properties["AutoSeatClimateRight"] = {
        .data_stream_id = 31, .data_id = "AutoSeatClimateRight", .unit = "", .value_type = 2
    };
    properties["ClimateSeatCoolingFrontLeft"] = {
        .data_stream_id = 32, .data_id = "ClimateSeatCoolingFrontLeft", .unit = "", .value_type = 0
    };
    properties["ClimateSeatCoolingFrontRight"] = {
        .data_stream_id = 33, .data_id = "ClimateSeatCoolingFrontRight", .unit = "", .value_type = 0
    };
    properties["DefrostForPreconditioning"] = {
        .data_stream_id = 34, .data_id = "DefrostForPreconditioning", .unit = "", .value_type = 2
    };
    properties["DefrostMode"] = {.data_stream_id = 35, .data_id = "DefrostMode", .unit = "", .value_type = 1};
    properties["HvacAutoMode"] = {.data_stream_id = 36, .data_id = "HvacAutoMode", .unit = "", .value_type = 1};
    properties["HvacFanSpeed"] = {.data_stream_id = 37, .data_id = "HvacFanSpeed", .unit = "", .value_type = 0};
    properties["HvacFanStatus"] = {.data_stream_id = 38, .data_id = "HvacFanStatus", .unit = "", .value_type = 0};
    properties["HvacPower"] = {.data_stream_id = 39, .data_id = "HvacPower", .unit = "", .value_type = 1};
    properties["HvacSteeringWheelHeatLevel"] = {
        .data_stream_id = 40, .data_id = "HvacSteeringWheelHeatLevel", .unit = "", .value_type = 0
    };
    properties["PreconditioningEnabled"] = {
        .data_stream_id = 41, .data_id = "PreconditioningEnabled", .unit = "", .value_type = 2
    };
    properties["RearDefrostEnabled"] = {
        .data_stream_id = 42, .data_id = "RearDefrostEnabled", .unit = "", .value_type = 2
    };
    properties["SeatHeaterLeft"] = {.data_stream_id = 43, .data_id = "SeatHeaterLeft", .unit = "", .value_type = 0};
    properties["SeatHeaterRight"] = {.data_stream_id = 44, .data_id = "SeatHeaterRight", .unit = "", .value_type = 0};
}

TeslaDataProperty *Vehicle::getProperty(const QString &data_id) {
    if (!properties.contains(data_id)) {
        return nullptr;
    }

    return &properties[data_id];
}
