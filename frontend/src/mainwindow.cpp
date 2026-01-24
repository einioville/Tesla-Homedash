#include "mainwindow.hh"
#include "mainwindow.hh"
#include <QString>
#include <QGridLayout>
#include <QFrame>
#include "tesla/widgets/dataentrylist/tesladataentrylist.hh"
#include "server_client/serverclient.hh"
#include "tesla/datahandler/tesladatahandler.hh"
#include "mediaplayer/widgets/mediaplayercard.hh"
#include <QUrl>
#include <QQuickItem>
#include <QGeoPositionInfo>
#include <QPainterPath>
#include <QTimer>
#include <QGraphicsDropShadowEffect>
#include <QProcess>

MainWindow::MainWindow(QWidget *parent) : QMainWindow(parent) {
    vehicle = new Vehicle(this);

    central = new QWidget(this);
    central->setContentsMargins(0, 0, 0, 0);
    setCentralWidget(central);

    QVector<TeslaDataProperty *> props;
    props.push_back(vehicle->getProperty("VehicleSpeed"));
    props.push_back(vehicle->getProperty("BatteryLevel"));
    props.push_back(vehicle->getProperty("RatedRange"));

    QVector<QString> titles;
    titles.push_back("Nopeus");
    titles.push_back("Akun Varaus");
    titles.push_back("Range");

    QVector<TeslaDataProperty *> props2;
    props2.push_back(vehicle->getProperty("DrivenToday"));
    props2.push_back(vehicle->getProperty("DrivenThisMonth"));
    props2.push_back(vehicle->getProperty("Odometer"));

    QVector<QString> titles2;
    titles2.push_back("Ajettu Tänään");
    titles2.push_back("Ajettu Tässä Kuussa");
    titles2.push_back("Odometer");

    grid = new QGridLayout(central);
    grid->setContentsMargins(10, 10, 10, 10);
    grid->setSpacing(10);

    QVector<TeslaDataProperty *> props3;
    props3.push_back(vehicle->getProperty("GpsHeading"));
    props3.push_back(vehicle->getProperty("Location"));

    map = new TeslaMap(this, props3);
    grid->addWidget(map, 0, 0, 6, 8);

    spotify_player = new MediaplayerCard(this);
    grid->addWidget(spotify_player, 6, 0, 4, 4);

    list_2 = new TeslaDataEntryList(this, 3, props2, titles2, 1);
    grid->addWidget(list_2, 0, 8, 6, 4);

    list_1 = new TeslaDataEntryList(this, 3, props, titles, 2);
    grid->addWidget(list_1, 0, 12, 6, 4);

    mw = new MainWeather(this);
    grid->addWidget(mw, 6, 4, 4, 8);

    //frame_6 = new QFrame(this);
    //frame_6->setStyleSheet("background-color: pink");
    cccard = new ClimateControllerCard(this, vehicle->getProperty("InsideTemp"), vehicle->getProperty("OutsideTemp"),
                                       vehicle->getProperty("HvacLeftTemperatureRequest"),
                                       vehicle->getProperty("HvacPower"));
    grid->addWidget(cccard, 6, 12, 4, 4);

    //setFixedSize(500, 500);
    setStyleSheet("background-color: #121212");

    //setFixedSize(1280, 800);
    resize(1280, 800);
    setFixedSize(1280, 800);

    tth = new TeslaDataHandler(this, vehicle);

    sdh = new MediaplayerDataHandler(this);

    wdh = new WeatherDataHandler(this);

    list_1->connectItems(tth);
    list_2->connectItems(tth);

    cccard->connectItems(tth);

    map->connectToTeslaDataHandler(tth);

    sdh->connectPlayer(spotify_player);

    wdh->connectMainWeather(mw);

    server_client = new ServerClient(this, tth, sdh, wdh, "127.0.0.1", 6969);
    server_client->startClient();

    reboot = new QPushButton(this);
    reboot->setFixedSize(50, 50);
    reboot->move(1230, 0);
    reboot->setStyleSheet("background: transparent; border: none");
    connect(reboot, &QPushButton::clicked, this, &MainWindow::rebootSys);
}

void MainWindow::rebootSys() {
    QProcess::startDetached("sudo reboot");
}

MainWindow::~MainWindow() {
}
