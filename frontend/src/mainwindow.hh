#ifndef MAINWINDOW_HH
#define MAINWINDOW_HH

#include <QMainWindow>
#include "tesla/widgets/singletesladataentry.hh"
#include "tesla/datahandler/tesladatahandler.hh"
#include "tesla/vehicle.hh"
#include "tesla/widgets/dataentrylist/tesladataentrylist.hh"
#include "server_client/serverclient.hh"
#include "mediaplayer/datahandler/mediaplayerdatahandler.hh"
#include "tesla/widgets/map/teslamap.hh"
#include <QGeoCoordinate>
#include "weather/widgets/mainweather.hh"
#include "weather/datahandler/weatherdatahandler.hh"
#include "tesla/widgets/climate/climatecontrollercard.hh"
#include "config/appconfig.hh"
#include <QPushButton>

/**
 * MainWindow — the dashboard's top-level QMainWindow.
 *
 * Owns and lays out every widget (10x16 QGridLayout): map, two telemetry
 * lists, media player card, weather panel, climate controller, plus a
 * corner reboot button. Also constructs the data handlers
 * (TeslaDataHandler, MediaplayerDataHandler, WeatherDataHandler) and the
 * ServerClient that ties them to the backend's TCP server.
 *
 * Construction is parameterised by AppConfig (env-driven backend address,
 * window size, fullscreen flag).
 */
class MainWindow : public QMainWindow {
    Q_OBJECT

public:
    explicit MainWindow(QWidget *parent, const AppConfig &config);

    ~MainWindow() override;

private slots:
    void rebootSys();

private:
    Vehicle *vehicle;

    //QFrame *frame_1;
    MediaplayerCard *spotify_player;
    QFrame *frame_3;
    QFrame *frame_4;
    QFrame *frame_6;

    QWidget *central;
    QGridLayout *grid;
    TeslaDataEntryList *list_1;
    TeslaDataEntryList *list_2;
    ClimateControllerCard *cccard;

    TeslaMap *map;

    TeslaDataHandler *tth;
    MediaplayerDataHandler *sdh;
    WeatherDataHandler *wdh;
    ServerClient *server_client;
    MainWeather *mw;
    QPushButton *reboot;
};
#endif  // MAINWINDOW_HH
