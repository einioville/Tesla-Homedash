#ifndef VEHICLE_HH
#define VEHICLE_HH

#include <QObject>
#include <QString>
#include <string>
#include <unordered_map>

struct TeslaDataProperty {
    qint32 data_stream_id;
    std::string data_id;
    std::string unit;
    int value_type;
};

class Vehicle : public QObject {
    Q_OBJECT

public:
    explicit Vehicle(QObject *parent);

    TeslaDataProperty *getProperty(const QString &data_id);

private:
    std::unordered_map<QString, TeslaDataProperty> properties;
};

#endif  // VEHICLE_HH
