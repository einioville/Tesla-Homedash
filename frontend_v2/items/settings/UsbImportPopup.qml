import QtQuick
import frontend_v2

// Screensaver photo import from a USB stick, as a modal over the OPTIONS VIEW —
// opened by the "Tuo USB:ltä" button on the Kuvakansio row a few pixels above it,
// so, like SpotifyDevicePopup, it darkens only this screen.
//
// Three steps, all done by the backend (UsbImport): pick a drive from the list,
// see how many photos its tesla_homedash_screensaver folder holds, copy them.
// Nothing is decided here beyond which button was pressed.
//
// Top-anchored and short on purpose: a popup inside a view cannot cover the dock
// (y 684–780 on the target), so a card reaching that band would hide its own
// buttons. The drive list scrolls past four entries rather than growing.
Item {
    id: popup

    anchors.fill: parent
    visible: UsbImport.phase !== "idle"
    z: 100

    readonly property string phase: UsbImport.phase
    readonly property bool working: phase === "listing" || phase === "scanning"
    readonly property bool canImport: phase === "ready" && UsbImport.count > 0

    function photos(n) {
        return n === 1 ? qsTr("1 kuva") : qsTr("%1 kuvaa").arg(n)
    }

    function sizeText(bytes) {
        const gb = bytes / 1e9
        const value = gb >= 1 ? gb : bytes / 1e6
        const unit = gb >= 1 ? qsTr("Gt") : qsTr("Mt")
        return value.toFixed(value >= 10 ? 0 : 1).replace(".", ",") + " " + unit
    }

    function driveName(drive) {
        if (!drive || drive.device === undefined)
            return ""
        return drive.label.length > 0 ? drive.label
             : drive.model.length > 0 ? drive.model : drive.device
    }

    // Swallows every tap that misses the card, so the settings underneath cannot
    // be operated mid-import.
    MouseArea {
        anchors.fill: parent
        preventStealing: true
        onClicked: {}
    }

    Rectangle {
        anchors.fill: parent
        color: Theme.dialogScrim
    }

    Rectangle {
        id: card
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        anchors.topMargin: Theme.gridMargin + 48
        width: Math.min(parent.width - 2 * Theme.gridMargin, 560)
        height: column.implicitHeight + 44
        radius: Theme.tripCardRadius
        color: Theme.spotifySurface
        border.width: 1
        border.color: Theme.spotifyRim

        Column {
            id: column
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 22
            spacing: 14

            Text {
                width: parent.width
                text: qsTr("Tuo kuvia USB-muistilta")
                font.family: Theme.fontFamily
                font.pixelSize: 19
                font.bold: true
                color: Theme.dataLabelValue
            }

            Text {
                width: parent.width
                wrapMode: Text.WordWrap
                text: qsTr("Kuvat haetaan USB-muistin juuressa olevasta kansiosta "
                           + "tesla_homedash_screensaver.")
                font.family: Theme.fontFamily
                font.pixelSize: 12
                color: Theme.spotifySubdued
            }

            // --- Waiting on the backend --------------------------------------
            Text {
                width: parent.width
                visible: popup.working
                wrapMode: Text.WordWrap
                text: popup.phase === "listing" ? qsTr("Haetaan USB-muisteja…")
                                                : qsTr("Liitetään USB-muistia ja etsitään kuvia…")
                font.family: Theme.fontFamily
                font.pixelSize: 14
                color: Theme.dataLabelValue

                SequentialAnimation on opacity {
                    running: popup.working
                    loops: Animation.Infinite
                    NumberAnimation { to: 0.45; duration: 700; easing.type: Easing.InOutQuad }
                    NumberAnimation { to: 1.0; duration: 700; easing.type: Easing.InOutQuad }
                }
            }

            // --- Step 1: the drives ------------------------------------------
            Text {
                width: parent.width
                visible: popup.phase === "drives" && UsbImport.drives.length === 0
                wrapMode: Text.WordWrap
                text: qsTr("USB-muistia ei löytynyt. Liitä USB-muisti ja paina Päivitä.")
                font.family: Theme.fontFamily
                font.pixelSize: 14
                color: Theme.dataLabelValue
            }

            ListView {
                id: driveList
                width: parent.width
                visible: popup.phase === "drives" && count > 0
                height: Math.min(count, 4) * 62 - spacing
                spacing: 6
                clip: true
                interactive: count > 4
                model: UsbImport.drives

                delegate: Rectangle {
                    id: driveRow

                    required property var modelData

                    width: driveList.width
                    height: 56
                    radius: 8
                    color: tap.pressed ? Theme.tripComboPressed : Theme.tripComboBg
                    border.width: 1
                    border.color: Theme.tripCardBorder

                    Column {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.leftMargin: 14
                        anchors.rightMargin: 14
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 2

                        Text {
                            width: parent.width
                            elide: Text.ElideRight
                            text: popup.driveName(driveRow.modelData)
                            font.family: Theme.fontFamily
                            font.pixelSize: 15
                            color: Theme.dataLabelValue
                        }

                        Text {
                            width: parent.width
                            elide: Text.ElideRight
                            text: [popup.sizeText(driveRow.modelData.size),
                                   driveRow.modelData.fstype,
                                   driveRow.modelData.device].filter(part => part.length > 0)
                                  .join(" · ")
                            font.family: Theme.fontFamily
                            font.pixelSize: 12
                            color: Theme.spotifySubdued
                        }
                    }

                    MouseArea {
                        id: tap
                        anchors.fill: parent
                        onClicked: UsbImport.scan(driveRow.modelData.device)
                    }
                }
            }

            // --- Step 2: what the drive holds --------------------------------
            Column {
                width: parent.width
                visible: popup.phase === "ready"
                spacing: 4

                Text {
                    width: parent.width
                    elide: Text.ElideRight
                    text: popup.driveName(UsbImport.device)
                    font.family: Theme.fontFamily
                    font.pixelSize: 12
                    color: Theme.spotifySubdued
                }

                Text {
                    width: parent.width
                    wrapMode: Text.WordWrap
                    text: !UsbImport.found
                          ? qsTr("USB-muistin juuresta ei löytynyt kansiota "
                                 + "tesla_homedash_screensaver.")
                          : UsbImport.count === 0
                            ? qsTr("Kansiossa tesla_homedash_screensaver ei ole kuvia.")
                            : qsTr("%1 löytyi (%2)").arg(popup.photos(UsbImport.count))
                                  .arg(popup.sizeText(UsbImport.bytes))
                    font.family: Theme.fontFamily
                    font.pixelSize: 15
                    color: popup.canImport ? Theme.dataLabelValue : "#ffd48a"
                }
            }

            // --- Step 3: the copy --------------------------------------------
            Column {
                width: parent.width
                visible: popup.phase === "copying"
                spacing: 8

                Text {
                    width: parent.width
                    text: qsTr("Kopioidaan kuvia… %1 / %2")
                          .arg(UsbImport.copied + UsbImport.skipped).arg(UsbImport.total)
                    font.family: Theme.fontFamily
                    font.pixelSize: 14
                    color: Theme.dataLabelValue
                }

                Rectangle {
                    width: parent.width
                    height: 6
                    radius: 3
                    color: Theme.tripComboBg

                    Rectangle {
                        height: parent.height
                        radius: parent.radius
                        color: Theme.accent
                        width: UsbImport.total > 0
                               ? parent.width * (UsbImport.copied + UsbImport.skipped)
                                 / UsbImport.total
                               : 0

                        Behavior on width {
                            NumberAnimation { duration: 200 }
                        }
                    }
                }
            }

            Column {
                width: parent.width
                visible: popup.phase === "done"
                spacing: 4

                Text {
                    width: parent.width
                    wrapMode: Text.WordWrap
                    text: qsTr("%1 tuotu kuvakansioon.").arg(popup.photos(UsbImport.copied))
                    font.family: Theme.fontFamily
                    font.pixelSize: 15
                    color: "#4ade80"
                }

                Text {
                    width: parent.width
                    visible: UsbImport.skipped > 0
                    wrapMode: Text.WordWrap
                    text: UsbImport.skipped === 1
                          ? qsTr("1 kuva oli siellä jo valmiiksi.")
                          : qsTr("%1 kuvaa oli siellä jo valmiiksi.").arg(UsbImport.skipped)
                    font.family: Theme.fontFamily
                    font.pixelSize: 12
                    color: Theme.spotifySubdued
                }

                Text {
                    width: parent.width
                    visible: UsbImport.unmounted
                    text: qsTr("Voit nyt irrottaa USB-muistin.")
                    font.family: Theme.fontFamily
                    font.pixelSize: 12
                    color: Theme.spotifySubdued
                }
            }

            Text {
                width: parent.width
                visible: popup.phase === "error"
                wrapMode: Text.WordWrap
                text: UsbImport.message.length > 0 ? UsbImport.message
                                                   : qsTr("Kuvien tuonti epäonnistui.")
                font.family: Theme.fontFamily
                font.pixelSize: 14
                color: "#ffd48a"
            }

            // Buttons pinned to the card's edges, so one appearing (the import
            // button when the scan answers) moves none of the others under a
            // finger already reaching for them.
            Item {
                width: parent.width
                height: 34

                DialogButton {
                    anchors.left: parent.left
                    visible: popup.phase === "drives" || popup.phase === "ready"
                             || popup.phase === "error"
                    label: popup.phase === "drives" ? qsTr("Päivitä") : qsTr("Takaisin")
                    onActivated: UsbImport.listDrives()
                }

                Row {
                    anchors.right: parent.right
                    spacing: 10

                    DialogButton {
                        primary: true
                        visible: popup.canImport
                        label: qsTr("Tuo %1").arg(popup.photos(UsbImport.count))
                        onActivated: UsbImport.start()
                    }

                    // During a copy this stops it after the current file; what was
                    // copied stays.
                    DialogButton {
                        label: popup.phase === "done" ? qsTr("Sulje") : qsTr("Peruuta")
                        onActivated: UsbImport.close()
                    }
                }
            }
        }
    }
}
