//
// Created by ville on 17.10.2025.
//

#include "tesladataentrylist.hh"
#include <QString>
#include <QFile>
#include <QColor>

TeslaDataEntryList::TeslaDataEntryList(QWidget *parent, int size, QVector<TeslaDataProperty *> &properties,
                                       const QVector<QString> &titles, int place) : QFrame(parent) {
    setObjectName("tesladataentrylist_" + QString::number(place));

    QFile style(":/resources/styles/tesladataentrylist.qss");
    if (style.open(QFile::ReadOnly | QFile::Text)) {
        QTextStream stream(&style);
        setStyleSheet(stream.readAll());
    }

    shadow = new QGraphicsDropShadowEffect(this);
    shadow->setBlurRadius(50);
    shadow->setXOffset(10);
    shadow->setYOffset(10);
    shadow->setColor(QColor(0, 0, 0, 150));
    setGraphicsEffect(shadow);

    layout = new QVBoxLayout(this);
    layout->setContentsMargins(10, 10, 10, 10);
    layout->setSpacing(0);

    items.reserve(size);
    for (int i = 0; i < size; i++) {
        layout->addStretch();
        if (i != 0) {
            separator_lines.append(new QFrame(this));
            QFrame *line = separator_lines.constLast();
            line->setFrameStyle(QFrame::NoFrame);
            line->setFixedHeight(4);
            line->setStyleSheet("background-color: white; color: white; border: none; border-radius: 2px");
            layout->addWidget(line);
            layout->addStretch();
        }
        items.push_back(new SingleTeslaDataEntry(this, properties[i], titles[i]));
        items[i]->setStyleSheet("background-color: transparent");
        layout->addWidget(items[i]);
    }
    layout->addStretch();
}

void TeslaDataEntryList::connectItems(const TeslaDataHandler *handler) {
    for (SingleTeslaDataEntry *item: items) {
        handler->connectToDataUpdateSignal(item->getTeslaDataPropertyId(), item);
    }
}
