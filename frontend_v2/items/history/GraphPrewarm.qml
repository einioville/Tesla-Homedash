import QtQuick
import QtGraphs

// One-time Qt Graphs renderer warm-up.
//
// The first time a GraphsView / LineSeries is drawn, the RHI compiles its render
// pipeline (and the QtGraphs module/types initialise) on the render thread — a
// one-time stall that otherwise lands on the first navigation to the History view
// ("slow the first time, smooth after"). Rendering a throwaway graph WITH a real
// line once at startup moves that cost into boot; the compiled pipelines stay
// cached for the whole process, so this item asks to be removed afterwards.
//
// It must actually render to compile anything, so it is a normal-sized graph
// placed behind the opaque dashboard (visible:false / opacity:0 would be skipped
// and defeat the purpose). It is never seen.
Item {
    id: root

    signal done()

    GraphsView {
        anchors.fill: parent

        axisX: ValueAxis { min: 0; max: 1; gridVisible: false; subGridVisible: false; labelsVisible: false }
        axisY: ValueAxis { min: 0; max: 1; gridVisible: false; subGridVisible: false; labelsVisible: false }

        // A few points so the line geometry pipeline compiles too, not just the
        // axes. Default (straight) line style — the same one the real graph uses
        // (it builds steps from explicit points, so its series is also straight).
        LineSeries {
            width: 2
            XYPoint { x: 0.0; y: 0.0 }
            XYPoint { x: 0.5; y: 1.0 }
            XYPoint { x: 1.0; y: 0.4 }
        }
    }

    // Give the render thread several frames to compile, then request removal.
    Timer {
        interval: 2000
        running: true
        repeat: false
        onTriggered: root.done()
    }
}
