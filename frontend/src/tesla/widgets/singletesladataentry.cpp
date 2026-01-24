#include "singletesladataentry.hh"

#include <qcoreevent.h>
#include <QFile>
#include <QFont>
#include <QMainWindow>
#include <QResizeEvent>
#include <cmath>

SingleTeslaDataEntry::SingleTeslaDataEntry(
    QWidget *parent, TeslaDataProperty *td_property, const QString &entry_title
)
    : TeslaDataWidget{parent, td_property} {
    setObjectName("singleTeslaDataEntry");
    layout = new QGridLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(0);
    setLayout(layout);

    title_label = new QLabel(this);
    title_label->setObjectName("titleLabel");
    title_label->setAlignment(Qt::AlignLeft | Qt::AlignBottom);
    title_label->setContentsMargins(0, 0, 0, 0);
    title_label->setText(entry_title);
    title_label_font = QFont("Gotham Rounded Medium", height() / 2);
    title_label->setFont(title_label_font);
    layout->addWidget(title_label, 0, 0, 1, 6, Qt::AlignLeft | Qt::AlignBottom);

    value_label = new QLabel(this);
    value_label->setObjectName("valueLabel");
    value_label->setAlignment(Qt::AlignLeft | Qt::AlignBottom);
    value_label->setContentsMargins(0, 0, 0, 0);
    value_label->setText("No Data");
    value_label_font = QFont("Gotham Rounded Medium", height() / 2);
    value_label->setFont(value_label_font);
    layout->addWidget(value_label, 1, 0, 1, 4, Qt::AlignLeft | Qt::AlignCenter);

    unit_label = new QLabel(this);
    unit_label->setObjectName("valueLabel");
    unit_label->setAlignment(Qt::AlignRight | Qt::AlignBottom);
    unit_label->setContentsMargins(0, 0, 0, 0);
    unit_label->setText(QString::fromStdString(td_property->unit));
    unit_label_font = QFont("Gotham Rounded Medium", height() / 2);
    unit_label->setFont(unit_label_font);
    layout->addWidget(unit_label, 1, 5, 1, 2);

    setStyle("singletesladataentry");
}

void SingleTeslaDataEntry::updateDataDouble(const double &value, const quint64 &timestamp) {
    int value_rounded = static_cast<int>(std::round(value));
    value_label->setText(QString::number(value_rounded));
}

void SingleTeslaDataEntry::updateDataString(const QString &value, const quint64 &timestamp) {
}

void SingleTeslaDataEntry::updateDataBool(const bool &value, const quint64 &timestamp) {
}

void SingleTeslaDataEntry::updateDataLocation(const double &value_latitude, const double &value_longitude,
                                              const quint64 &timestamp) {
}

void SingleTeslaDataEntry::resizeEvent(QResizeEvent *event) {
    QWidget::resizeEvent(event);

    const int new_width = event->size().width();

    title_label_font.setPointSize(new_width / 15);
    title_label->setFont(title_label_font);

    value_label_font.setPointSize(new_width / 8);
    value_label->setFont(value_label_font);

    unit_label_font.setPointSize(new_width / 15);
    unit_label->setFont(unit_label_font);
    unit_label->setContentsMargins(0, 0, 0, new_width / 80);
}

