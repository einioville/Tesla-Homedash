#ifndef FRONTEND_V2_SERIESBOUNDS_HH
#define FRONTEND_V2_SERIESBOUNDS_HH

#include <QList>
#include <QPointF>
#include <QVariantList>

#include <limits>

/** The axis bounds a static history graph is drawn over. */
struct SeriesBounds {
    double minX = 0.0;
    double maxX = 1.0;
    double minY = 0.0;
    double maxY = 1.0;
};

/**
 * The extent of `points`, or 0..1 on both axes when there are none, so an empty
 * graph still renders. A single timestamp is padded to +/- 1 min: a QML ValueAxis
 * with min == max divides by zero mapping data to pixels and crashes QtGraphs.
 * (A flat y-range is harmless — HistoryGraph pads it via yPad when auto-fitting.)
 */
inline SeriesBounds seriesBounds(const QList<QPointF> &points) {
    if (points.isEmpty()) {
        return {};
    }
    SeriesBounds b{std::numeric_limits<double>::max(), std::numeric_limits<double>::lowest(),
                   std::numeric_limits<double>::max(), std::numeric_limits<double>::lowest()};
    for (const QPointF &p : points) {
        b.minX = qMin(b.minX, p.x());
        b.maxX = qMax(b.maxX, p.x());
        b.minY = qMin(b.minY, p.y());
        b.maxY = qMax(b.maxY, p.y());
    }
    if (b.maxX <= b.minX) {
        b.minX -= 60000.0;
        b.maxX += 60000.0;
    }
    return b;
}

/**
 * Rolls a live graph's window to [nowMs - windowMs, nowMs]. `points` (QPointF
 * variants, oldest first) loses everything before the left edge except the last
 * such point, which the step line needs for the value held at the edge. The
 * y-bounds span the points kept, 0..1 when there are none; HistoryGraph uses them
 * only when the visible window holds no points.
 */
inline SeriesBounds rollLiveWindow(QVariantList &points, qint64 windowMs, qint64 nowMs) {
    const double left = static_cast<double>(nowMs - windowMs);
    qsizetype firstInside = 0;
    while (firstInside < points.size() && points[firstInside].toPointF().x() < left) {
        ++firstInside;
    }
    if (firstInside > 1) {
        points.remove(0, firstInside - 1);
    }
    SeriesBounds b{left, static_cast<double>(nowMs), 0.0, 1.0};
    if (!points.isEmpty()) {
        b.minY = std::numeric_limits<double>::max();
        b.maxY = std::numeric_limits<double>::lowest();
        for (const QVariant &p : points) {
            b.minY = qMin(b.minY, p.toPointF().y());
            b.maxY = qMax(b.maxY, p.toPointF().y());
        }
    }
    return b;
}

#endif  // FRONTEND_V2_SERIESBOUNDS_HH
