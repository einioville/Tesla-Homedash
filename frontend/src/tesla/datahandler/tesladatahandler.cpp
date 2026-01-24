//
// Created by ville on 20.11.2025.
//

#include "TeslaDataHandler.hh"
#include <QDataStream>
#include <QVariantList>
#include <QDebug>
#include <QIODevice>

TeslaDataHandler::TeslaDataHandler(QObject *parent, Vehicle *veh) : QObject{parent} {
    vehicle = veh;
}

void TeslaDataHandler::processStreamData(const QByteArray &packet) {
    QDataStream stream(packet);
    stream.setByteOrder(QDataStream::BigEndian);

    quint16 data_id;
    stream >> data_id;

    quint8 value_type;
    stream >> value_type;

    QString info_msg = "Received teslaStreamPacket | packet length : " + QString::number(packet.size()) +
                       " | data id : " + QString::number(data_id) + " | value type id : " + QString::number(value_type);

    switch (value_type) {
        case 0: {
            double value;
            stream >> value;
            quint64 timestamp;
            stream >> timestamp;

            info_msg += " | value : " + QString::number(value) + " | timestamp : " + QString::number(timestamp);
            qInfo().noquote() << info_msg;

            switch (data_id) {
                case 0:
                    emit onACChargingPowerUpdate(value, timestamp);
                    break;

                case 1:
                    emit onBatteryLevelUpdate(value, timestamp);
                    break;

                case 3:
                    emit onChargeAmpsUpdate(value, timestamp);

                case 5:
                    emit onChargeLimitSocUpdate(value, timestamp);
                    break;

                case 6:
                    emit onChargeRateMilePerHourUpdate(value, timestamp);
                    break;

                case 7:
                    emit onChargerPhasesUpdate(value, timestamp);
                    break;

                case 8:
                    emit onChargerVoltageUpdate(value, timestamp);
                    break;

                case 11:
                    emit onEnergyRemainingUpdate(value, timestamp);
                    break;

                case 12:
                    emit onEstimatedHoursToChargeTerminationUpdate(value, timestamp);
                    break;

                case 15:
                    emit onHvacLeftTemperatureRequestUpdate(value, timestamp);
                    break;

                case 16:
                    emit onHvacRightTemperatureRequestUpdate(value, timestamp);
                    break;

                case 17:
                    emit onInsideTempUpdate(value, timestamp);
                    break;

                case 18:
                    emit onLifetimeEnergyUsedUpdate(value, timestamp);
                    break;

                case 21:
                    emit onOdometerUpdate(value, timestamp);
                    break;

                case 22:
                    emit onOutsideTempUpdate(value, timestamp);
                    break;

                case 23:
                    emit onRatedRangeUpdate(value, timestamp);
                    break;

                case 24:
                    emit onTimeToFullChargeUpdate(value, timestamp);
                    break;

                case 25:
                    emit onVehicleSpeedUpdate(value, timestamp);
                    break;

                case 27:
                    emit onDrivenTodayUpdate(value, timestamp);
                    break;

                case 28:
                    emit onDrivenThisMonthUpdate(value, timestamp);
                    break;

                case 29:
                    emit onGpsHeadingUpdate(value, timestamp);
                    break;

                case 32:
                    emit onClimateSeatCoolingFrontLeftUpdate(value, timestamp);
                    break;

                case 33:
                    emit onClimateSeatCoolingFrontRightUpdate(value, timestamp);
                    break;

                case 37:
                    emit onHvacFanSpeedUpdate(value, timestamp);
                    break;

                case 38:
                    emit onHvacFanStatusUpdate(value, timestamp);
                    break;

                case 40:
                    emit onHvacSteeringWheelHeatLevelUpdate(value, timestamp);
                    break;

                case 43:
                    emit onSeatHeaterLeftUpdate(value, timestamp);
                    break;

                case 44:
                    emit onSeatHeaterRightUpdate(value, timestamp);
                    break;

                default:
                    break;
            }

            break;
        }

        case 1: {
            quint16 value_length;
            stream >> value_length;

            QByteArray raw(value_length, Qt::Uninitialized);
            stream.readRawData(raw.data(), value_length);
            const QString value = QString::fromUtf8(raw);

            quint64 timestamp;
            stream >> timestamp;

            info_msg += " | value : " + value + " | timestamp : " + QString::number(timestamp);
            qInfo().noquote() << info_msg;

            switch (data_id) {
                case 4:
                    emit onBMSStateUpdate(value, timestamp);

                case 9:
                    emit onDetailedChargeStateUpdate(value, timestamp);
                    break;

                case 13:
                    emit onGearUpdate(value, timestamp);
                    break;

                case 35:
                    emit onDefrostModeUpdate(value, timestamp);
                    break;

                case 36:
                    emit onHvacAutoModeUpdate(value, timestamp);
                    break;

                case 39:
                    emit onHvacPowerUpdate(value, timestamp);
                    break;

                default:
                    break;
            }

            break;
        }

        case 2: {
            quint8 value_int_bool;
            stream >> value_int_bool;

            const bool value = value_int_bool == 1;

            quint64 timestamp;
            stream >> timestamp;

            info_msg += " | value : " + QString::number(value_int_bool) + " | timestamp : " +
                    QString::number(timestamp);
            qInfo().noquote() << info_msg;

            switch (data_id) {
                case 2:
                    emit onBmsFullChargeCompleteUpdate(value, timestamp);
                    break;

                case 10:
                    emit onDriverSeatOccupiedUpdate(value, timestamp);
                    break;

                case 14:
                    emit onHvacACEnabledUpdate(value, timestamp);
                    break;

                case 20:
                    emit onLockedUpdate(value, timestamp);

                case 26:
                    emit onVehicleOnlineUpdate(value, timestamp);
                    break;

                case 30:
                    emit onAutoSeatClimateLeftUpdate(value, timestamp);
                    break;

                case 31:
                    emit onAutoSeatClimateRightUpdate(value, timestamp);
                    break;

                case 34:
                    emit onDefrostForPreconditioningUpdate(value, timestamp);
                    break;

                case 41:
                    emit onPreconditioningEnabledUpdate(value, timestamp);
                    break;

                case 42:
                    emit onRearDefrostEnabledUpdate(value, timestamp);
                    break;

                default:
                    break;
            }

            break;
        }

        case 3: {
            double value_latitude;
            stream >> value_latitude;
            info_msg += " | value : (latitude : " + QString::number(value_latitude);

            double value_longitude;
            stream >> value_longitude;
            info_msg += ", longitude : " + QString::number(value_longitude);

            quint64 timestamp;
            stream >> timestamp;

            info_msg += " | timestamp : " + QString::number(timestamp);
            qInfo().noquote() << info_msg;

            emit onLocationUpdate(value_latitude, value_longitude, timestamp);

            break;
        }
        default: {
            break;
        }
    }
}

