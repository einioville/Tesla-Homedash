#include "lightninglayer.hh"

#include <QColor>
#include <QMatrix4x4>
#include <QSGGeometry>
#include <QSGGeometryNode>
#include <QSGMaterial>
#include <QSGMaterialShader>
#include <QStringView>

#include <cmath>
#include <cstring>
#include <numbers>

namespace {
constexpr double kEarthRadius = 6378137.0;
// Half a strike quad's side: the shown frame's outline reaches 5 + (2.5 + 3) / 2 px from the
// strike, plus the shader's soft edge.
constexpr float kQuadHalf = 9.0f;

// The two sizes the Canvas drew: the shown frame's strikes, and the loop's earlier ones.
constexpr float kFreshRadius = 5.0f;
constexpr float kFreshWidth = 2.5f;
constexpr float kEarlierRadius = 3.5f;
constexpr float kEarlierWidth = 2.0f;
// How much wider the black outline is than the yellow cross on it.
constexpr float kOutline = 3.0f;

struct Vertex {
    float x;
    float y;
    float offsetX;
    float offsetY;
    float steps;
    float slot;
};

const QSGGeometry::AttributeSet &vertexAttributes() {
    static const QSGGeometry::Attribute attributes[] = {
        QSGGeometry::Attribute::createWithAttributeType(0, 2, QSGGeometry::FloatType,
                                                        QSGGeometry::PositionAttribute),
        QSGGeometry::Attribute::createWithAttributeType(1, 2, QSGGeometry::FloatType,
                                                        QSGGeometry::UnknownAttribute),
        QSGGeometry::Attribute::createWithAttributeType(2, 2, QSGGeometry::FloatType,
                                                        QSGGeometry::UnknownAttribute),
    };
    static const QSGGeometry::AttributeSet set = {3, sizeof(Vertex), attributes};
    return set;
}

class StrikeMaterial : public QSGMaterial {
public:
    StrikeMaterial(QColor color, float radius, float halfWidth, bool fresh)
        : m_radius(radius), m_halfWidth(halfWidth), m_fresh(fresh ? 1.0f : 0.0f) {
        m_color[0] = color.redF();
        m_color[1] = color.greenF();
        m_color[2] = color.blueF();
        m_color[3] = 1.0f;
        // Never merged with another node's geometry: the four passes share theirs.
        setFlag(Blending | RequiresFullMatrix);
    }

    QSGMaterialType *type() const override {
        static QSGMaterialType type;
        return &type;
    }
    QSGMaterialShader *createShader(QSGRendererInterface::RenderMode) const override;

    float m_color[4];
    float m_radius;
    float m_halfWidth;
    float m_fresh;
    float m_frame = 0.0f;
    float m_frameCount = 1.0f;
};

class StrikeShader : public QSGMaterialShader {
public:
    StrikeShader() {
        setShaderFileName(VertexStage, QStringLiteral(":/resources/shaders/lightning.vert.qsb"));
        setShaderFileName(FragmentStage, QStringLiteral(":/resources/shaders/lightning.frag.qsb"));
    }

