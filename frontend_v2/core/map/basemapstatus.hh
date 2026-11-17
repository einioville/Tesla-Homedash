#ifndef FRONTEND_V2_BASEMAPSTATUS_HH
#define FRONTEND_V2_BASEMAPSTATUS_HH

#include <QObject>
#include <QString>
#include <QTimer>
#include <QUrl>

class QNetworkAccessManager;
class QNetworkReply;

/**
 * BasemapStatus — whether MML's tile service answers this display (QML `Basemap`, #87).
 *
 * Qt Location reports no failed tile to QML: it tries a tile five times, gives up, and draws
 * the nearest cached lower-zoom tile stretched in its place, so an MML outage shows as blurred
 * or blank imagery and nothing else. This asks MML for its zoom-0 tile (about 1 KB) every
 * 2 min; `mmlReachable` drops after three failures in a row, 20 s apart, which puts every
 * map on EOX's imagery (items/tesla/BasemapSwitch.qml), and returns after three successes in a
 * row, a minute apart. A type switch reloads every tile on screen, so a single failed request
 * never switches; switching back is also what asks MML again for the tiles Qt gave up on.
 *
 * Only a failure that is MML's counts. An HTTP answer that is not an image (403 for a refused
 * key, a 5xx) is. No answer at all (no connection, nothing in 10 s) sends the same request to
 * EOX, and when EOX does not answer either, the display is offline and nothing changes: the
 * maps keep their imagery, and MML's cached tiles are the sharper ones.
 *
 * Asked by the display, not the backend: what matters is whether this display reaches MML,
 * since it fetches its own tiles (root CLAUDE.md §5.4).
 */
class BasemapStatus : public QObject {
    Q_OBJECT
    // True while MML answers, and with no MML key at all (no probe runs).
    Q_PROPERTY(bool mmlReachable READ mmlReachable NOTIFY mmlReachableChanged)

public:
    // `mmlTilesUrl` is AppConfig's template (%z/%y/%x, the key in its query); empty, nothing
    // is probed.
    explicit BasemapStatus(const QString &mmlTilesUrl, QObject *parent = nullptr);

    bool mmlReachable() const { return m_reachable; }

signals:
    void mmlReachableChanged();

private:
    enum class Answer { Image, NotImage, None };

    void probeMml();
    void probeEox(const QString &mmlReason);
    QNetworkReply *get(const QUrl &url);
    Answer answerOf(QNetworkReply *reply, QString *reason) const;
    void settle(bool mmlUp, const QString &reason);
    void scheduleNext();

    QNetworkAccessManager *m_network;
    QTimer m_next;
    QUrl m_mml;
    QUrl m_eox;
    QString m_mmlKey;
    bool m_reachable = true;
    // Probes in a row that disagree with m_reachable.
    int m_streak = 0;
    bool m_offlineLogged = false;
};

#endif  // FRONTEND_V2_BASEMAPSTATUS_HH