void TeslaDataHandler::connectToDataUpdateSignal(const quint16 &data_id,
                                                 const TeslaDataWidget *tesla_data_widget) const {
    switch (data_id) {
        case 0:
            connect(this, &TeslaDataHandler::onACChargingPowerUpdate,
                    tesla_data_widget, &TeslaDataWidget::updateDataDouble);
            break;

        case 1:
            connect(this, &TeslaDataHandler::onBatteryLevelUpdate,
                    tesla_data_widget, &TeslaDataWidget::updateDataDouble);
            break;

        case 2:
            connect(this, &TeslaDataHandler::onBmsFullChargeCompleteUpdate,
                    tesla_data_widget, &TeslaDataWidget::updateDataBool);
            break;

        case 3:
            connect(this, &TeslaDataHandler::onChargeAmpsUpdate,
                    tesla_data_widget, &TeslaDataWidget::updateDataDouble);
            break;

        case 4:
            connect(this, &TeslaDataHandler::onBMSStateUpdate,
                    tesla_data_widget, &TeslaDataWidget::updateDataString);
            break;

        case 5:
            connect(this, &TeslaDataHandler::onChargeLimitSocUpdate,
                    tesla_data_widget, &TeslaDataWidget::updateDataDouble);
            break;

        case 6:
            connect(this, &TeslaDataHandler::onChargeRateMilePerHourUpdate,
                    tesla_data_widget, &TeslaDataWidget::updateDataDouble);
            break;

        case 7:
            connect(this, &TeslaDataHandler::onChargerPhasesUpdate,
                    tesla_data_widget, &TeslaDataWidget::updateDataDouble);
            break;

        case 8:
            connect(this, &TeslaDataHandler::onChargerVoltageUpdate,
                    tesla_data_widget, &TeslaDataWidget::updateDataDouble);
            break;

        case 9:
            connect(this, &TeslaDataHandler::onDetailedChargeStateUpdate,
                    tesla_data_widget, &TeslaDataWidget::updateDataString);
            break;

        case 10:
            connect(this, &TeslaDataHandler::onDriverSeatOccupiedUpdate,
                    tesla_data_widget, &TeslaDataWidget::updateDataBool);
            break;

        case 11:
            connect(this, &TeslaDataHandler::onEnergyRemainingUpdate,
                    tesla_data_widget, &TeslaDataWidget::updateDataDouble);
            break;

        case 12:
            connect(this, &TeslaDataHandler::onEstimatedHoursToChargeTerminationUpdate,
                    tesla_data_widget, &TeslaDataWidget::updateDataDouble);
            break;

        case 13:
            connect(this, &TeslaDataHandler::onGearUpdate,
                    tesla_data_widget, &TeslaDataWidget::updateDataString);
            break;

        case 14:
            connect(this, &TeslaDataHandler::onHvacACEnabledUpdate,
                    tesla_data_widget, &TeslaDataWidget::updateDataBool);
            break;

        case 15:
            connect(this, &TeslaDataHandler::onHvacLeftTemperatureRequestUpdate,
                    tesla_data_widget, &TeslaDataWidget::updateDataDouble);
            break;

        case 16:
            connect(this, &TeslaDataHandler::onHvacRightTemperatureRequestUpdate,
                    tesla_data_widget, &TeslaDataWidget::updateDataDouble);
            break;

        case 17:
            connect(this, &TeslaDataHandler::onInsideTempUpdate,
                    tesla_data_widget, &TeslaDataWidget::updateDataDouble);
            break;

        case 18:
            connect(this, &TeslaDataHandler::onLifetimeEnergyUsedUpdate,
                    tesla_data_widget, &TeslaDataWidget::updateDataDouble);
            break;

        case 19:
            connect(this, &TeslaDataHandler::onLocationUpdate,
                    tesla_data_widget, &TeslaDataWidget::updateDataLocation);
            break;

        case 20:
            connect(this, &TeslaDataHandler::onLockedUpdate,
                    tesla_data_widget, &TeslaDataWidget::updateDataBool);
            break;

        case 21:
            connect(this, &TeslaDataHandler::onOdometerUpdate,
                    tesla_data_widget, &TeslaDataWidget::updateDataDouble);
            break;

        case 22:
            connect(this, &TeslaDataHandler::onOutsideTempUpdate,
                    tesla_data_widget, &TeslaDataWidget::updateDataDouble);
            break;

        case 23:
            connect(this, &TeslaDataHandler::onRatedRangeUpdate,
                    tesla_data_widget, &TeslaDataWidget::updateDataDouble);
            break;

        case 24:
            connect(this, &TeslaDataHandler::onTimeToFullChargeUpdate,
                    tesla_data_widget, &TeslaDataWidget::updateDataDouble);
            break;

        case 25:
            connect(this, &TeslaDataHandler::onVehicleSpeedUpdate,
                    tesla_data_widget, &TeslaDataWidget::updateDataDouble);
            break;

        case 26:
            connect(this, &TeslaDataHandler::onVehicleOnlineUpdate,
                    tesla_data_widget, &TeslaDataWidget::updateDataBool);
            break;

        case 27:
            connect(this, &TeslaDataHandler::onDrivenTodayUpdate, tesla_data_widget,
                    &TeslaDataWidget::updateDataDouble);
            break;

        case 28:
            connect(this, &TeslaDataHandler::onDrivenThisMonthUpdate, tesla_data_widget,
                    &TeslaDataWidget::updateDataDouble);
            break;

        case 29:
            connect(this, &TeslaDataHandler::onGpsHeadingUpdate, tesla_data_widget, &TeslaDataWidget::updateDataDouble);
            break;

        case 30:
            connect(this, &TeslaDataHandler::onAutoSeatClimateLeftUpdate,
                    tesla_data_widget, &TeslaDataWidget::updateDataBool);
            break;

        case 31:
            connect(this, &TeslaDataHandler::onAutoSeatClimateRightUpdate,
                    tesla_data_widget, &TeslaDataWidget::updateDataBool);
            break;

        case 32:
            connect(this, &TeslaDataHandler::onClimateSeatCoolingFrontLeftUpdate,
                    tesla_data_widget, &TeslaDataWidget::updateDataDouble);
            break;

        case 33:
            connect(this, &TeslaDataHandler::onClimateSeatCoolingFrontRightUpdate,
                    tesla_data_widget, &TeslaDataWidget::updateDataDouble);
            break;

        case 34:
            connect(this, &TeslaDataHandler::onDefrostForPreconditioningUpdate,
                    tesla_data_widget, &TeslaDataWidget::updateDataBool);
            break;

        case 35:
            connect(this, &TeslaDataHandler::onDefrostModeUpdate,
                    tesla_data_widget, &TeslaDataWidget::updateDataString);
            break;

        case 36:
            connect(this, &TeslaDataHandler::onHvacAutoModeUpdate,
                    tesla_data_widget, &TeslaDataWidget::updateDataString);
            break;

        case 37:
            connect(this, &TeslaDataHandler::onHvacFanSpeedUpdate,
                    tesla_data_widget, &TeslaDataWidget::updateDataDouble);
            break;

        case 38:
            connect(this, &TeslaDataHandler::onHvacFanStatusUpdate,
                    tesla_data_widget, &TeslaDataWidget::updateDataDouble);
            break;

        case 39:
            connect(this, &TeslaDataHandler::onHvacPowerUpdate,
                    tesla_data_widget, &TeslaDataWidget::updateDataString);
            break;

        case 40:
            connect(this, &TeslaDataHandler::onHvacSteeringWheelHeatLevelUpdate,
                    tesla_data_widget, &TeslaDataWidget::updateDataDouble);
            break;

        case 41:
            connect(this, &TeslaDataHandler::onPreconditioningEnabledUpdate,
                    tesla_data_widget, &TeslaDataWidget::updateDataBool);
            break;

        case 42:
            connect(this, &TeslaDataHandler::onRearDefrostEnabledUpdate,
                    tesla_data_widget, &TeslaDataWidget::updateDataBool);
            break;

        case 43:
            connect(this, &TeslaDataHandler::onSeatHeaterLeftUpdate,
                    tesla_data_widget, &TeslaDataWidget::updateDataDouble);
            break;

        case 44:
            connect(this, &TeslaDataHandler::onSeatHeaterRightUpdate,
                    tesla_data_widget, &TeslaDataWidget::updateDataDouble);
            break;

        default:
            break;
    }
}

