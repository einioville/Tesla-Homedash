//
// Created by ville on 20.11.2025.
//

#include "tesladatahandler.hh"
#include "../../utils/logger.hh"
#include <QDataStream>
#include <QVariantList>
#include <QIODevice>

namespace {
    const Logger logger = Logger::get("tesla.data");
}

namespace {
    using TDH = TeslaDataHandler;
    using TDW = TeslaDataWidget;
    using TDMW = TeslaDataMultiWidget;

    using DoubleSignal = void (TDH::*)(const double &, const quint64 &);
    using StringSignal = void (TDH::*)(const QString &, const quint64 &);
    using BoolSignal = void (TDH::*)(const bool &, const quint64 &);
    using LocationSignal = void (TDH::*)(const double &, const double &, const quint64 &);

    // One row per Tesla property. value_type matches the binary protocol:
    //   0 = double  -> sig_double
    //   1 = string  -> sig_string
    //   2 = bool    -> sig_bool
    //   3 = location -> sig_location
    // Only the signal slot matching value_type is populated; the others are
    // nullptr. processStreamData and connectToDataUpdateSignal both walk this
    // table, replacing the three 46-case switches that used to live here.
    // The set of data_id values and their bound signals matches the backend's
    // `tesla data` entries in config.json (see CLAUDE.md "Adding a new
    // telemetry field" for the four-file update protocol).
    struct StreamRoute {
        quint16 data_id;
        quint8 value_type;
        DoubleSignal sig_double;
        StringSignal sig_string;
        BoolSignal sig_bool;
        LocationSignal sig_location;
    };

    const StreamRoute kRoutes[] = {
        {0,  0, &TDH::onACChargingPowerUpdate,                  nullptr, nullptr, nullptr},
        {1,  0, &TDH::onBatteryLevelUpdate,                     nullptr, nullptr, nullptr},
        {2,  2, nullptr, nullptr, &TDH::onBmsFullChargeCompleteUpdate,  nullptr},
        {3,  0, &TDH::onChargeAmpsUpdate,                       nullptr, nullptr, nullptr},
        {4,  1, nullptr, &TDH::onBMSStateUpdate,                nullptr, nullptr},
        {5,  0, &TDH::onChargeLimitSocUpdate,                   nullptr, nullptr, nullptr},
        {6,  0, &TDH::onChargeRateMilePerHourUpdate,            nullptr, nullptr, nullptr},
        {7,  0, &TDH::onChargerPhasesUpdate,                    nullptr, nullptr, nullptr},
        {8,  0, &TDH::onChargerVoltageUpdate,                   nullptr, nullptr, nullptr},
        {9,  1, nullptr, &TDH::onDetailedChargeStateUpdate,     nullptr, nullptr},
        {10, 2, nullptr, nullptr, &TDH::onDriverSeatOccupiedUpdate,     nullptr},
        {11, 0, &TDH::onEnergyRemainingUpdate,                  nullptr, nullptr, nullptr},
        {12, 0, &TDH::onEstimatedHoursToChargeTerminationUpdate, nullptr, nullptr, nullptr},
        {13, 1, nullptr, &TDH::onGearUpdate,                    nullptr, nullptr},
        {14, 2, nullptr, nullptr, &TDH::onHvacACEnabledUpdate,             nullptr},
        {15, 0, &TDH::onHvacLeftTemperatureRequestUpdate,       nullptr, nullptr, nullptr},
        {16, 0, &TDH::onHvacRightTemperatureRequestUpdate,      nullptr, nullptr, nullptr},
        {17, 0, &TDH::onInsideTempUpdate,                       nullptr, nullptr, nullptr},
        {18, 0, &TDH::onLifetimeEnergyUsedUpdate,               nullptr, nullptr, nullptr},
        {19, 3, nullptr, nullptr, nullptr, &TDH::onLocationUpdate},
        {20, 2, nullptr, nullptr, &TDH::onLockedUpdate,                    nullptr},
        {21, 0, &TDH::onOdometerUpdate,                         nullptr, nullptr, nullptr},
        {22, 0, &TDH::onOutsideTempUpdate,                      nullptr, nullptr, nullptr},
        {23, 0, &TDH::onRatedRangeUpdate,                       nullptr, nullptr, nullptr},
        {24, 0, &TDH::onTimeToFullChargeUpdate,                 nullptr, nullptr, nullptr},
        {25, 0, &TDH::onVehicleSpeedUpdate,                     nullptr, nullptr, nullptr},
        {26, 2, nullptr, nullptr, &TDH::onVehicleOnlineUpdate,             nullptr},
        {27, 0, &TDH::onDrivenTodayUpdate,                      nullptr, nullptr, nullptr},
        {28, 0, &TDH::onDrivenThisMonthUpdate,                  nullptr, nullptr, nullptr},
        {29, 0, &TDH::onGpsHeadingUpdate,                       nullptr, nullptr, nullptr},
        {30, 2, nullptr, nullptr, &TDH::onAutoSeatClimateLeftUpdate,       nullptr},
        {31, 2, nullptr, nullptr, &TDH::onAutoSeatClimateRightUpdate,      nullptr},
        {32, 0, &TDH::onClimateSeatCoolingFrontLeftUpdate,      nullptr, nullptr, nullptr},
        {33, 0, &TDH::onClimateSeatCoolingFrontRightUpdate,     nullptr, nullptr, nullptr},
        {34, 2, nullptr, nullptr, &TDH::onDefrostForPreconditioningUpdate, nullptr},
        {35, 1, nullptr, &TDH::onDefrostModeUpdate,             nullptr, nullptr},
        {36, 1, nullptr, &TDH::onHvacAutoModeUpdate,            nullptr, nullptr},
        {37, 0, &TDH::onHvacFanSpeedUpdate,                     nullptr, nullptr, nullptr},
        {38, 0, &TDH::onHvacFanStatusUpdate,                    nullptr, nullptr, nullptr},
        {39, 1, nullptr, &TDH::onHvacPowerUpdate,               nullptr, nullptr},
        {40, 0, &TDH::onHvacSteeringWheelHeatLevelUpdate,       nullptr, nullptr, nullptr},
        {41, 2, nullptr, nullptr, &TDH::onPreconditioningEnabledUpdate,    nullptr},
        {42, 2, nullptr, nullptr, &TDH::onRearDefrostEnabledUpdate,        nullptr},
        {43, 0, &TDH::onSeatHeaterLeftUpdate,                   nullptr, nullptr, nullptr},
        {44, 0, &TDH::onSeatHeaterRightUpdate,                  nullptr, nullptr, nullptr},
        {45, 0, &TDH::onEstBatteryRangeUpdate,                  nullptr, nullptr, nullptr},
    };

