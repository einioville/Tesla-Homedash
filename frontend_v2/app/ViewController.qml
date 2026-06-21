import QtQuick

// View host: lazy-loads each view on first selection, then keeps it ALIVE in
// memory so its state survives a switch away — e.g. the History view keeps its
// selected property + time window, ready exactly as you left it. The 4 GB Pi has
// memory to spare for a handful of resident views.
//
// While a view is not current it is FROZEN, not torn down: it is not painted
// (`visible: current`) and its per-frame work — the map's follow animation +
// center binding, the media colour fades, the seek ticker, the HVAC breath glow —
// is gated on the `isCurrent` property bound below, so a hidden view does no
// animated/rendered work and stops stealing GPU/CPU from the visible one. Cheap
// data bindings stay live (scalar updates that don't paint while hidden), so when
// a view becomes current again it is already showing current values. Only one view
// is visible at a time, so no z-ordering is needed.
Item {
    id: host

    property var model: []
    property int currentIndex: 0

    Repeater {
        model: host.model

        Loader {
            id: viewLoader
            required property int index
            required property var modelData

            readonly property bool current: index === host.currentIndex

            anchors.fill: parent
            sourceComponent: modelData.component

            // Load on first selection, then stay loaded (state kept in memory).
            active: current || keep
            property bool keep: false
            onActiveChanged: if (active) keep = true

            // Paint and accept input only while current; hidden views stay loaded
            // but frozen (see header). One view visible at a time → no z needed.
            visible: current
            enabled: current

            Binding {
                target: viewLoader.item
                property: "isCurrent"
                value: viewLoader.current
                when: viewLoader.status === Loader.Ready
            }
        }
    }
}
