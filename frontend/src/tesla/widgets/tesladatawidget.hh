#ifndef TESLADATAWIDGET_HH
#define TESLADATAWIDGET_HH

#include <QJsonObject>
#include <QWidget>
#include <QVariant>
#include <QMap>
#include <QVector>

#include "../vehicle.hh"

class TeslaDataWidget : public QWidget {
    Q_OBJECT

public:
    explicit TeslaDataWidget(
        QWidget *parent, TeslaDataProperty *td_property
    );

    void setStyle(const QString &name);

    quint16 getTeslaDataPropertyId() const;

public slots:
    virtual void updateDataDouble(const double &value, const quint64 &timestamp) = 0;

    virtual void updateDataString(const QString &value, const quint64 &timestamp) = 0;

    virtual void updateDataBool(const bool &value, const quint64 &timestamp) = 0;

    virtual void updateDataLocation(const double &value_latitude, const double &value_longitude,
                                    const quint64 &timestamp) = 0;

private:
    TeslaDataProperty *tesla_data_property;
};

class TeslaDataMultiWidget : public QWidget {
    Q_OBJECT;

public:
    explicit TeslaDataMultiWidget(QWidget *parent, QVector<TeslaDataProperty *> td_properies);

    void setStyle(const QString &name);

    QVector<quint16> getTeslaDataPropertyIds() const;

public slots:
    virtual void updateDataDouble(const double &value, const quint64 &timestamp) = 0;

    virtual void updateDataString(const QString &value, const quint64 &timestamp) = 0;

    virtual void updateDataBool(const bool &value, const quint64 &timestamp) = 0;

    virtual void updateDataLocation(const double &value_latitude, const double &value_longitude,
                                    const quint64 &timestamp) = 0;

private:
    QVector<TeslaDataProperty *> tesla_data_properties;
};

#endif  // TESLADATAWIDGET_HH