    const StreamRoute *findRoute(quint16 data_id) {
        for (const auto &r : kRoutes) {
            if (r.data_id == data_id) {
                return &r;
            }
        }
        return nullptr;
    }
}

TeslaDataHandler::TeslaDataHandler(QObject *parent, Vehicle *veh) : QObject{parent} {
    vehicle = veh;
}

void TeslaDataHandler::processStreamData(const QByteArray &packet) {
    QDataStream stream(packet);
    stream.setByteOrder(QDataStream::BigEndian);
    QIODevice *device = stream.device();

    quint16 data_id;
    stream >> data_id;

    quint8 value_type;
    stream >> value_type;

    const StreamRoute *route = findRoute(data_id);
    if (!route) {
        logger.warning(QStringLiteral("No matching route for data_id=%1 (value_type=%2)")
                           .arg(data_id).arg(value_type));
        return;
    }
    if (route->value_type != value_type) {
        logger.warning(QStringLiteral("value_type mismatch for data_id=%1: expected=%2 got=%3")
                           .arg(data_id).arg(route->value_type).arg(value_type));
        return;
    }

    switch (value_type) {
        case 0: {
            double value;
            stream >> value;
            quint64 timestamp;
            stream >> timestamp;

            logger.debug(QStringLiteral("Stream packet | data_id=%1 | value_type=0 | value=%2 | ts=%3")
                             .arg(data_id).arg(value).arg(timestamp));

            if (route->sig_double) {
                emit (this->*(route->sig_double))(value, timestamp);
            }
            break;
        }

        case 1: {
            quint16 value_length;
            stream >> value_length;

            // Bounds-check the length prefix against what is actually in the
            // packet to avoid reading past the buffer on malformed frames.
            if (device && device->bytesAvailable() < value_length) {
                logger.warning(QStringLiteral("Truncated string payload | data_id=%1 | need=%2 have=%3")
                                   .arg(data_id).arg(value_length).arg(device->bytesAvailable()));
                return;
            }

            QByteArray raw(value_length, Qt::Uninitialized);
            stream.readRawData(raw.data(), value_length);
            const QString value = QString::fromUtf8(raw);

            quint64 timestamp;
            stream >> timestamp;

            logger.debug(QStringLiteral("Stream packet | data_id=%1 | value_type=1 | value=%2 | ts=%3")
                             .arg(data_id).arg(value).arg(timestamp));

            if (route->sig_string) {
                emit (this->*(route->sig_string))(value, timestamp);
            }
            break;
        }

        case 2: {
            quint8 value_int_bool;
            stream >> value_int_bool;

            const bool value = value_int_bool == 1;

            quint64 timestamp;
            stream >> timestamp;

            logger.debug(QStringLiteral("Stream packet | data_id=%1 | value_type=2 | value=%2 | ts=%3")
                             .arg(data_id).arg(value ? QStringLiteral("true") : QStringLiteral("false"))
                             .arg(timestamp));

            if (route->sig_bool) {
                emit (this->*(route->sig_bool))(value, timestamp);
            }
            break;
        }

        case 3: {
            double value_latitude;
            stream >> value_latitude;

            double value_longitude;
            stream >> value_longitude;

            quint64 timestamp;
            stream >> timestamp;

            logger.debug(QStringLiteral("Stream packet | data_id=%1 | value_type=3 | lat=%2 lon=%3 | ts=%4")
                             .arg(data_id).arg(value_latitude).arg(value_longitude).arg(timestamp));

            if (route->sig_location) {
                emit (this->*(route->sig_location))(value_latitude, value_longitude, timestamp);
            }
            break;
        }
        default: {
            logger.warning(QStringLiteral("Unknown value_type=%1 for data_id=%2").arg(value_type).arg(data_id));
            break;
        }
    }
}

