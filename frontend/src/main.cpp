#include <QApplication>
#include "mainwindow.hh"
#include "config/appconfig.hh"
#include "utils/logger.hh"
#include <QFontDatabase>

int main(int argc, char *argv[]) {
    QApplication a(argc, argv);

    // Raspberry Pi OS's default widget palette renders text near-black, which
    // is invisible on the dashboard's dark (#121212) background (the Windows
    // dev default happened to be light). Force white as the app-wide default
    // text colour. This is the lowest-specificity rule, so any per-widget QSS
    // that sets its own colour still overrides it.
    a.setStyleSheet(QStringLiteral("QLabel, QPushButton { color: #FFFFFF; }"));

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
