#include "routebands.hh"

#include <QtMath>

#include <algorithm>
#include <cmath>

namespace {
// The most segments a chunk of appended fixes holds: a new fix has its chunk's paths
// processed again, so this bounds that work however long the drive.
constexpr int kGrowSegments = 200;
// EPSG:3857's sphere, as GeoFrame.merc() has it.
constexpr double kEarthRadiusM = 6378137.0;

QPointF merc(double latitude, double longitude) {
    return {kEarthRadiusM * qDegreesToRadians(longitude),
            kEarthRadiusM * std::log(std::tan(M_PI / 4 + qDegreesToRadians(latitude) / 2))};
}

// Initial compass bearing from a to b, degrees clockwise from north: the car arrow's
// rotation (arrow.svg points north at 0).
double bearing(const RouteBands::Fix &a, const RouteBands::Fix &b) {
    const double lat1 = qDegreesToRadians(a.latitude);
    const double lat2 = qDegreesToRadians(b.latitude);
    const double dLon = qDegreesToRadians(b.longitude - a.longitude);
    const double y = std::sin(dLon) * std::cos(lat2);
    const double x = std::cos(lat1) * std::sin(lat2) - std::sin(lat1) * std::cos(lat2) * std::cos(dLon);
    return std::fmod(qRadiansToDegrees(std::atan2(y, x)) + 360.0, 360.0);
}
}  // namespace

RouteBands::RouteBands(QObject *parent) : QAbstractListModel(parent) {}

int RouteBands::rowCount(const QModelIndex &parent) const {
    return parent.isValid() ? 0 : static_cast<int>(m_chunks.size());
}

QVariant RouteBands::data(const QModelIndex &index, int role) const {
    if (!index.isValid() || index.row() >= m_chunks.size() || role != RevisionRole)
        return {};
    return m_chunks.at(index.row()).revision;
}

QHash<int, QByteArray> RouteBands::roleNames() const {
    return {{RevisionRole, "revision"}};
}

QGeoCoordinate RouteBands::origin() const {
    if (m_fixes.isEmpty())
        return {};
    return {m_fixes.first().latitude, m_fixes.first().longitude};
}

void RouteBands::setBandCount(int count) {
    if (count == m_bandCount)
        return;
    beginResetModel();
    m_bandCount = count;
    build();
    endResetModel();
    emit bandsChanged();
}

void RouteBands::setBandKmh(double kmh) {
    if (kmh == m_bandKmh)
        return;
    beginResetModel();
    m_bandKmh = kmh;
    build();
    endResetModel();
    emit bandsChanged();
}

void RouteBands::reset(const QList<Fix> &fixes) {
    const QGeoCoordinate before = origin();
    beginResetModel();
    m_fixes = fixes;
    m_resetFixes = fixes.size();
    setOrigin(fixes);
    build();
    endResetModel();
    if (origin() != before)
        emit originChanged();
}

void RouteBands::append(const Fix &fix) {
    m_fixes.append(fix);
    if (m_fixes.size() == 1) {
        setOrigin(m_fixes);
        emit originChanged();
        return;
    }
    if (!configured())
        return;
    const qsizetype i = m_fixes.size() - 1;
    if (opensChunk()) {
        const int row = static_cast<int>(m_chunks.size());
        beginInsertRows({}, row, row);
        Chunk chunk;
        chunk.bands.resize(m_bandCount);
        addSegment(chunk, i);
        m_chunks.append(chunk);
        m_lastIsReset = false;
        endInsertRows();
        return;
    }
    Chunk &chunk = m_chunks.last();
    addSegment(chunk, i);
    ++chunk.revision;
    const QModelIndex changed = index(static_cast<int>(m_chunks.size()) - 1);
    emit dataChanged(changed, changed, {RevisionRole});
}

QList<QPolygonF> RouteBands::runs(int chunk, int band) const {
    if (chunk < 0 || chunk >= m_chunks.size())
        return {};
    const QList<QList<QPolygonF>> &bands = m_chunks.at(chunk).bands;
    return band >= 0 && band < bands.size() ? bands.at(band) : QList<QPolygonF>();
}

QList<QPolygonF> RouteBands::casing(int chunk) const {
    return chunk >= 0 && chunk < m_chunks.size() ? m_chunks.at(chunk).casing : QList<QPolygonF>();
}

QVariantMap RouteBands::positionAt(double ts) const {
    const qsizetype n = m_fixes.size();
    if (n == 0)
        return {};
    // The first fix at or after ts, then whichever of it and the one before is nearer.
    const auto after = std::lower_bound(m_fixes.cbegin(), m_fixes.cend(), ts,
                                        [](const Fix &f, double t) { return f.ts < t; });
    qsizetype i = after - m_fixes.cbegin();
    if (i >= n)
        i = n - 1;
    else if (i > 0 && std::abs(m_fixes.at(i - 1).ts - ts) <= std::abs(m_fixes.at(i).ts - ts))
        --i;
    const Fix &fix = m_fixes.at(i);
    double heading = 0.0;
    if (i + 1 < n)
        heading = bearing(fix, m_fixes.at(i + 1));
    else if (i > 0)
        heading = bearing(m_fixes.at(i - 1), fix);
    return {{QStringLiteral("lat"), fix.latitude},
            {QStringLiteral("lon"), fix.longitude},
            {QStringLiteral("bearing"), heading}};
}

QPointF RouteBands::local(const Fix &fix) const {
    const QPointF m = merc(fix.latitude, fix.longitude);
    return {m.x() - m_originMerc.x(), m_originMerc.y() - m.y()};
}

int RouteBands::bandOf(double kmh) const {
    return std::clamp(static_cast<int>(std::floor(kmh / m_bandKmh)), 0, m_bandCount - 1);
}

void RouteBands::setOrigin(const QList<Fix> &fixes) {
    m_originMerc = fixes.isEmpty() ? QPointF()
                                   : merc(fixes.first().latitude, fixes.first().longitude);
}

void RouteBands::build() {
    m_chunks.clear();
    m_lastIsReset = false;
    if (!configured())
        return;
    if (m_resetFixes >= 2) {
        Chunk chunk;
        chunk.bands.resize(m_bandCount);
        for (qsizetype i = 1; i < m_resetFixes; ++i)
            addSegment(chunk, i);
        m_chunks.append(chunk);
        m_lastIsReset = true;
    }
    for (qsizetype i = std::max<qsizetype>(1, m_resetFixes); i < m_fixes.size(); ++i) {
        if (opensChunk()) {
            Chunk chunk;
            chunk.bands.resize(m_bandCount);
            m_chunks.append(chunk);
            m_lastIsReset = false;
        }
        addSegment(m_chunks.last(), i);
    }
}

bool RouteBands::opensChunk() const {
    return m_chunks.isEmpty() || m_lastIsReset || m_chunks.last().segments >= kGrowSegments;
}

void RouteBands::addSegment(Chunk &chunk, qsizetype i) const {
    const Fix &from = m_fixes.at(i - 1);
    const Fix &to = m_fixes.at(i);
    const QPointF a = local(from);
    const QPointF b = local(to);
    if (chunk.casing.isEmpty())
        chunk.casing.append(QPolygonF{a});
    chunk.casing.last().append(b);
    const int band = bandOf((from.speed + to.speed) / 2);
    QList<QPolygonF> &runs = chunk.bands[band];
    if (band != chunk.lastBand)
        runs.append(QPolygonF{a, b});
    else
        runs.last().append(b);
    chunk.lastBand = band;
    ++chunk.segments;
}
