#include "spectrumlevels.hh"

#include <algorithm>

#include "mediadata.hh"

namespace {
// How far outside the item the line's closing edge runs.
constexpr qreal kCloseOutside = 24.0;
// At rest the line lies just above the bottom edge.
constexpr qreal kRestGap = 3.0;
}  // namespace

SpectrumLevels::SpectrumLevels(QObject *parent) : QAbstractListModel(parent) {}

SpectrumLevels::~SpectrumLevels() {
    if (m_watching && m_source) {
        m_source->releaseSpectrum();
    }
}

int SpectrumLevels::rowCount(const QModelIndex &parent) const {
    return parent.isValid() ? 0 : static_cast<int>(m_drawn.size());
}

QVariant SpectrumLevels::data(const QModelIndex &index, int role) const {
    if (role != LevelRole || !index.isValid() || index.row() >= m_drawn.size()) {
        return {};
    }
    return m_drawn.at(index.row());
}

QHash<int, QByteArray> SpectrumLevels::roleNames() const {
    return {{LevelRole, "level"}};
}

QObject *SpectrumLevels::source() const {
    return m_source.data();
}

void SpectrumLevels::setSource(QObject *source) {
    auto *media = qobject_cast<MediaData *>(source);
    if (m_source == media) {
        return;
    }
    unwatch();
    m_source = media;
    emit sourceChanged();
    syncWatch();
}

void SpectrumLevels::setLive(bool live) {
    if (m_live == live) {
        return;
    }
    m_live = live;
    emit liveChanged();
    syncWatch();
}

void SpectrumLevels::setRise(qreal rise) {
    if (m_rise == rise) {
        return;
    }
    m_rise = rise;
    emit riseChanged();
}

void SpectrumLevels::setFall(qreal fall) {
    if (m_fall == fall) {
        return;
    }
    m_fall = fall;
    emit fallChanged();
}

void SpectrumLevels::setTracePath(bool trace) {
    if (m_tracePath == trace) {
        return;
    }
    m_tracePath = trace;
    emit tracePathChanged();
    rebuildPath();
}

void SpectrumLevels::setWidth(qreal width) {
    if (m_width == width) {
        return;
    }
    m_width = width;
    emit widthChanged();
    rebuildPath();
}

void SpectrumLevels::setHeight(qreal height) {
    if (m_height == height) {
        return;
    }
    m_height = height;
    emit heightChanged();
    rebuildPath();
}

// Watches the source's spectrum while live, and only then: the backend records only
// while some display watches, and the frames another instance asked for are not this
// one's. Letting go starts the levels over from nothing.
void SpectrumLevels::syncWatch() {
    if (!m_live || !m_source) {
        unwatch();
        return;
    }
    if (m_watching) {
        return;
    }
    m_watching = true;
    connect(m_source, &MediaData::spectrumChanged, this, &SpectrumLevels::onFrame);
    m_source->retainSpectrum();
}

void SpectrumLevels::unwatch() {
    if (!m_watching) {
        return;
    }
    m_watching = false;
    if (m_source) {
        disconnect(m_source, &MediaData::spectrumChanged, this, &SpectrumLevels::onFrame);
        m_source->releaseSpectrum();
    }
    step({});
}

void SpectrumLevels::onFrame() {
    if (m_source) {
        step(m_source->spectrum());
    }
}

void SpectrumLevels::step(const QList<qreal> &raw) {
    // A late frame (a busy GUI thread) falls by no more than a tenth of a second's worth.
    const qreal elapsed = m_lastFrame.isValid() ? m_lastFrame.restart() / 1000.0 : 0.1;
    if (!m_lastFrame.isValid()) {
        m_lastFrame.start();
    }
    const qreal fall = m_fall * std::min<qreal>(0.1, elapsed);
    const qsizetype n = raw.size();
    QList<qreal> shown(n);
    for (qsizetype i = 0; i < n; ++i) {
        const qreal was = i < m_shown.size() ? m_shown.at(i) : 0.0;
        const qreal level = raw.at(i);
        shown[i] = level > was ? was + (level - was) * m_rise : std::max(level, was - fall);
    }
    m_shown = shown;

    QList<qreal> drawn(n);
    for (qsizetype i = 0; i < n; ++i) {
        qreal sum = 2.0 * shown.at(i);
        qreal weight = 2.0;
        if (i > 0) {
            sum += shown.at(i - 1);
            weight += 1.0;
        }
        if (i + 1 < n) {
            sum += shown.at(i + 1);
            weight += 1.0;
        }
        drawn[i] = sum / weight;
    }
    if (drawn.size() != m_drawn.size()) {
        beginResetModel();
        m_drawn = drawn;
        endResetModel();
        emit countChanged();
    } else {
        m_drawn = drawn;
        if (n > 0) {
            emit dataChanged(index(0), index(static_cast<int>(n) - 1), {LevelRole});
        }
    }
    rebuildPath();
}

void SpectrumLevels::rebuildPath() {
    const qsizetype n = m_drawn.size();
    if (!m_tracePath || n < 2 || m_width <= 0.0 || m_height <= 0.0) {
        if (!m_path.isEmpty()) {
            m_path.clear();
            emit pathChanged();
        }
        return;
    }
    const qreal w = m_width;
    const qreal h = m_height;
    const qreal rest = h - kRestGap;
    const auto x = [&](qsizetype i) { return static_cast<qreal>(i) / static_cast<qreal>(n - 1) * w; };
    const auto y = [&](qsizetype i) { return rest - m_drawn.at(std::clamp<qsizetype>(i, 0, n - 1)) * rest; };

    // Catmull-Rom through the levels, as cubic Béziers.
    const auto num = [](qreal v) { return QString::number(v, 'f', 1); };
    QString path;
    path.reserve(static_cast<qsizetype>(n) * 48 + 96);
    path += QStringLiteral("M ") + num(x(0)) + u' ' + num(y(0));
    for (qsizetype i = 0; i < n - 1; ++i) {
        path += QStringLiteral(" C ") + num(x(i) + (x(i + 1) - x(std::max<qsizetype>(0, i - 1))) / 6.0)
                + u' ' + num(y(i) + (y(i + 1) - y(i - 1)) / 6.0)
                + u' ' + num(x(i + 1) - (x(std::min<qsizetype>(n - 1, i + 2)) - x(i)) / 6.0)
                + u' ' + num(y(i + 1) - (y(i + 2) - y(i)) / 6.0)
                + u' ' + num(x(i + 1)) + u' ' + num(y(i + 1));
    }
    path += QStringLiteral(" L ") + num(w + kCloseOutside) + u' ' + num(y(n - 1))
            + QStringLiteral(" L ") + num(w + kCloseOutside) + u' ' + num(h + kCloseOutside)
            + QStringLiteral(" L ") + num(-kCloseOutside) + u' ' + num(h + kCloseOutside)
            + QStringLiteral(" L ") + num(-kCloseOutside) + u' ' + num(y(0)) + QStringLiteral(" Z");
    m_path = path;
    emit pathChanged();
}
