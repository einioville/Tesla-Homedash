import QtQuick
import frontend_v2

// The "Kuvakansio" row's description: how many photos the screensaver folder
// holds. Live — Photos watches the folder, so the number climbs during a USB
// import and after an scp. Styled exactly like a row's `help` line, which it
// stands in for.
Text {
    // The watcher covers photos copied in; this covers the folder itself having
    // been deleted and made again since the last look.
    Component.onCompleted: Photos.refresh()

    wrapMode: Text.WordWrap
    font.family: Theme.fontFamily
    font.pixelSize: 12
    color: Theme.dataLabelTitle
    text: Photos.count === 0 ? qsTr("Kuvia ei löytynyt")
        : Photos.count === 1 ? qsTr("1 kuva löydetty")
        : qsTr("%1 kuvaa löydetty").arg(Photos.count)
}
