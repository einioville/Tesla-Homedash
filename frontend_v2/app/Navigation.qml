pragma Singleton
import QtQuick

// Asks for another view from inside one: the dashboard's weather card opens the Weather view.
// Main.qml makes the switch, so a view names the one it wants by its key in Main.viewModel and
// need not know where that stands on the cylinder.
QtObject {
    signal openRequested(string key)

    function open(key) {
        openRequested(key)
    }
}
