#include <QApplication>
#include "mainwindow.hh"
#include "config/appconfig.hh"
#include <QFontDatabase>

int main(int argc, char *argv[]) {
    QApplication a(argc, argv);

    int font_id = QFontDatabase::addApplicationFont(":/resources/fonts/gothamrnd_medium.otf");

    if (font_id != -1) {
        QString family = QFontDatabase::applicationFontFamilies(font_id).at(0);
        QFont font(family);
        a.setFont(font);
    } else {
        qDebug() << font_id;
    }

    const AppConfig config = AppConfig::load();

    MainWindow w(nullptr, config);
    if (config.fullscreen) {
        w.showFullScreen();
    } else {
        w.show();
    }
    return a.exec();
}
