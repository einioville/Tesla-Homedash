import QtQuick
import frontend_v2

// Spotify device identification, as a small modal dialog over the OPTIONS VIEW.
//
// Sibling of SpotifyAuthPopup, with one deliberate difference: this one is a
// child of SettingsView, not of Main.qml, so it fills and darkens only that
// screen. The re-authorization prompt has to be app-level because the grant can
// die while any view is on screen; a device scan is the opposite — it is only
// ever started by the "Tunnista laite" row a few pixels above this dialog, so
// raising it over the whole dashboard would darken views the user never asked
// about and hide the card the flow belongs to.
//
// Nothing is decided here. The backend stops the radio, polls Spotify for what
// is playing on any device and streams the result back; this side shows the
// device and the track so the user can confirm it is the right one, and asks
// the backend to write it to spotifyDeviceId.
Item {
    id: popup

    anchors.fill: parent
    visible: SpotifyDevice.phase !== "idle"
    // Already the last child of the view, so this only pins the ordering if a
    // card is ever added after it.
    z: 100

    readonly property bool scanning: SpotifyDevice.phase === "scanning"
    readonly property bool saving: SpotifyDevice.phase === "saving"
    readonly property bool busy: popup.scanning || popup.saving
    readonly property bool succeeded: SpotifyDevice.phase === "done"
    readonly property bool failed: SpotifyDevice.phase === "error"

    // Swallows every tap that misses the card, so the settings underneath cannot
    // be operated while a scan is running.
    MouseArea {
        anchors.fill: parent
        preventStealing: true
        onClicked: {}
    }

    // Scrim. Lighter than a plain blackout because SettingsView blurs its own
    // content behind this dialog — at a near-opaque tint the blur would be
    // invisible and its cost pure waste.
    Rectangle {
        anchors.fill: parent
        color: Theme.dialogScrim
    }

    Rectangle {
        id: card
        anchors.centerIn: parent
        // Wider than the auth dialog: this one carries cover art and four lines
        // of metadata, and a track title should elide rather than wrap.
        width: Math.min(parent.width - 2 * Theme.gridMargin, 520)
        height: column.implicitHeight + 44
        radius: Theme.tripCardRadius
        // Spotify's own elevated-surface grey, opaque: this is a modal, and a
        // dialog you can read the blurred screen through smears that backdrop
        // into its own cover art and metadata.
        color: Theme.spotifySurface
        border.width: 1
        // A hairline rather than the settings cards' bright white rim — the
        // green light hugging the inside of it is the edge the eye should follow.
        border.color: Theme.spotifyRim

        // A Spotify-green light chasing the inside of the card's rim while the
        // scan looks, which completes into a fully lit ring the moment a device
        // is on screen. It is the one piece of feedback visible from across the
        // room — the user is at the speaker, not at the panel — and going from
        // "one arc moving" to "the whole border lit" is legible at that distance
        // in a way that a line of Finnish text is not.
        SpotifyGlowBorder {
            anchors.fill: parent
            // Taken from the card rather than restated, so the glow's outer edge
            // lands on the inside of this rim however the rim changes.
            borderWidth: card.border.width
            cornerRadius: card.radius
            complete: SpotifyDevice.hasDevice
        }

        Column {
            id: column
            anchors.centerIn: parent
            width: parent.width - 44
            spacing: 14

            Text {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                text: qsTr("Tunnista Spotify-laite")
                font.family: Theme.fontFamily
                font.pixelSize: 19
                // Synthesized embolden (the font ships one weight) — Spotify
                // sets its headings well above its body copy, and this card has
                // four text sizes that otherwise differ by only a few pixels.
                font.bold: true
                color: Theme.dataLabelValue
            }

            // The block that swaps between the "start playing something" guide
            // and the device that was found. Both live in ONE container with a
            // height floor, because the card must not resize when a device
            // appears or stops playing: on a 10" touch panel a control that
            // moves between reach and tap mis-routes the tap — here it would put
            // "Peruuta" under a finger aimed at "Valitse laite" and kill the scan.
            Item {
                id: swapBlock
                width: parent.width
                // Whichever state is taller wins, so neither transition changes
                // the card's height. The literal is a floor for the degenerate
                // case where both blocks measure small (no track lines yet).
                implicitHeight: Math.max(guideBlock.implicitHeight,
                                         details.implicitHeight, 96)
                height: implicitHeight

                Column {
                    id: guideBlock
                    width: parent.width
                    anchors.verticalCenter: parent.verticalCenter
                    // The guide is stale advice once a device is on screen; the
                    // children below are always visible, so the block's implicit
                    // height stays measurable while it is hidden.
                    visible: popup.scanning && !SpotifyDevice.hasDevice
                    spacing: 14

                    // The instruction, shown only while the scan has found nothing yet.
                    Text {
                        id: guide
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.WordWrap
                        text: qsTr("Aloita toisto haluamallasi Spotify-laitteella")
                        font.family: Theme.fontFamily
                        font.pixelSize: 14
                        color: Theme.dataLabelValue
                    }

                    // The radio going quiet is not a fault, and without this line it
                    // looks like one.
                    Text {
                        id: guideNote
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.WordWrap
                        text: qsTr("Radion toisto on pysäytetty tunnistuksen ajaksi.")
                        font.family: Theme.fontFamily
                        font.pixelSize: 12
                        color: Theme.spotifySubdued
                    }

                    // The only motion on the card, so "still looking" reads at a glance
                    // from across the room.
                    Text {
                        id: glyph
                        anchors.horizontalCenter: parent.horizontalCenter
                        font.family: Theme.fontFamily
                        font.pixelSize: 40
                        text: "…"
                        color: Theme.spotifySubdued

                        SequentialAnimation on opacity {
                            running: guideBlock.visible
                            loops: Animation.Infinite
                            NumberAnimation { to: 0.35; duration: 700; easing.type: Easing.InOutQuad }
                            NumberAnimation { to: 1.0; duration: 700; easing.type: Easing.InOutQuad }
                        }
                        // The animation leaves opacity wherever it stopped, so it has to be
                        // put back explicitly once the scan settles.
                        onOpacityChanged: if (!guideBlock.visible && opacity !== 1.0) opacity = 1.0
                    }
                }

                // What was found. Everything elides: the card's width is fixed, and a
                // long track title must not resize the dialog under the user's finger.
                Row {
                    id: details
                    width: parent.width
                    anchors.verticalCenter: parent.verticalCenter
                    visible: SpotifyDevice.hasDevice
                    spacing: 14

                    // Hidden outright when there is no usable image — an episode with
                    // no art, or a URL that fails to load, leaves no broken box.
                    Rectangle {
                        id: cover
                        width: 72
                        height: 72
                        radius: 8
                        color: Theme.spotifyBase
                        clip: true
                        visible: SpotifyDevice.trackImageUrl.length > 0 &&
                                 coverImage.status !== Image.Error

                        Image {
                            id: coverImage
                            anchors.fill: parent
                            source: SpotifyDevice.trackImageUrl
                            asynchronous: true
                            fillMode: Image.PreserveAspectCrop
                            sourceSize.width: cover.width
                            sourceSize.height: cover.height
                            smooth: true
                        }
                    }

                    Column {
                        id: info
                        width: details.width -
                               (cover.visible ? cover.width + details.spacing : 0)
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 2

                        // The device is what the user is actually choosing, so it
                        // leads in the value colour; the track is only evidence that
                        // this is the right one.
                        Text {
                            width: parent.width
                            elide: Text.ElideRight
                            text: SpotifyDevice.deviceName
                            font.family: Theme.fontFamily
                            font.pixelSize: 16
                            font.bold: true
                            color: Theme.dataLabelValue
                        }

                        Text {
                            width: parent.width
                            elide: Text.ElideRight
                            // Volume is optional on the wire (-1 = unknown), and a
                            // device that cannot report it must not read as "0 %".
                            text: SpotifyDevice.deviceType +
                                  (SpotifyDevice.deviceVolume >= 0
                                      ? " · " + SpotifyDevice.deviceVolume + " %" : "")
                            font.family: Theme.fontFamily
                            font.pixelSize: 12
                            color: Theme.spotifySubdued
                        }

                        Item {
                            width: 1
                            height: 6
                        }

                        Text {
                            id: trackLine
                            width: parent.width
                            visible: SpotifyDevice.trackName.length > 0
                            elide: Text.ElideRight
                            text: SpotifyDevice.trackName
                            font.family: Theme.fontFamily
                            font.pixelSize: 13
                            color: Theme.dataLabelValue
                        }

                        Text {
                            width: parent.width
                            visible: SpotifyDevice.trackArtists.length > 0
                            elide: Text.ElideRight
                            text: SpotifyDevice.trackArtists
                            font.family: Theme.fontFamily
                            font.pixelSize: 12
                            color: Theme.spotifySubdued
                        }

                        Text {
                            width: parent.width
                            visible: SpotifyDevice.trackAlbum.length > 0
                            elide: Text.ElideRight
                            text: SpotifyDevice.trackAlbum
                            font.family: Theme.fontFamily
                            font.pixelSize: 11
                            color: Theme.spotifySubdued
                        }
                    }
                }
            }

            // Where the configured device stands. Without it, selecting the
            // device that is already configured looks like it did nothing.
            Text {
                id: currentLine
                width: parent.width
                visible: currentLine.text.length > 0
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                font.family: Theme.fontFamily
                font.pixelSize: 12
                color: Theme.spotifySubdued
                text: {
                    if (SpotifyDevice.isCurrent)
                        return qsTr("Tämä on jo valittu laite")
                    if (SpotifyDevice.currentDeviceName.length > 0)
                        return qsTr("Nykyinen laite: ") + SpotifyDevice.currentDeviceName
                    if (SpotifyDevice.currentDeviceId.length > 0)
                        return qsTr("Nykyinen laitetunnus: ") + SpotifyDevice.currentDeviceId
                    return ""
                }
            }

            // Result, and — while the scan is running — anything blocking it: a
            // missing grant or an unreachable API arrives as a message with the
            // scan still nominally on, and staring at a pulsing ellipsis forever
            // is worse than being told why nothing is happening.
            Text {
                id: resultLine
                width: parent.width
                visible: resultLine.text.length > 0
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                font.family: Theme.fontFamily
                font.pixelSize: 13
                // Amber stays amber: a warning is not brand-coloured, and a
                // failure rendered in Spotify green would read as success.
                color: popup.succeeded ? Theme.spotifyGreen
                     : popup.saving ? Theme.spotifySubdued : "#ffd48a"
                text: {
                    if (popup.succeeded)
                        return qsTr("Laite tallennettu.")
                    if (popup.saving)
                        return qsTr("Tallennetaan…")
                    if (SpotifyDevice.message.length > 0)
                        return SpotifyDevice.message
                    if (popup.failed)
                        return qsTr("Laitteen tunnistus epäonnistui.")
                    return ""
                }
            }

            Row {
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 10

                SpotifyButton {
                    // The action the dialog exists for, so it carries the green.
                    primary: true
                    // Gated on the FLOW, not the phase. A failed save leaves the
                    // phase on "error" while the backend keeps scanning, so a
                    // phase gate made the dialog a dead end — the device on
                    // screen with no way to select it. And the slot is held for
                    // the whole scanning/saving flow rather than appearing with
                    // the device: a button that joins and leaves the row moves
                    // the OTHER button sideways under a finger already reaching
                    // for it. Only the terminal "done" retires it.
                    visible: SpotifyDevice.flowActive && !popup.succeeded
                    // Selectable only with a device that carries an id (a
                    // restricted device has none on the wire) and no save
                    // already in flight. The dimming lives here rather than in
                    // SpotifyButton, which has no disabled state of its own;
                    // `enabled` propagates to its MouseArea, and the handler
                    // guards as well.
                    readonly property bool canSelect:
                        SpotifyDevice.deviceSelectable && !popup.saving
                    enabled: canSelect
                    opacity: canSelect ? 1.0 : 0.4
                    label: qsTr("Valitse laite")
                    onActivated: {
                        if (canSelect)
                            SpotifyDevice.select()
                    }
                }

                // "Peruuta" while the scan runs is not cosmetic — the backend
                // polls until told to stop, and this is what stops it.
                SpotifyButton {
                    label: popup.busy ? qsTr("Peruuta") : qsTr("Sulje")
                    onActivated: SpotifyDevice.cancel()
                }
            }
        }
    }
}
