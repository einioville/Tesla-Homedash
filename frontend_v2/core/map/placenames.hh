#ifndef FRONTEND_V2_PLACENAMES_HH
#define FRONTEND_V2_PLACENAMES_HH

#include <QHash>
#include <QList>
#include <QSet>
#include <QObject>
#include <QString>
#include <QTimer>
#include <QVariantList>

class QNetworkAccessManager;
class QNetworkReply;

/**
 * PlaceNames — OpenStreetMap place names for the maps (QML `PlaceNames`, issue #54).
 * The basemaps are imagery without labels, so the names are fetched from the Overpass
 * API (`place=*` with a name; ODbL, keyless) and drawn by the map itself.
 *
 * Names are fetched per slippy-map tile, at one of three tile zooms by how small a place
 * is: cities and towns per z6 tile, villages, suburbs and islands per z9, hamlets,
 * neighbourhoods and the rest per z12. Each tile is one Overpass request, ever: the
 * result is kept in memory and on disk (`<GenericCacheLocation>/Tesla-Homedash/
 * place-names/<z>-<x>-<y>.json`, an empty tile too) and refreshed only when half a year
 * old, so roads driven every day cost nothing after the first time.
 *
 * Overpass is shared and slow — 30 to 60 s for a busy request is normal — so requests go
 * one at a time, two seconds apart, the tiles of the newest view first; a tile no view has
 * wanted for two minutes is dropped from the queue. A failed request goes to the next of
 * three public servers, and once all three have failed in a row the queue pauses (30 s,
 * doubling to 10 min) rather than retrying in a loop.
 *
 * `query()` answers from what is cached and queues the rest; `revision` changes when a
 * tile arrives, which is a map's cue to ask again.
 */
class PlaceNames : public QObject {
    Q_OBJECT
    Q_PROPERTY(int revision READ revision NOTIFY revisionChanged)

public:
    explicit PlaceNames(QObject *parent = nullptr);

    int revision() const { return m_revision; }

    // The places to label in [south, north] x [west, east] at map zoom `zoom`, as
    // { name, lat, lon, rank } — rank 0 a city, larger is smaller. Tiles not cached
    // yet are queued, and come in a later answer.
    Q_INVOKABLE QVariantList query(double south, double west, double north, double east,
                                   double zoom);

signals:
    void revisionChanged();

private:
    struct Place {
        QString name;
        int kind;
        double lat;
        double lon;
    };
    struct Tile {
        QList<Place> places;
        qint64 fetchedMs = 0;
    };

    static quint64 key(int z, int x, int y);
    QString cachePath(quint64 tileKey) const;
    // The tile from memory, else from disk; nullptr when neither has it.
    const Tile *cached(quint64 tileKey);
    // Puts `missing` at the head of the queue, `stale` at its tail.
    void enqueue(const QList<quint64> &missing, const QList<quint64> &stale);
    void fetchNext();
    void onReply(QNetworkReply *reply, quint64 tileKey);
    bool store(quint64 tileKey, const QByteArray &json);

    QNetworkAccessManager *m_network;
    QString m_cacheDir;
    QHash<quint64, Tile> m_tiles;
    // Tiles known not to be on disk, so a view does not look for each on every query.
    QSet<quint64> m_notOnDisk;
    // Tiles to fetch, the most wanted first, and when a view last wanted each.
    QList<quint64> m_queue;
    QHash<quint64, qint64> m_wantedMs;
    bool m_busy = false;
    // The server asked next, and how many have failed in a row.
    int m_server = 0;
    int m_failures = 0;
    int m_backoffMs = 0;
    QTimer m_next;
    int m_revision = 0;
};

#endif  // FRONTEND_V2_PLACENAMES_HH