    // The block in lightning.vert / .frag: qt_Matrix, color, then six floats.
    bool updateUniformData(RenderState &state, QSGMaterial *newMaterial, QSGMaterial *) override {
        QByteArray *buffer = state.uniformData();
        const auto *material = static_cast<const StrikeMaterial *>(newMaterial);
        const QMatrix4x4 matrix = state.combinedMatrix();
        std::memcpy(buffer->data(), matrix.constData(), 64);
        const float values[] = {material->m_color[0], material->m_color[1], material->m_color[2],
                                material->m_color[3], state.opacity(),     material->m_radius,
                                material->m_halfWidth, material->m_frame,  material->m_frameCount,
                                material->m_fresh};
        std::memcpy(buffer->data() + 64, values, sizeof values);
        return true;
    }
};

QSGMaterialShader *StrikeMaterial::createShader(QSGRendererInterface::RenderMode) const {
    return new StrikeShader;
}

// The layer's subtree: the four passes over one shared quad set, in drawing order.
class StrikeNode : public QSGNode {
public:
    StrikeNode() : geometry(vertexAttributes(), 0) {
        geometry.setDrawingMode(QSGGeometry::DrawTriangles);
        geometry.setVertexDataPattern(QSGGeometry::StaticPattern);
        const QColor black(Qt::black);
        const QColor yellow(0xff, 0xd2, 0x1f);
        StrikeMaterial *materials[] = {
            new StrikeMaterial(black, kEarlierRadius, (kEarlierWidth + kOutline) / 2, false),
            new StrikeMaterial(yellow, kEarlierRadius, kEarlierWidth / 2, false),
            new StrikeMaterial(black, kFreshRadius, (kFreshWidth + kOutline) / 2, true),
            new StrikeMaterial(yellow, kFreshRadius, kFreshWidth / 2, true),
        };
        for (int i = 0; i < 4; ++i) {
            passes[i] = new QSGGeometryNode;
            passes[i]->setGeometry(&geometry);
            passes[i]->setMaterial(materials[i]);
            passes[i]->setFlag(QSGNode::OwnsMaterial);
            appendChildNode(passes[i]);
        }
    }
    // The passes point at `geometry`, a member: they go before it does.
    ~StrikeNode() override {
        while (QSGNode *child = firstChild()) {
            removeChildNode(child);
            delete child;
        }
    }

    QSGGeometry geometry;
    QSGGeometryNode *passes[4];
};

double mercatorX(double longitude) {
    return kEarthRadius * longitude * std::numbers::pi / 180.0;
}

double mercatorY(double latitude) {
    return kEarthRadius * std::log(std::tan(std::numbers::pi / 4 + latitude * std::numbers::pi / 360.0));
}
}  // namespace

LightningLayer::LightningLayer(QQuickItem *parent) : QQuickItem(parent) {
    setFlag(ItemHasContents);
}

void LightningLayer::setArea(const QRectF &area) {
    if (m_area == area) {
        return;
    }
    m_area = area;
    emit areaChanged();
    regroup();
}

void LightningLayer::setFirstFrameMs(double ms) {
    if (m_firstFrameMs == ms) {
        return;
    }
    m_firstFrameMs = ms;
    emit loopChanged();
    regroup();
}

void LightningLayer::setStepMs(int ms) {
    if (m_stepMs == ms || ms <= 0) {
        return;
    }
    m_stepMs = ms;
    emit loopChanged();
    regroup();
}

void LightningLayer::setFrameCount(int count) {
    if (m_frameCount == count) {
        return;
    }
    m_frameCount = count;
    emit loopChanged();
    regroup();
}

void LightningLayer::setFrame(int frame) {
    if (m_frame == frame) {
        return;
    }
    m_frame = frame;
    emit frameChanged();
    if (recount()) {
        emit countsChanged();
    }
    update();
}

void LightningLayer::load(const QString &response) {
    m_strikes.clear();
    static const QString open = QStringLiteral("<gmlcov:positions>");
    const qsizetype start = response.indexOf(open);
    const qsizetype end = start < 0 ? -1 : response.indexOf(QStringLiteral("</gmlcov:positions>"), start);
    if (end > start) {
        const QStringView positions = QStringView(response).mid(start + open.size(), end - start - open.size());
        double triple[3];
        int have = 0;
        qsizetype i = 0;
        const qsizetype n = positions.size();
        while (i < n) {
            while (i < n && positions[i].isSpace()) {
                ++i;
            }
            const qsizetype from = i;
            while (i < n && !positions[i].isSpace()) {
                ++i;
            }
            if (i == from) {
                break;
            }
            bool ok = false;
            triple[have] = positions.mid(from, i - from).toDouble(&ok);
            if (!ok) {
                have = 0;
                continue;
            }
            if (++have == 3) {
                m_strikes.append({mercatorX(triple[1]), mercatorY(triple[0]), triple[2] * 1000.0});
                have = 0;
            }
        }
    }
    regroup();
}

