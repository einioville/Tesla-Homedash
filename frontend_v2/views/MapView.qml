import QtQuick
import frontend_v2

// Full-screen map view: the dashboard's TeslaMap blown up to fill the whole
// surface. Corners are left square (roundedCorners: false) — the map IS the
// view, so there's no surrounding card for rounded corners to blend into. The
// dock floats over it as a frosted overlay, exactly as on the dashboard.
//
// isCurrent is forwarded to the map so it freezes its follow animation + center
// binding while this view is hidden: the ViewController keeps this view (and its
// own TeslaMap instance, separate from the dashboard's) resident but frozen, so
// returning to it is instant with no per-frame work while away.
Rectangle {
    id: view

    property bool isCurrent: false
    color: Theme.dashboardBackground

    TeslaMap {
        anchors.fill: parent
        roundedCorners: false
        isCurrent: view.isCurrent
    }
}
