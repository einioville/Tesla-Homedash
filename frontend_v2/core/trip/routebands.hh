#ifndef FRONTEND_V2_ROUTEBANDS_HH
#define FRONTEND_V2_ROUTEBANDS_HH

#include <QAbstractListModel>
#include <QGeoCoordinate>
#include <QHash>
#include <QList>
#include <QPointF>
#include <QPolygonF>
#include <QVariantMap>

/**
 * RouteBands — a route coloured by speed, drawn by items/tesla/SpeedRoute.qml: the
 * Trips map's trip (`Trips.route`) and the drive on the car's maps (`CurrentDrive.route`).
 * It holds the fixes and builds what the Shapes draw, so no per-point JavaScript runs on
 * a load, a new fix or any frame of a pan or zoom (#83).
 *
 *  - The geometry is in a GeoFrame's coordinates: EPSG:3857 metres east and south of
 *    `origin`, the first fix. Each segment goes to the speed band of the mean of its two
 *    fixes (`bandCount` bands `bandKmh` wide, which the drawer sets from Theme; nothing is
 *    built until it has), and a band's consecutive segments join into one run, a
 *    QPolygonF, which PathMultiline takes as it is. casing() is the line whole, for a
 *    drawer that strokes one under it.
 *  - The rows are chunks of the route, each one Shape in the drawer. A reset puts its
 *    fixes in one chunk; fixes appended after it go to chunks of at most kGrowSegments
 *    segments, so a new fix has one short chunk processed again, not the whole drive. A
 *    row's `revision` changes with its geometry: runs() and casing() are invokables, which
 *    register no binding dependency, so the drawer's bindings read it too.
 *  - positionAt() answers the fix nearest a time, for the Trips map's inspect marker.
 */
class RouteBands : public QAbstractListModel {
    Q_OBJECT
    Q_PROPERTY(QGeoCoordinate origin READ origin NOTIFY originChanged)
    Q_PROPERTY(int bandCount READ bandCount WRITE setBandCount NOTIFY bandsChanged)
    Q_PROPERTY(double bandKmh READ bandKmh WRITE setBandKmh NOTIFY bandsChanged)

public:
    // speed in km/h, ts in epoch ms (0 where nothing asks for a time).
    struct Fix {
        double latitude = 0.0;
        double longitude = 0.0;
        double speed = 0.0;
        qint64 ts = 0;
    };

    enum Role { RevisionRole = Qt::UserRole + 1 };

    explicit RouteBands(QObject *parent = nullptr);

    int rowCount(const QModelIndex &parent = {}) const override;
    QVariant data(const QModelIndex &index, int role) const override;
    QHash<int, QByteArray> roleNames() const override;

    QGeoCoordinate origin() const;
    int bandCount() const { return m_bandCount; }
    void setBandCount(int count);
    double bandKmh() const { return m_bandKmh; }
    void setBandKmh(double kmh);

    bool isEmpty() const { return m_fixes.isEmpty(); }

    // Replaces the route.
    void reset(const QList<Fix> &fixes);
    // Adds a fix at its end.
    void append(const Fix &fix);

    // Band `band`'s runs in chunk `chunk`; the chunk's line whole.
    Q_INVOKABLE QList<QPolygonF> runs(int chunk, int band) const;
    Q_INVOKABLE QList<QPolygonF> casing(int chunk) const;
    // The fix nearest `ts` as { lat, lon, bearing }, the bearing toward the next fix (from
    // the one before at the end), in degrees clockwise from north; empty with no fixes.
    Q_INVOKABLE QVariantMap positionAt(double ts) const;

signals:
    void originChanged();
    void bandsChanged();

private:
    struct Chunk {
        QList<QPolygonF> casing;
        QList<QList<QPolygonF>> bands;
        int segments = 0;
        int lastBand = -1;
        int revision = 0;
    };

    QPointF local(const Fix &fix) const;
    int bandOf(double kmh) const;
    bool configured() const { return m_bandCount > 0 && m_bandKmh > 0.0; }
    void setOrigin(const QList<Fix> &fixes);
    // The chunks for every fix, the reset's in one and the appended ones after it.
    void build();
    // The segment from fix i-1 to fix i into `chunk`.
    void addSegment(Chunk &chunk, qsizetype i) const;
    // Whether the segment ending at fix i opens a chunk of its own.
    bool opensChunk() const;

    QList<Fix> m_fixes;
    // How many of the fixes came with the last reset.
    qsizetype m_resetFixes = 0;
    QList<Chunk> m_chunks;
    // The chunk the reset's fixes went into, while it is the last one.
    bool m_lastIsReset = false;
    QPointF m_originMerc;
    int m_bandCount = 0;
    double m_bandKmh = 0.0;
};

#endif  // FRONTEND_V2_ROUTEBANDS_HH
