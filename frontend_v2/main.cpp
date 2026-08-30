#include <QFont>
#include <QFontDatabase>
#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QQuickStyle>
#include <QtQml>
#include <memory>

#include "core/appconfig.hh"
#include "core/charging/chargingdata.hh"
#include "core/idlewatcher.hh"
#include "core/connectionprobe.hh"
#include "core/screenpower.hh"
#include "core/logger.hh"
#include "core/media/mediadata.hh"
#include "core/media/mediaimageprovider.hh"
#include "core/notification/notificationhandler.hh"
#include "core/serverclient.hh"
#include "core/settings.hh"
#include "core/spotifyauth.hh"
#include "core/systemstatus.hh"
#include "core/tesla/tesladata.hh"
#include "core/tesla/teslahistory.hh"
#include "core/trip/tripsdata.hh"
#include "core/weather/weatherdata.hh"

int main(int argc, char* argv[]) {
    QGuiApplication app(argc, argv);

    // Install the logger at INFO first so the AppConfig constructor's own startup
    // warnings land, then re-install at the configured level once it is known.
    // This also routes Qt-internal (QML/Quick) messages through the shared
    // formatter under "qt".
    Logger::install(Logger::Level::Info);
    static const Logger logger = Logger::get("app");

    // Load Gotham Rounded Medium and make it the app-wide default so Qt Quick
    // Text picks it up (mirrors the Widgets frontend's main.cpp).
    const int fontId = QFontDatabase::addApplicationFont(
        QStringLiteral(":/resources/fonts/gothamrnd_medium.otf"));
    if (fontId != -1) {
        const QStringList families = QFontDatabase::applicationFontFamilies(fontId);
        if (!families.isEmpty()) {
            app.setFont(QFont(families.at(0)));
        }
    }

    // Settings is constructed BEFORE AppConfig on purpose: it owns the user's
    // saved backend host/port and screensaver timeout, and AppConfig has to see
    // those overrides rather than the environment's values. The socket does not
    // exist yet, so the CONFIG_* wiring is attached further down.
    Settings settings;

    AppConfig config(&settings);
    Logger::install(config.logLevel());
    logger.info(QStringLiteral("Starting frontend_v2 | backend=%1:%2")
                    .arg(config.backendHost())
                    .arg(config.backendPort()));

    // Data layer, constructed eagerly and registered before the engine loads so
    // each QML singleton is this exact instance, already subscribed to the
    // socket before the backend's on-connect snapshot burst. Declared before the
    // engine so they outlive it at shutdown.
    ServerClient serverClient(config.backendHost(), config.backendPort());
    // Now that the socket exists, let Settings serve the backend half of the
    // Options view (CONFIG_SCHEMA / CONFIG_SET / CONFIG_RESTART).
    settings.attachServer(&serverClient);
    TeslaData teslaData(&serverClient);
    // History reads live values off the Tesla singleton (by property id) for the
    // live-graph mode, so it takes a TeslaData pointer.
    TeslaHistory teslaHistory(&serverClient, &teslaData);
    // Trip viewer: request/response over the same socket (TRIP_* codes). No live
    // data, so it only needs the ServerClient.
    TripsData tripsData(&serverClient);
    // Charging view: live CHARGER_STREAM (myenergi) + charger-history / month
    // request-response over the same socket.
    ChargingData chargingData(&serverClient);
    auto mediaCache = std::make_shared<MediaImageCache>();
    MediaData mediaData(&serverClient, mediaCache);
    WeatherData weatherData(&serverClient);
    // Frontend-owned notifications: observes the data handlers + connection state
    // and renders config/notifications.json rules. Built before the engine so it
    // is subscribed before serverClient.start() fires the first connect.
    NotificationHandler notificationHandler(&teslaData, &serverClient);
    // Inactivity watcher driving the screensaver: installs an app-wide event
    // filter (needs qApp, already constructed above). Timeout from AppConfig.
    IdleWatcher idleWatcher(config.screensaverTimeoutMs());
    // Panel power-down, a longer step beyond the screensaver. Driven by the same
    // activity stream; its settings are bound from Theme in Main.qml, so it stays
    // disarmed until the user enables it. It only DECIDES — backend/display_service
    // does the switching, because system calls belong to the backend.
    ScreenPower screenPower;
    screenPower.attachServer(&serverClient);
    // One-shot reachability check for the backend address settings. Independent of
    // serverClient, which owns the live session and must keep reconnecting.
    ConnectionProbe connectionProbe;
    // The Options view's maintenance dashboard. Polls only while its panel is on
    // screen, so a settings screen nobody opened costs nothing.
    SystemStatus systemStatus;
    systemStatus.attachServer(&serverClient);
    // Spotify re-authorization. Entirely the backend's job — it opens the consent
    // page in the host browser and catches the redirect — so this side only tracks
    // progress for the dialog.
    SpotifyAuth spotifyAuth;
    spotifyAuth.attachServer(&serverClient);
    QObject::connect(&idleWatcher, &IdleWatcher::activity, &screenPower,
                     &ScreenPower::onActivity);

    // Pin the Qt Quick Controls style to Basic — the style the custom control
    // styling (e.g. TripComboBox's themed field / popup / delegate) is written for.
    // Without this the platform default wins: on Windows that's the native style,
    // which refuses ComboBox background/contentItem customization (it warns and
    // renders native), so the dark theme only took on the Linux target. Must be set
    // before the engine loads any Controls.
    QQuickStyle::setStyle(QStringLiteral("Basic"));

    QQmlApplicationEngine engine;
    // The engine takes ownership of the image provider; it shares the cache with
    // MediaData via shared_ptr, so neither dangles regardless of teardown order.
    engine.addImageProvider(QStringLiteral("media"), new MediaImageProvider(mediaCache));

    qmlRegisterSingletonInstance("frontend_v2", 1, 0, "App", &config);
    qmlRegisterSingletonInstance("frontend_v2", 1, 0, "Server", &serverClient);
    qmlRegisterSingletonInstance("frontend_v2", 1, 0, "Tesla", &teslaData);
    qmlRegisterSingletonInstance("frontend_v2", 1, 0, "History", &teslaHistory);
    qmlRegisterSingletonInstance("frontend_v2", 1, 0, "Trips", &tripsData);
    qmlRegisterSingletonInstance("frontend_v2", 1, 0, "Charging", &chargingData);
    qmlRegisterSingletonInstance("frontend_v2", 1, 0, "Media", &mediaData);
    qmlRegisterSingletonInstance("frontend_v2", 1, 0, "Weather", &weatherData);
    qmlRegisterSingletonInstance("frontend_v2", 1, 0, "Notifications", &notificationHandler);
    qmlRegisterSingletonInstance("frontend_v2", 1, 0, "Idle", &idleWatcher);
    qmlRegisterSingletonInstance("frontend_v2", 1, 0, "Display", &screenPower);
    qmlRegisterSingletonInstance("frontend_v2", 1, 0, "Probe", &connectionProbe);
    qmlRegisterSingletonInstance("frontend_v2", 1, 0, "System", &systemStatus);
    qmlRegisterSingletonInstance("frontend_v2", 1, 0, "SpotifyAuth", &spotifyAuth);
    qmlRegisterSingletonInstance("frontend_v2", 1, 0, "Settings", &settings);

    QObject::connect(
        &engine, &QQmlApplicationEngine::objectCreationFailed, &app,
        []() { QCoreApplication::exit(-1); }, Qt::QueuedConnection);
    engine.loadFromModule("frontend_v2", "Main");

    serverClient.start();

    return QCoreApplication::exec();
}