void TeslaDataHandler::connectToDataUpdateSignal(const QVector<quint16> &data_ids,
                                                 const TeslaDataMultiWidget *tesla_data_widget) const {
    for (quint16 data_id: data_ids) {
        switch (data_id) {
            case 0:
                connect(this, &TeslaDataHandler::onACChargingPowerUpdate,
                        tesla_data_widget, &TeslaDataMultiWidget::updateDataDouble);
                break;

            case 1:
                connect(this, &TeslaDataHandler::onBatteryLevelUpdate,
                        tesla_data_widget, &TeslaDataMultiWidget::updateDataDouble);
                break;

            case 2:
                connect(this, &TeslaDataHandler::onBmsFullChargeCompleteUpdate,
                        tesla_data_widget, &TeslaDataMultiWidget::updateDataBool);
                break;

            case 3:
                connect(this, &TeslaDataHandler::onChargeAmpsUpdate,
                        tesla_data_widget, &TeslaDataMultiWidget::updateDataDouble);
                break;

            case 4:
                connect(this, &TeslaDataHandler::onBMSStateUpdate,
                        tesla_data_widget, &TeslaDataMultiWidget::updateDataString);
                break;

            case 5:
                connect(this, &TeslaDataHandler::onChargeLimitSocUpdate,
                        tesla_data_widget, &TeslaDataMultiWidget::updateDataDouble);
                break;

            case 6:
                connect(this, &TeslaDataHandler::onChargeRateMilePerHourUpdate,
                        tesla_data_widget, &TeslaDataMultiWidget::updateDataDouble);
                break;

            case 7:
                connect(this, &TeslaDataHandler::onChargerPhasesUpdate,
                        tesla_data_widget, &TeslaDataMultiWidget::updateDataDouble);
                break;

            case 8:
                connect(this, &TeslaDataHandler::onChargerVoltageUpdate,
                        tesla_data_widget, &TeslaDataMultiWidget::updateDataDouble);
                break;

            case 9:
                connect(this, &TeslaDataHandler::onDetailedChargeStateUpdate,
                        tesla_data_widget, &TeslaDataMultiWidget::updateDataString);
                break;

            case 10:
                connect(this, &TeslaDataHandler::onDriverSeatOccupiedUpdate,
                        tesla_data_widget, &TeslaDataMultiWidget::updateDataBool);
                break;

            case 11:
                connect(this, &TeslaDataHandler::onEnergyRemainingUpdate,
                        tesla_data_widget, &TeslaDataMultiWidget::updateDataDouble);
                break;

            case 12:
                connect(this, &TeslaDataHandler::onEstimatedHoursToChargeTerminationUpdate,
                        tesla_data_widget, &TeslaDataMultiWidget::updateDataDouble);
                break;

            case 13:
                connect(this, &TeslaDataHandler::onGearUpdate,
                        tesla_data_widget, &TeslaDataMultiWidget::updateDataString);
                break;

            case 14:
                connect(this, &TeslaDataHandler::onHvacACEnabledUpdate,
                        tesla_data_widget, &TeslaDataMultiWidget::updateDataBool);
                break;

            case 15:
                connect(this, &TeslaDataHandler::onHvacLeftTemperatureRequestUpdate,
                        tesla_data_widget, &TeslaDataMultiWidget::updateDataDouble);
                break;

            case 16:
                connect(this, &TeslaDataHandler::onHvacRightTemperatureRequestUpdate,
                        tesla_data_widget, &TeslaDataMultiWidget::updateDataDouble);
                break;

            case 17:
                connect(this, &TeslaDataHandler::onInsideTempUpdate,
                        tesla_data_widget, &TeslaDataMultiWidget::updateDataDouble);
                break;

            case 18:
                connect(this, &TeslaDataHandler::onLifetimeEnergyUsedUpdate,
                        tesla_data_widget, &TeslaDataMultiWidget::updateDataDouble);
                break;

            case 19:
                connect(this, &TeslaDataHandler::onLocationUpdate,
                        tesla_data_widget, &TeslaDataMultiWidget::updateDataLocation);
                break;

            case 20:
                connect(this, &TeslaDataHandler::onLockedUpdate,
                        tesla_data_widget, &TeslaDataMultiWidget::updateDataBool);
                break;

            case 21:
                connect(this, &TeslaDataHandler::onOdometerUpdate,
                        tesla_data_widget, &TeslaDataMultiWidget::updateDataDouble);
                break;

            case 22:
                connect(this, &TeslaDataHandler::onOutsideTempUpdate,
                        tesla_data_widget, &TeslaDataMultiWidget::updateDataDouble);
                break;

            case 23:
                connect(this, &TeslaDataHandler::onRatedRangeUpdate,
                        tesla_data_widget, &TeslaDataMultiWidget::updateDataDouble);
                break;

            case 24:
                connect(this, &TeslaDataHandler::onTimeToFullChargeUpdate,
                        tesla_data_widget, &TeslaDataMultiWidget::updateDataDouble);
                break;

            case 25:
                connect(this, &TeslaDataHandler::onVehicleSpeedUpdate,
                        tesla_data_widget, &TeslaDataMultiWidget::updateDataDouble);
                break;

            case 26:
                connect(this, &TeslaDataHandler::onVehicleOnlineUpdate,
                        tesla_data_widget, &TeslaDataMultiWidget::updateDataBool);
                break;

            case 27:
                connect(this, &TeslaDataHandler::onDrivenTodayUpdate, tesla_data_widget,
                        &TeslaDataMultiWidget::updateDataDouble);
                break;

            case 28:
                connect(this, &TeslaDataHandler::onDrivenThisMonthUpdate, tesla_data_widget,
                        &TeslaDataMultiWidget::updateDataDouble);
                break;

            case 29:
                connect(this, &TeslaDataHandler::onGpsHeadingUpdate, tesla_data_widget,
                        &TeslaDataMultiWidget::updateDataDouble);
                break;

            case 30:
                connect(this, &TeslaDataHandler::onAutoSeatClimateLeftUpdate,
                        tesla_data_widget, &TeslaDataMultiWidget::updateDataBool);
                break;

            case 31:
                connect(this, &TeslaDataHandler::onAutoSeatClimateRightUpdate,
                        tesla_data_widget, &TeslaDataMultiWidget::updateDataBool);
                break;

            case 32:
                connect(this, &TeslaDataHandler::onClimateSeatCoolingFrontLeftUpdate,
                        tesla_data_widget, &TeslaDataMultiWidget::updateDataDouble);
                break;

            case 33:
                connect(this, &TeslaDataHandler::onClimateSeatCoolingFrontRightUpdate,
                        tesla_data_widget, &TeslaDataMultiWidget::updateDataDouble);
                break;

            case 34:
                connect(this, &TeslaDataHandler::onDefrostForPreconditioningUpdate,
                        tesla_data_widget, &TeslaDataMultiWidget::updateDataBool);
                break;

            case 35:
                connect(this, &TeslaDataHandler::onDefrostModeUpdate,
                        tesla_data_widget, &TeslaDataMultiWidget::updateDataString);
                break;

            case 36:
                connect(this, &TeslaDataHandler::onHvacAutoModeUpdate,
                        tesla_data_widget, &TeslaDataMultiWidget::updateDataString);
                break;

            case 37:
                connect(this, &TeslaDataHandler::onHvacFanSpeedUpdate,
                        tesla_data_widget, &TeslaDataMultiWidget::updateDataDouble);
                break;

            case 38:
                connect(this, &TeslaDataHandler::onHvacFanStatusUpdate,
                        tesla_data_widget, &TeslaDataMultiWidget::updateDataDouble);
                break;

            case 39:
                connect(this, &TeslaDataHandler::onHvacPowerUpdate,
                        tesla_data_widget, &TeslaDataMultiWidget::updateDataString);
                break;

            case 40:
                connect(this, &TeslaDataHandler::onHvacSteeringWheelHeatLevelUpdate,
                        tesla_data_widget, &TeslaDataMultiWidget::updateDataDouble);
                break;

            case 41:
                connect(this, &TeslaDataHandler::onPreconditioningEnabledUpdate,
                        tesla_data_widget, &TeslaDataMultiWidget::updateDataBool);
                break;

            case 42:
                connect(this, &TeslaDataHandler::onRearDefrostEnabledUpdate,
                        tesla_data_widget, &TeslaDataMultiWidget::updateDataBool);
                break;

            case 43:
                connect(this, &TeslaDataHandler::onSeatHeaterLeftUpdate,
                        tesla_data_widget, &TeslaDataMultiWidget::updateDataDouble);
                break;

            case 44:
                connect(this, &TeslaDataHandler::onSeatHeaterRightUpdate,
                        tesla_data_widget, &TeslaDataMultiWidget::updateDataDouble);
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
    emit onTeslaRequest(packet);
}

void TeslaDataHandler::plusTargetTemperature() {
    uint32_t packet_length = 1;
    uint8_t msg_type = 0x62;
    QByteArray packet;
    QDataStream stream(&packet, QIODevice::WriteOnly);
    stream << packet_length;
    stream << msg_type;
    emit onTeslaRequest(packet);
}

void TeslaDataHandler::minusTargetTemperature() {
    uint32_t packet_length = 1;
    uint8_t msg_type = 0x61;
    QByteArray packet;
    QDataStream stream(&packet, QIODevice::WriteOnly);
    stream << packet_length;
    stream << msg_type;
    emit onTeslaRequest(packet);
}

