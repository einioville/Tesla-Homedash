#include "graphseries.hh"

#include <algorithm>
#include <array>
#include <cmath>
#include <limits>

namespace {

// A bound on traced pixels, far off-screen. A point far outside the visible y-range
// maps to an enormous pixel, and the curve renderer triangulates the WHOLE path (the
// layers' clip is only a rasteriser scissor, not a geometry clip), which asserts and
// aborts the app once a vertex exceeds 2^21 px (qtriangulator.cpp). Clamped to this,
// only the scissored-away tail changes. Also the glow's floor: far below the plot, so
// a y re-fit stretching the glow before the next build cannot lift it into view.
constexpr double kPathLimit = 1 << 18;

constexpr double kInfinity = std::numeric_limits<double>::infinity();

double clampPx(double v) {
    return v < -kPathLimit ? -kPathLimit : (v > kPathLimit ? kPathLimit : v);
}

// Math.min / Math.max: a NaN in gives a NaN out, as in the JavaScript this replaced.
double nanMin(double a, double b) {
    return std::isnan(a) || std::isnan(b) ? qQNaN() : std::min(a, b);
}
double nanMax(double a, double b) {
    return std::isnan(a) || std::isnan(b) ? qQNaN() : std::max(a, b);
}

bool xBefore(const QPointF &p, double x) { return p.x() < x; }
bool xAfter(double x, const QPointF &p) { return x < p.x(); }

// Index of the last point at or before x, of an ascending series whose first point is.
qsizetype lastAtOrBefore(const QList<QPointF> &pts, double x) {
    return std::upper_bound(pts.cbegin(), pts.cend(), x, xAfter) - pts.cbegin() - 1;
}

// The straight segment between the two readings bracketing x, held at the ends
// outside the series.
double interpAt(const QList<QPointF> &pts, double x) {
    const qsizetype n = pts.size();
    if (n == 0) {
        return qQNaN();
    }
    if (x <= pts.first().x()) {
        return pts.first().y();
    }
    if (x >= pts.last().x()) {
        return pts.last().y();
    }
    const qsizetype lo = lastAtOrBefore(pts, x);
    const QPointF &a = pts.at(lo);
    const QPointF &b = pts.at(lo + 1);
    const double span = b.x() - a.x();
    if (span <= 0) {
        return a.y();
    }
    return a.y() + (b.y() - a.y()) * (x - a.x()) / span;
}

QPolygonF tracePoints(const QList<QPointF> &pts, double x0, double xSpan, double yTop,
                      double ySpan, double w, double h) {
    QPolygonF out;
    out.reserve(pts.size());
    for (const QPointF &p : pts) {
        out.append(QPointF(clampPx((p.x() - x0) / xSpan * w), clampPx((yTop - p.y()) / ySpan * h)));
    }
    return out;
}

QList<QPointF> toPoints(const QVariant &value) {
    if (value.metaType() == QMetaType::fromType<QList<QPointF>>()) {
        return value.value<QList<QPointF>>();
    }
    const QVariantList items = value.toList();
    QList<QPointF> points;
    points.reserve(items.size());
    for (const QVariant &item : items) {
        points.append(item.toPointF());
    }
    return points;
}

}  // namespace

GraphSeries::GraphSeries(QObject *parent) : QObject(parent) {}

void GraphSeries::setPoints(const QList<QPointF> &points) {
    m_points = points;
    emit pointsChanged();
}

void GraphSeries::setLineMode(const QString &mode) {
    if (m_lineMode == mode) {
        return;
    }
    m_lineMode = mode;
    emit lineModeChanged();
    bump();
}

void GraphSeries::setExtraPoints(const QVariantList &lines) {
    m_extraPoints = lines;
    m_extras.clear();
    m_extras.reserve(lines.size());
    for (const QVariant &line : lines) {
        m_extras.append(toPoints(line));
    }
    emit extraPointsChanged();
    bump();
}

void GraphSeries::snapshot() {
    m_raw = m_points;
    bump();
}

void GraphSeries::bump() {
    ++m_revision;
    emit revisionChanged();
}

void GraphSeries::rebuild(double buildMinX, double buildMaxX, double viewSpan,
                          double plotWidth, double bucketsPerPx) {
    m_decimated = decimate(buildMinX, buildMaxX, viewSpan, plotWidth, bucketsPerPx);
    m_stepped = stepped(m_decimated, buildMinX, buildMaxX);
    bump();
}

