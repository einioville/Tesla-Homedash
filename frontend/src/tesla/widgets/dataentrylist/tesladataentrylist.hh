//
// Created by ville on 17.10.2025.
//

#ifndef GUI_TESLADATAENTRYLIST_HH
#define GUI_TESLADATAENTRYLIST_HH
#include <QVector>
#include "../singletesladataentry.hh"
#include "../../vehicle.hh"
#include <QString>
#include <QVBoxLayout>
#include "../../datahandler/tesladatahandler.hh"
#include <QFrame>
#include <QGraphicsDropShadowEffect>

#include "../tesladatawidget.hh"

class TeslaDataEntryList : public QFrame {
    Q_OBJECT

public:
    TeslaDataEntryList(QWidget *parent, int size, QVector<TeslaDataProperty *> &properties,
                       const QVector<QString> &titles, int place);

    void connectItems(const TeslaDataHandler *handler);

private:
    QVector<SingleTeslaDataEntry *> items;
    QVector<QFrame *> separator_lines;
    QVBoxLayout *layout;
    QGraphicsDropShadowEffect *shadow;
};

#endif //GUI_TESLADATAENTRYLIST_HH