void TeslaDataHandler::connectToDataUpdateSignal(const quint16 &data_id,
                                                 const TeslaDataWidget *tesla_data_widget) const {
    const StreamRoute *route = findRoute(data_id);
    if (!route) {
        return;
    }

    switch (route->value_type) {
        case 0:
            if (route->sig_double) {
                connect(this, route->sig_double, tesla_data_widget, &TeslaDataWidget::updateDataDouble);
            }
            break;
        case 1:
            if (route->sig_string) {
                connect(this, route->sig_string, tesla_data_widget, &TeslaDataWidget::updateDataString);
            }
            break;
        case 2:
            if (route->sig_bool) {
                connect(this, route->sig_bool, tesla_data_widget, &TeslaDataWidget::updateDataBool);
            }
            break;
        case 3:
            if (route->sig_location) {
                connect(this, route->sig_location, tesla_data_widget, &TeslaDataWidget::updateDataLocation);
            }
            break;
        default:
            break;
    }
}

void TeslaDataHandler::connectToDataUpdateSignal(const QVector<quint16> &data_ids,
                                                 const TeslaDataMultiWidget *tesla_data_widget) const {
    for (quint16 data_id : data_ids) {
        const StreamRoute *route = findRoute(data_id);
        if (!route) {
            continue;
        }

        switch (route->value_type) {
            case 0:
                if (route->sig_double) {
                    connect(this, route->sig_double, tesla_data_widget, &TeslaDataMultiWidget::updateDataDouble);
                }
                break;
            case 1:
                if (route->sig_string) {
                    connect(this, route->sig_string, tesla_data_widget, &TeslaDataMultiWidget::updateDataString);
                }
                break;
            case 2:
                if (route->sig_bool) {
                    connect(this, route->sig_bool, tesla_data_widget, &TeslaDataMultiWidget::updateDataBool);
                }
                break;
            case 3:
                if (route->sig_location) {
                    connect(this, route->sig_location, tesla_data_widget, &TeslaDataMultiWidget::updateDataLocation);
                }
                break;
            default:
                break;
        }
    }
}

void TeslaDataHandler::switchClimateState() {
    uint32_t packet_length = 1;
    uint8_t msg_type = 0x60;
    QByteArray packet;
    QDataStream stream(&packet, QIODevice::WriteOnly);
    stream << packet_length;
    stream << msg_type;
    logger.info(QStringLiteral("Climate switch command issued"));
    emit onTeslaRequest(packet);
}

void TeslaDataHandler::plusTargetTemperature() {
    uint32_t packet_length = 1;
    uint8_t msg_type = 0x62;
    QByteArray packet;
    QDataStream stream(&packet, QIODevice::WriteOnly);
    stream << packet_length;
    stream << msg_type;
    logger.info(QStringLiteral("Target temperature +1 command issued"));
    emit onTeslaRequest(packet);
}

void TeslaDataHandler::minusTargetTemperature() {
    uint32_t packet_length = 1;
    uint8_t msg_type = 0x61;
    QByteArray packet;
    QDataStream stream(&packet, QIODevice::WriteOnly);
    stream << packet_length;
    stream << msg_type;
    logger.info(QStringLiteral("Target temperature -1 command issued"));
    emit onTeslaRequest(packet);
}