// M4: the window is divided into bucketsPerPx buckets per visible plot pixel, and each
// bucket keeps its first, last, min-y and max-y points (deduped, x-ascending). This
// reproduces the rasterized line at pixel resolution — spikes survive (a spike is its
// bucket's min/max), a held value collapses to one flat point, and the first/last points
// keep linear slopes faithful. The two bracket points just outside the window (the held
// left edge = last point <= windowStart, and the first point >= windowEnd) are always
// kept so the line enters and exits correctly and the edge interpolation is exact.
// O(visible raw count).
QList<QPointF> GraphSeries::decimate(double windowStart, double windowEnd, double viewSpan,
                                     double plotWidth, double bucketsPerPx) const {
    const QList<QPointF> &S = m_raw;
    const qsizetype N = S.size();
    if (N == 0) {
        return {};
    }
    const qsizetype L = S.first().x() <= windowStart ? lastAtOrBefore(S, windowStart) : -1;
    const qsizetype R = std::lower_bound(S.cbegin(), S.cend(), windowEnd, xBefore) - S.cbegin();

    // A visible set already under the bucket count renders exactly (no decimation), so
    // the small Trips / Charging graphs draw every point; nor is any at the "max"
    // resolution level (bucketsPerPx 0). The density is per VISIBLE pixel, so the count
    // scales with how far this (build) window reaches past the view: otherwise a wider
    // render margin would quietly thin out what is on screen, and a smaller graph would
    // get the same count as a full-width one.
    const double plotW = std::max(1.0, plotWidth);
    const qsizetype startIdx = L < 0 ? 0 : L;
    const double cap = bucketsPerPx > 0 && viewSpan > 0
        ? std::ceil(bucketsPerPx * plotW * (windowEnd - windowStart) / viewSpan)
        : 0;
    const auto rawSlice = [&] {
        return S.mid(startIdx, std::max<qsizetype>(0, std::min(R + 1, N) - startIdx));
    };
    if (cap <= 0 || R - startIdx <= cap) {
        return rawSlice();
    }
    const double bucketDx = (windowEnd - windowStart) / cap;
    // A zero or negative span would never advance the bucket loop. clampWidth floors the
    // span, so this cannot normally happen.
    if (bucketDx <= 0) {
        return rawSlice();
    }

    QList<QPointF> out;
    out.reserve(static_cast<qsizetype>(4 * cap) + 2);
    if (L >= 0) {
        out.append(S.at(L));
    }
    double bucketEnd = windowStart + bucketDx;
    bool have = false;
    qsizetype first = 0, mn = 0, mx = 0, last = 0;
    // First, last, min and max in x order, each dropped when equal (x AND y) to the point
    // emitted before it: no duplicate or zero-area segments in the glow's fill.
    const auto flush = [&] {
        std::array<qsizetype, 4> cand{first, mn, mx, last};
        std::stable_sort(cand.begin(), cand.end(),
                         [&](qsizetype a, qsizetype b) { return S.at(a).x() < S.at(b).x(); });
        for (const qsizetype k : cand) {
            const QPointF &c = S.at(k);
            if (!out.isEmpty() && out.last().x() == c.x() && out.last().y() == c.y()) {
                continue;
            }
            out.append(c);
        }
    };
    for (qsizetype i = L < 0 ? 0 : L + 1; i < N && S.at(i).x() < windowEnd; ++i) {
        const QPointF &p = S.at(i);
        while (p.x() > bucketEnd) {
            if (have) {
                flush();
                have = false;
            }
            bucketEnd += bucketDx;
        }
        if (!have) {
            first = mn = mx = last = i;
            have = true;
        } else {
            if (p.y() < S.at(mn).y()) {
                mn = i;
            }
            if (p.y() > S.at(mx).y()) {
                mx = i;
            }
            last = i;
        }
    }
    if (have) {
        flush();
    }
    if (R < N) {
        out.append(S.at(R));
    }
    return out;
}

