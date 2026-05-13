#include <QApplication>
#include "mainwindow.hh"
#include "config/appconfig.hh"
#include "utils/logger.hh"
#include <QFontDatabase>

int main(int argc, char *argv[]) {
    QApplication a(argc, argv);

    // AppConfig::load() needs the logger for its own startup lines, so
    // install with the INFO default first. Once we've parsed the env
    // var below, raise/lower the threshold to the configured level.
    Logger::install(Logger::Level::Info);
    static const Logger app_log = Logger::get("app");
    app_log.info("Tesla-Homedash frontend starting");

    int font_id = QFontDatabase::addApplicationFont(":/resources/fonts/gothamrnd_medium.otf");

    if (font_id != -1) {
        QString family = QFontDatabase::applicationFontFamilies(font_id).at(0);
        QFont font(family);
        a.setFont(font);
    } else {
        app_log.warning(QStringLiteral("Font load failed: gothamrnd_medium.otf (font_id=%1)").arg(font_id));
    }

    const AppConfig config = AppConfig::load();
    Logger::install(config.log_level);

    MainWindow w(nullptr, config);
    if (config.fullscreen) {
        w.showFullScreen();
    } else {
        w.show();
    }
    return a.exec();
}
