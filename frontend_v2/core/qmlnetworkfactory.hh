#ifndef FRONTEND_V2_QMLNETWORKFACTORY_HH
#define FRONTEND_V2_QMLNETWORKFACTORY_HH

#include <QNetworkAccessManager>
#include <QQmlNetworkAccessManagerFactory>

/**
 * QmlNetworkFactory — the network access the QML engine's own fetches go through: every
 * XMLHttpRequest and every Image with an http(s) source (the radar's frames and lightning,
 * the road cameras). Qt's default manager has no timeout at all, so a server that accepts a
 * request and then goes silent would leave it pending for good; this one gives up after
 * kTransferTimeoutMs without a byte, and the request ends as an error (XHR status 0). The
 * maps' tiles have their own manager in the Qt Location plugin, and the C++ fetchers their
 * own timeouts. create() runs on whichever thread loads, so it touches nothing shared.
 */
class QmlNetworkFactory : public QQmlNetworkAccessManagerFactory {
public:
    QNetworkAccessManager *create(QObject *parent) override {
        auto *manager = new QNetworkAccessManager(parent);
        manager->setTransferTimeout(kTransferTimeoutMs);
        return manager;
    }

private:
    static constexpr int kTransferTimeoutMs = 30 * 1000;
};

#endif  // FRONTEND_V2_QMLNETWORKFACTORY_HH
