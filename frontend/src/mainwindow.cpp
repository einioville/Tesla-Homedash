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

MainWindow::MainWindow(QWidget *parent, const AppConfig &config) : QMainWindow(parent) {
    vehicle = new Vehicle(this);

    central = new QWidget(this);
    central->setContentsMargins(0, 0, 0, 0);
    setCentralWidget(central);

    QVector<TeslaDataProperty *> props;
    props.push_back(vehicle->getProperty("VehicleSpeed"));
    props.push_back(vehicle->getProperty("BatteryLevel"));
    props.push_back(vehicle->getProperty("EstBatteryRange"));

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

    media_player_card = new MediaPlayerCard(this);
    grid->addWidget(media_player_card, 6, 0, 4, 4);

    list_2 = new TeslaDataEntryList(this, 3, props2, titles2, 1);
    grid->addWidget(list_2, 0, 8, 6, 4);

    list_1 = new TeslaDataEntryList(this, 3, props, titles, 2);
    grid->addWidget(list_1, 0, 12, 6, 4);

    main_weather = new MainWeather(this);
    grid->addWidget(main_weather, 6, 4, 4, 8);

    climate_card = new ClimateControllerCard(this, vehicle->getProperty("InsideTemp"), vehicle->getProperty("OutsideTemp"),
                                             vehicle->getProperty("HvacLeftTemperatureRequest"),
                                             vehicle->getProperty("HvacPower"));
    grid->addWidget(climate_card, 6, 12, 4, 4);

    setStyleSheet("background-color: #121212");

    // Fullscreen mode skips the fixed-size lock so the QMainWindow can grow
    // to whatever physical screen the dashboard is running on. Windowed
    // mode keeps the original 1280x800 layout assumptions and locks the
    // window size.
    resize(config.window_width, config.window_height);
    if (!config.fullscreen) {
        setFixedSize(config.window_width, config.window_height);
    }

    tesla_data_handler = new TeslaDataHandler(this, vehicle);
    media_data_handler = new MediaPlayerDataHandler(this);
    weather_data_handler = new WeatherDataHandler(this);

    list_1->connectItems(tesla_data_handler);
    list_2->connectItems(tesla_data_handler);
    climate_card->connectItems(tesla_data_handler);
    map->connectToTeslaDataHandler(tesla_data_handler);
    media_data_handler->connectPlayer(media_player_card);
    weather_data_handler->connectMainWeather(main_weather);

    server_client = new ServerClient(this, tesla_data_handler, media_data_handler, weather_data_handler,
                                     config.backend_host, config.backend_port);
    server_client->startClient();

    // Reboot button — placed in a corner of the central widget. Using the
    // grid (rather than absolute move()) keeps it visible regardless of the
    // configured window size.
    reboot = new QPushButton(central);
    reboot->setFixedSize(50, 50);
    reboot->setStyleSheet("background: transparent; border: none");
    grid->addWidget(reboot, 0, 15, 1, 1, Qt::AlignTop | Qt::AlignRight);
    reboot->raise();
    connect(reboot, &QPushButton::clicked, this, &MainWindow::rebootSys);
}

void MainWindow::rebootSys() {
    QProcess::startDetached("sudo reboot");
}

MainWindow::~MainWindow() {
}
