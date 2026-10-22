#ifndef FRONTEND_V2_GRAPHSERIES_HH
#define FRONTEND_V2_GRAPHSERIES_HH

#include <QList>
#include <QObject>
#include <QPointF>
#include <QPolygonF>
#include <QString>
#include <QVariantList>

/**
 * GraphSeries — the data half of items/history/HistoryGraph.qml, so that no graph
 * runs per-point JavaScript (#83). It holds the series as QList<QPointF>, never
 * converted to JS, and does the work from data to Shape paths: M4 decimation for the
 * window being built, the step or linear path through it, the trace into plot
 * pixels, the y envelope and the value lookups the inspect readout needs. The paths
 * reach the Shapes as QPolygonF, which PathPolyline takes as it is. HistoryGraph
 * keeps the gestures, the axes, the transforms and the draw-in.
 *
 *  - `points` is bound to the data source; `snapshot()` takes what the graph draws
 *    and answers for, on a load or a live tick (an implicitly shared copy).
 *  - `extraPoints` holds the further lines over the same axes (a list of point
 *    lists), drawn point to point with no decimation; trace() traces them with the
 *    main line, `extraPaths` holding one QPolygonF each.
 *  - `revision` changes whenever what valueAt() / extraValueAt() / fitY() answer
 *    from does: an invokable registers no binding dependency, so a binding that
 *    calls one reads `revision` too.
 */
class GraphSeries : public QObject {
    Q_OBJECT
    Q_PROPERTY(QList<QPointF> points READ points WRITE setPoints NOTIFY pointsChanged)
    Q_PROPERTY(QString lineMode READ lineMode WRITE setLineMode NOTIFY lineModeChanged)
    Q_PROPERTY(QVariantList extraPoints READ extraPoints WRITE setExtraPoints NOTIFY extraPointsChanged)
    Q_PROPERTY(QPolygonF linePath READ linePath NOTIFY linePathChanged)
    Q_PROPERTY(QPolygonF glowPath READ glowPath NOTIFY glowPathChanged)
    Q_PROPERTY(QVariantList extraPaths READ extraPaths NOTIFY extraPathsChanged)
    Q_PROPERTY(int revision READ revision NOTIFY revisionChanged)

public:
    explicit GraphSeries(QObject *parent = nullptr);

    QList<QPointF> points() const { return m_points; }
    void setPoints(const QList<QPointF> &points);
    QString lineMode() const { return m_lineMode; }
    void setLineMode(const QString &mode);
    QVariantList extraPoints() const { return m_extraPoints; }
    void setExtraPoints(const QVariantList &lines);
    QPolygonF linePath() const { return m_linePath; }
    QPolygonF glowPath() const { return m_glowPath; }
    QVariantList extraPaths() const { return m_extraPaths; }
    int revision() const { return m_revision; }

    // Takes `points` as the series drawn and answered for.
    Q_INVOKABLE void snapshot();
    // Decimates the snapshot to [buildMinX, buildMaxX] and builds the path through
    // it per lineMode, clamped to that window. The density is bucketsPerPx buckets
    // per pixel of the VISIBLE plot (viewSpan wide, plotWidth px); <= 0 keeps every
    // point.
    Q_INVOKABLE void rebuild(double buildMinX, double buildMaxX, double viewSpan,
                             double plotWidth, double bucketsPerPx);
    // Traces the built path, and the extra lines, into plot pixels for these axes
    // (x0 and yTop at the plot's top-left, w × h px): the line, and with `glow` the
    // glow — the line closed down to two floor points far below the plot. False,
    // with the paths cleared, when there is nothing to trace.
    Q_INVOKABLE bool trace(double x0, double xSpan, double yTop, double ySpan,
                           double w, double h, bool glow);
    // The snapshot's value at x: held from the last reading ("step") or
    // interpolated ("linear"); NaN when empty.
    Q_INVOKABLE double valueAt(double x) const;
    // Extra line `line` interpolated at x; NaN when it has no points.
    Q_INVOKABLE double extraValueAt(int line, double x) const;
    // The y envelope over [tMin, tMax] as (min, max), held edge values and extra
    // lines included; (0, 1) while nothing is built, (fallbackMin, fallbackMax)
    // when the window holds no value.
    Q_INVOKABLE QPointF fitY(double tMin, double tMax, double fallbackMin,
                             double fallbackMax) const;

signals:
    void pointsChanged();
    void lineModeChanged();
    void extraPointsChanged();
    void linePathChanged();
    void glowPathChanged();
    void extraPathsChanged();
    void revisionChanged();

private:
    QList<QPointF> decimate(double windowStart, double windowEnd, double viewSpan,
                            double plotWidth, double bucketsPerPx) const;
    QList<QPointF> stepped(const QList<QPointF> &points, double lo, double hi) const;
    void bump();

    QList<QPointF> m_points;
    QString m_lineMode = QStringLiteral("step");
    QVariantList m_extraPoints;

    QList<QPointF> m_raw;
    QList<QList<QPointF>> m_extras;
    QList<QPointF> m_decimated;
    QList<QPointF> m_stepped;

    QPolygonF m_linePath;
    QPolygonF m_glowPath;
    QVariantList m_extraPaths;
    int m_revision = 0;
};

#endif  // FRONTEND_V2_GRAPHSERIES_HH
