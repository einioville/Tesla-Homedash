#ifndef FRONTEND_V2_LIGHTNINGLAYER_HH
#define FRONTEND_V2_LIGHTNINGLAYER_HH

#include <QList>
#include <QQuickItem>
#include <QRectF>
#include <QString>

/**
 * LightningLayer — the lightning over items/weather/RadarLayer.qml's loop, drawn on the GPU
 * (#83). It parses FMI's response itself (`load`), keeps the strikes in `area` (the view the
 * radar frames were fetched for), and draws each as a yellow cross outlined in black: the
 * shown frame's own strikes full size, the loop's earlier ones smaller and fading with age, as
 * the CPU Canvas it replaces drew them.
 *
 *  - The geometry — a quad per strike, in this item's pixels — is built when the strikes, the
 *    area or the loop change, and when `project` puts them in the camera of the moment, which
 *    RadarLayer does when the map rests (and every 1.5 s while it moves); in between the item is
 *    carried with the map like a frame. A loop step builds nothing: one quad set serves four
 *    passes (earlier outlines, earlier crosses, then the shown frame's), and the step only
 *    changes the frame the shaders (resources/shaders/lightning.*) compare each strike's slot
 *    with — all outlines of a pass go down before its crosses, so a cluster's crosses do not cut
 *    each other.
 *  - A strike falls in the slot of the frame whose 5 minutes end at or after it; the newest
 *    takes those since it as well, and one at or before the loop's start is in none.
 */
class LightningLayer : public QQuickItem {
    Q_OBJECT
    // The EPSG:3857 box whose strikes are drawn and counted; an empty one holds none.
    Q_PROPERTY(QRectF area READ area WRITE setArea NOTIFY areaChanged)
    // The loop: the first frame's time (epoch ms), the step between frames, how many there
    // are, and the one shown.
    Q_PROPERTY(double firstFrameMs READ firstFrameMs WRITE setFirstFrameMs NOTIFY loopChanged)
    Q_PROPERTY(int stepMs READ stepMs WRITE setStepMs NOTIFY loopChanged)
    Q_PROPERTY(int frameCount READ frameCount WRITE setFrameCount NOTIFY loopChanged)
    Q_PROPERTY(int frame READ frame WRITE setFrame NOTIFY frameChanged)
    // Strikes in the area, whenever they fell; and those the shown frame draws.
    Q_PROPERTY(int inArea READ inArea NOTIFY countsChanged)
    Q_PROPERTY(int shown READ shown NOTIFY countsChanged)

public:
    explicit LightningLayer(QQuickItem *parent = nullptr);

    QRectF area() const { return m_area; }
    void setArea(const QRectF &area);
    double firstFrameMs() const { return m_firstFrameMs; }
    void setFirstFrameMs(double ms);
    int stepMs() const { return m_stepMs; }
    void setStepMs(int ms);
    int frameCount() const { return m_frameCount; }
    void setFrameCount(int count);
    int frame() const { return m_frame; }
    void setFrame(int frame);
    int inArea() const { return m_inArea; }
    int shown() const { return m_shown; }

    // Takes the strikes from FMI's `fmi::observations::lightning::multipointcoverage` response,
    // replacing those held. Its gmlcov:positions holds one "lat lon epoch-seconds" triple per
    // strike; a response with no strikes has no positions element at all.
    Q_INVOKABLE void load(const QString &response);
    // Puts the strikes in the camera of the moment. EPSG:3857 to the screen is a similarity:
    // (ax, ay) is the point under the top-left corner, (bx, by) the one under the top edge's
    // far end, `width` pixels along.
    Q_INVOKABLE void project(double ax, double ay, double bx, double by, double width);

signals:
    void areaChanged();
    void loopChanged();
    void frameChanged();
    void countsChanged();

protected:
    QSGNode *updatePaintNode(QSGNode *oldNode, UpdatePaintNodeData *data) override;

private:
    struct Strike {
        double mx;  // EPSG:3857 metres
        double my;
        double t;   // epoch ms
    };
    // A strike in the area and the loop.
    struct Placed {
        double mx;
        double my;
        float steps;  // its time in loop steps from the first frame
        float slot;
    };

    void regroup();
    // The shown frame's count from the slots'; whether it changed.
    bool recount();

    QList<Strike> m_strikes;
    QList<Placed> m_placed;
    QList<int> m_slotCounts;
    QRectF m_area;
    double m_firstFrameMs = 0.0;
    int m_stepMs = 300000;
    int m_frameCount = 0;
    int m_frame = 0;
    int m_inArea = 0;
    int m_shown = 0;

    bool m_projected = false;
    double m_ax = 0.0;
    double m_ay = 0.0;
    double m_ux = 1.0;
    double m_uy = 0.0;
    double m_k = 1.0;  // pixels to the metre

    bool m_geometryDirty = false;
};

#endif  // FRONTEND_V2_LIGHTNINGLAYER_HH