void LightningLayer::project(double ax, double ay, double bx, double by, double width) {
    const double length = std::hypot(bx - ax, by - ay);
    if (length <= 0.0 || width <= 0.0) {
        return;
    }
    m_ax = ax;
    m_ay = ay;
    m_ux = (bx - ax) / length;
    m_uy = (by - ay) / length;
    m_k = width / length;
    m_projected = true;
    m_geometryDirty = true;
    update();
}

void LightningLayer::regroup() {
    m_placed.clear();
    m_slotCounts.fill(0, qMax(0, m_frameCount));
    int inArea = 0;
    const bool areaValid = m_area.isValid();
    const double loopStart = m_firstFrameMs - m_stepMs;
    for (const Strike &s : std::as_const(m_strikes)) {
        if (!areaValid || s.mx < m_area.left() || s.mx > m_area.right() || s.my < m_area.top()
            || s.my > m_area.bottom()) {
            continue;
        }
        ++inArea;
        if (m_frameCount <= 0 || s.t <= loopStart) {
            continue;
        }
        const double steps = (s.t - m_firstFrameMs) / m_stepMs;
        const int slot = qMin(m_frameCount - 1, qMax(0, static_cast<int>(std::ceil(steps))));
        ++m_slotCounts[slot];
        m_placed.append({s.mx, s.my, static_cast<float>(steps), static_cast<float>(slot)});
    }
    const bool changed = inArea != m_inArea;
    m_inArea = inArea;
    m_geometryDirty = true;
    if (recount() || changed) {
        emit countsChanged();
    }
    update();
}

bool LightningLayer::recount() {
    int shown = 0;
    for (int i = 0; i < m_slotCounts.size() && i <= m_frame; ++i) {
        shown += m_slotCounts.at(i);
    }
    const bool changed = shown != m_shown;
    m_shown = shown;
    return changed;
}

QSGNode *LightningLayer::updatePaintNode(QSGNode *oldNode, UpdatePaintNodeData *) {
    if (!m_projected || m_placed.isEmpty()) {
        delete oldNode;
        return nullptr;
    }
    auto *node = static_cast<StrikeNode *>(oldNode);
    if (!node) {
        node = new StrikeNode;
        m_geometryDirty = true;
    }
    if (m_geometryDirty) {
        m_geometryDirty = false;
        QSGGeometry &geometry = node->geometry;
        geometry.allocate(static_cast<int>(m_placed.size() * 6));
        auto *v = static_cast<Vertex *>(geometry.vertexData());
        static const float corners[6][2] = {{-1, -1}, {1, -1}, {1, 1}, {-1, -1}, {1, 1}, {-1, 1}};
        for (const Placed &p : std::as_const(m_placed)) {
            const double dx = p.mx - m_ax;
            const double dy = p.my - m_ay;
            const float x = static_cast<float>(m_k * (dx * m_ux + dy * m_uy));
            const float y = static_cast<float>(m_k * (dx * m_uy - dy * m_ux));
            for (const auto &c : corners) {
                const float ox = c[0] * kQuadHalf;
                const float oy = c[1] * kQuadHalf;
                *v++ = {x + ox, y + oy, ox, oy, p.steps, p.slot};
            }
        }
        geometry.markVertexDataDirty();
        for (QSGGeometryNode *pass : node->passes) {
            pass->markDirty(QSGNode::DirtyGeometry);
        }
    }
    for (QSGGeometryNode *pass : node->passes) {
        auto *material = static_cast<StrikeMaterial *>(pass->material());
        const float frame = static_cast<float>(m_frame);
        const float count = static_cast<float>(qMax(1, m_frameCount));
        if (material->m_frame != frame || material->m_frameCount != count) {
            material->m_frame = frame;
            material->m_frameCount = count;
            pass->markDirty(QSGNode::DirtyMaterial);
        }
    }
    return node;
}
