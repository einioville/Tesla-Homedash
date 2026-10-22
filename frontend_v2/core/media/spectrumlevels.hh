#ifndef FRONTEND_V2_SPECTRUMLEVELS_HH
#define FRONTEND_V2_SPECTRUMLEVELS_HH

#include <QAbstractListModel>
#include <QElapsedTimer>
#include <QList>
#include <QObject>
#include <QPointer>
#include <QString>

class MediaData;

/**
 * SpectrumLevels — the data half of items/media/MediaSpectrum.qml, so the spectrum
 * runs no JavaScript per frame (#83). While `live` it watches the `source`'s spectrum
 * (MediaData::retainSpectrum, released again when it stops) and turns each frame into
 * what is drawn: each band rises `rise` of the way to a new level at once and falls
 * back at most `fall` of the full height a second, and is then averaged with its
 * neighbours (1-2-1), so the line flows through the bands instead of zig-zagging.
 *
 *  - It is a list model with a row per band, low to high frequency, whose `level`
 *    (0-1) a bar stands on. A frame changes the rows' data, so each bar takes its own
 *    value and no list crosses into QML; measured at 120 frames a second, a quarter
 *    less GUI-thread time than bars indexing a list property. `count` changes only
 *    when the spectrum starts or stops.
 *  - With `tracePath` set, `path` is the line through the levels in a width × height
 *    item, as SVG path data for PathSvg: a Catmull-Rom curve as cubic Béziers, closed
 *    outside the item (right, under the bottom edge and back up the left) so a fill
 *    under it reaches the edges and the stroke draws the curve alone. Cubics, not a
 *    polyline sampled from them: the Shape took half as long again to process the
 *    polyline's ~470 points as the 39 cubics.
 */
class SpectrumLevels : public QAbstractListModel {
    Q_OBJECT
    // Media, whose frames this takes while live.
    Q_PROPERTY(QObject *source READ source WRITE setSource NOTIFY sourceChanged)
    Q_PROPERTY(bool live READ live WRITE setLive NOTIFY liveChanged)
    Q_PROPERTY(qreal rise READ rise WRITE setRise NOTIFY riseChanged)
    Q_PROPERTY(qreal fall READ fall WRITE setFall NOTIFY fallChanged)
    Q_PROPERTY(bool tracePath READ tracePath WRITE setTracePath NOTIFY tracePathChanged)
    Q_PROPERTY(qreal width READ width WRITE setWidth NOTIFY widthChanged)
    Q_PROPERTY(qreal height READ height WRITE setHeight NOTIFY heightChanged)
    Q_PROPERTY(int count READ count NOTIFY countChanged)
    Q_PROPERTY(QString path READ path NOTIFY pathChanged)

public:
    explicit SpectrumLevels(QObject *parent = nullptr);
    ~SpectrumLevels() override;

    QObject *source() const;
    void setSource(QObject *source);
    bool live() const { return m_live; }
    void setLive(bool live);
    qreal rise() const { return m_rise; }
    void setRise(qreal rise);
    qreal fall() const { return m_fall; }
    void setFall(qreal fall);
    bool tracePath() const { return m_tracePath; }
    void setTracePath(bool trace);
    qreal width() const { return m_width; }
    void setWidth(qreal width);
    qreal height() const { return m_height; }
    void setHeight(qreal height);
    int count() const { return static_cast<int>(m_drawn.size()); }
    QString path() const { return m_path; }

    enum Roles { LevelRole = Qt::UserRole + 1 };
    int rowCount(const QModelIndex &parent = QModelIndex()) const override;
    QVariant data(const QModelIndex &index, int role) const override;
    QHash<int, QByteArray> roleNames() const override;

signals:
    void sourceChanged();
    void liveChanged();
    void riseChanged();
    void fallChanged();
    void tracePathChanged();
    void widthChanged();
    void heightChanged();
    void countChanged();
    void pathChanged();

private:
    void syncWatch();
    void unwatch();
    void onFrame();
    void step(const QList<qreal> &raw);
    void rebuildPath();

    QPointer<MediaData> m_source;
    bool m_live = false;
    bool m_watching = false;
    qreal m_rise = 0.6;
    qreal m_fall = 1.2;
    bool m_tracePath = false;
    qreal m_width = 0.0;
    qreal m_height = 0.0;
    // The levels as they move, and as drawn (blurred).
    QList<qreal> m_shown;
    QList<qreal> m_drawn;
    QString m_path;
    QElapsedTimer m_lastFrame;
};

#endif  // FRONTEND_V2_SPECTRUMLEVELS_HH
