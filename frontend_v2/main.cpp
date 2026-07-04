#include <QFont>
#include <QFontDatabase>
#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QtQml>  // qmlRegisterSingletonInstance + QQmlEngine
#include <memory>

#include "core/appconfig.hh"
#include "core/logger.hh"
#include "core/media/mediadata.hh"
#include "core/media/mediaimageprovider.hh"
#include "core/notification/notificationhandler.hh"
#include "core/serverclient.hh"
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

    AppConfig config;
    Logger::install(config.logLevel());
    logger.info(QStringLiteral("Starting frontend_v2 | backend=%1:%2")
                    .arg(config.backendHost())
                    .arg(config.backendPort()));

    // Data layer, constructed eagerly and registered before the engine loads so
    // each QML singleton is this exact instance, already subscribed to the
    // socket before the backend's on-connect snapshot burst. Declared before the
    // engine so they outlive it at shutdown.
    ServerClient serverClient(config.backendHost(), config.backendPort());
    TeslaData teslaData(&serverClient);
    // History reads live values off the Tesla singleton (by property id) for the
    // live-graph mode, so it takes a TeslaData pointer.
    TeslaHistory teslaHistory(&serverClient, &teslaData);
    // Trip viewer: request/response over the same socket (TRIP_* codes). No live
    // data, so it only needs the ServerClient.
    TripsData tripsData(&serverClient);
    auto mediaCache = std::make_shared<MediaImageCache>();
    MediaData mediaData(&serverClient, mediaCache);
    WeatherData weatherData(&serverClient);
    // Frontend-owned notifications: observes the data handlers + connection state
    // and renders config/notifications.json rules. Built before the engine so it
    // is subscribed before serverClient.start() fires the first connect.
    NotificationHandler notificationHandler(&teslaData, &serverClient);

    QQmlApplicationEngine engine;
    // The engine takes ownership of the image provider; it shares the cache with
    // MediaData via shared_ptr, so neither dangles regardless of teardown order.
    engine.addImageProvider(QStringLiteral("media"), new MediaImageProvider(mediaCache));

    qmlRegisterSingletonInstance("frontend_v2", 1, 0, "App", &config);
    qmlRegisterSingletonInstance("frontend_v2", 1, 0, "Server", &serverClient);
    qmlRegisterSingletonInstance("frontend_v2", 1, 0, "Tesla", &teslaData);
    qmlRegisterSingletonInstance("frontend_v2", 1, 0, "History", &teslaHistory);
    qmlRegisterSingletonInstance("frontend_v2", 1, 0, "Trips", &tripsData);
    qmlRegisterSingletonInstance("frontend_v2", 1, 0, "Media", &mediaData);
    qmlRegisterSingletonInstance("frontend_v2", 1, 0, "Weather", &weatherData);
    qmlRegisterSingletonInstance("frontend_v2", 1, 0, "Notifications", &notificationHandler);

    QObject::connect(
        &engine, &QQmlApplicationEngine::objectCreationFailed, &app,
        []() { QCoreApplication::exit(-1); }, Qt::QueuedConnection);
    engine.loadFromModule("frontend_v2", "Main");

    serverClient.start();

    return QCoreApplication::exec();
}
