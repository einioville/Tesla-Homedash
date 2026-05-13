#ifndef VEHICLE_HH
#define VEHICLE_HH

#include <QObject>
#include <QString>
#include <string>
#include <unordered_map>

/**
 * TeslaDataProperty — frontend-side metadata for a single Tesla telemetry
 * field. Mirrors the backend's `VehicleDataProperty` entries in config.json
 * but only carries what widgets need to bind and render.
 *
 *   data_stream_id — protocol id matched against the wire packet
 *   data_id        — human-readable name (matches the config.json key)
 *   unit           — display unit, empty for dimensionless fields
 *   value_type     — 0=double, 1=string, 2=bool, 3=location
 */
struct TeslaDataProperty {
    qint32 data_stream_id;
    std::string data_id;
    std::string unit;
    int value_type;
};

/**
 * Vehicle — frontend-side registry of TeslaDataProperty entries. Populated
 * once at construction. Widgets request properties by name via
 * getProperty(); the resulting pointer remains valid for the Vehicle's
 * lifetime (the map is never mutated post-construction).
 */
class Vehicle : public QObject {
    Q_OBJECT

public:
    explicit Vehicle(QObject *parent);

    TeslaDataProperty *getProperty(const QString &data_id);

private:
    std::unordered_map<QString, TeslaDataProperty> properties;
};

#endif  // VEHICLE_HH
