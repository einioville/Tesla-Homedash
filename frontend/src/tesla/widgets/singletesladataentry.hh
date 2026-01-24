#ifndef SINGLETESLADATAENTRY_HH
#define SINGLETESLADATAENTRY_HH

#include <QLabel>
#include <QHBoxLayout>
#include <QWidget>
#include "tesladatawidget.hh"
#include "../vehicle.hh"
#include <QGridLayout>
#include <QSize>

class SingleTeslaDataEntry : public TeslaDataWidget {
    Q_OBJECT

public:
    explicit SingleTeslaDataEntry(
        QWidget *parent, TeslaDataProperty *td_property, const QString &title
    );

public slots:
    void updateDataDouble(const double &value, const quint64 &timestamp) override;

    void updateDataString(const QString &value, const quint64 &timestamp) override;

    void updateDataBool(const bool &value, const quint64 &timestamp) override;

    void updateDataLocation(const double &value_latitude, const double &value_longitude,
                            const quint64 &timestamp) override;

protected:
    void resizeEvent(QResizeEvent *event) override;

private:
    QGridLayout *layout;

    QLabel *title_label;
    QFont title_label_font;

    QLabel *value_label;
    QFont value_label_font;

    QLabel *unit_label;
    QFont unit_label_font;
};

#endif  // SINGLETESLADATAENTRY_HH
