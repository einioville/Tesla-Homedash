#include "tesladatawidget.hh"

#include <QFile>

TeslaDataWidget::TeslaDataWidget(QWidget *parent, TeslaDataProperty *td_property) : QWidget{parent} {
    tesla_data_property = td_property;
}

void TeslaDataWidget::setStyle(const QString &name) {
    QFile style(":/resources/styles/" + name + ".qss");
    if (style.open(QFile::ReadOnly | QFile::Text)) {
        QTextStream stream(&style);
        setStyleSheet(stream.readAll());
    }
}

quint16 TeslaDataWidget::getTeslaDataPropertyId() const {
    return tesla_data_property->data_stream_id;
}

TeslaDataMultiWidget::TeslaDataMultiWidget(QWidget *parent, QVector<TeslaDataProperty *> td_properties) : QWidget(
    parent) {
    tesla_data_properties = td_properties;
}

void TeslaDataMultiWidget::setStyle(const QString &name) {
    QFile style(":/resources/styles/" + name + ".qss");
    if (style.open(QFile::ReadOnly | QFile::Text)) {
        QTextStream stream(&style);
        setStyleSheet(stream.readAll());
    }
}

QVector<quint16> TeslaDataMultiWidget::getTeslaDataPropertyIds() const {
    QVector<quint16> data_ids;
    data_ids.reserve(tesla_data_properties.size());
    for (TeslaDataProperty *property: tesla_data_properties) {
        data_ids.push_back(property->data_stream_id);
    }
    return data_ids;
}