// The readings as an explicit path in data coordinates, clamped to the built window
// [lo, hi] — drawn as straight segments, so the geometry built here IS what shows.
QList<QPointF> GraphSeries::stepped(const QList<QPointF> &pts, double lo, double hi) const {
    const qsizetype n = pts.size();
    if (n == 0) {
        return {};
    }
    QList<QPointF> out;
    if (m_lineMode == QStringLiteral("linear")) {
        // An interpolated point at each edge (held at the ends when the edge lies outside
        // the data, as valueAt() does), every reading strictly inside between them.
        out.reserve(n + 2);
        out.append(QPointF(lo, interpAt(pts, lo)));
        for (const QPointF &p : pts) {
            if (p.x() > lo && p.x() < hi) {
                out.append(p);
            }
        }
        out.append(QPointF(hi, interpAt(pts, hi)));
        return out;
    }
    // "step": the held value out to the next reading, then a vertical jump to the new
    // one. It starts at the value held at the left edge (the last reading at or before
    // lo), so the line starts flat at the edge when the first reading predates the
    // window, and the last value is held to the right edge ("held until now" in live
    // mode) — a single reading draws as a flat line across the window.
    out.reserve(2 * n + 2);
    double heldY = pts.first().y();
    qsizetype i = 0;
    while (i < n && pts.at(i).x() <= lo) {
        heldY = pts.at(i).y();
        ++i;
    }
    out.append(QPointF(lo, heldY));
    for (; i < n && pts.at(i).x() <= hi; ++i) {
        out.append(QPointF(pts.at(i).x(), heldY));
        out.append(pts.at(i));
        heldY = pts.at(i).y();
    }
    out.append(QPointF(hi, heldY));
    return out;
}

bool GraphSeries::trace(double x0, double xSpan, double yTop, double ySpan, double w,
                        double h, bool glow) {
    if (m_stepped.isEmpty() || w <= 0 || h <= 0 || xSpan <= 0 || ySpan <= 0) {
        m_linePath.clear();
        m_extraPaths.clear();
        emit linePathChanged();
        emit extraPathsChanged();
        if (glow) {
            m_glowPath.clear();
            emit glowPathChanged();
        }
        return false;
    }
    m_linePath = tracePoints(m_stepped, x0, xSpan, yTop, ySpan, w, h);
    m_extraPaths.clear();
    for (const QList<QPointF> &extra : std::as_const(m_extras)) {
        m_extraPaths.append(QVariant::fromValue(tracePoints(extra, x0, xSpan, yTop, ySpan, w, h)));
    }
    emit linePathChanged();
    emit extraPathsChanged();
    if (glow) {
        m_glowPath.clear();
        m_glowPath.reserve(m_linePath.size() + 2);
        m_glowPath.append(QPointF(m_linePath.first().x(), kPathLimit));
        m_glowPath.append(m_linePath);
        m_glowPath.append(QPointF(m_linePath.last().x(), kPathLimit));
        emit glowPathChanged();
    }
    return true;
}

double GraphSeries::valueAt(double x) const {
    const qsizetype n = m_raw.size();
    if (n == 0) {
        return qQNaN();
    }
    if (m_lineMode == QStringLiteral("linear")) {
        return interpAt(m_raw, x);
    }
    if (x <= m_raw.first().x()) {
        return m_raw.first().y();
    }
    if (x >= m_raw.last().x()) {
        return m_raw.last().y();
    }
    return m_raw.at(lastAtOrBefore(m_raw, x)).y();
}

double GraphSeries::extraValueAt(int line, double x) const {
    if (line < 0 || line >= m_extras.size()) {
        return qQNaN();
    }
    return interpAt(m_extras.at(line), x);
}

// Scans the DECIMATED set's visible slice: M4 keeps each bucket's true min-y and max-y,
// so its envelope equals the raw visible envelope (the fit cannot clip), and the scan
// stays small enough for every frame of a gesture. The edge values come from the raw
// series, so the exact held / interpolated value at each view edge is in.
QPointF GraphSeries::fitY(double tMin, double tMax, double fallbackMin,
                          double fallbackMax) const {
    const QList<QPointF> &pts = m_decimated;
    if (pts.isEmpty()) {
        return {0.0, 1.0};
    }
    double mn = kInfinity;
    double mx = -kInfinity;
    const auto fold = [&](double v) {
        mn = nanMin(mn, v);
        mx = nanMax(mx, v);
    };
    const auto foldEdge = [&](double v) {
        if (!std::isnan(v)) {
            fold(v);
        }
    };
    foldEdge(valueAt(tMin));
    for (auto it = std::lower_bound(pts.cbegin(), pts.cend(), tMin, xBefore);
         it != pts.cend() && it->x() <= tMax; ++it) {
        fold(it->y());
    }
    foldEdge(valueAt(tMax));
    for (const QList<QPointF> &extra : m_extras) {
        foldEdge(interpAt(extra, tMin));
        foldEdge(interpAt(extra, tMax));
        for (const QPointF &p : extra) {
            if (p.x() >= tMin && p.x() <= tMax) {
                fold(p.y());
            }
        }
    }
    if (mn == kInfinity) {
        return {fallbackMin, fallbackMax};
    }
    return {mn, mx};
}
