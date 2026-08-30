import QtQuick
import frontend_v2

// Detail pane: the subsections of the ONE section selected in the sidebar.
//
// Each subsection is its own card — the same card the sidebar carries
// (Theme.tripCardBg / tripCardRadius / tripCardBorder) — stacked in a Flickable,
// so a general section such as Yleinen reads as "Näytönsäästäjä", "Sijainti ja
// aika", "Lisäasetukset" rather than one undifferentiated list of rows.
//
// The pane itself is transparent: the cards are the containers, and nesting them
// inside a further card would just draw a border around borders.
//
// A section can mix origins — Settings merges the local and backend schemas by
// group id — so the "sovelluksen/palvelimen asetukset" badge belongs to each
// CARD, not to the pane. The two halves fail differently (a backend card can
// reject a value or be unreachable), which is why the distinction is drawn at all.
Item {
    id: pane

    // The selected group from Settings.groups, or undefined while none is
    // selected / the list is still empty.
    property var groupData

    readonly property bool hasData: groupData !== undefined && groupData !== null
    readonly property var sections: hasData && groupData.sections !== undefined
                                    ? groupData.sections : []

    // --- Section title ----------------------------------------------------
    // No card of its own: it names what the sidebar has selected, and the cards
    // below carry the structure.
    Text {
        id: paneTitle
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: pane.hasData ? 34 : 0
        visible: pane.hasData
        verticalAlignment: Text.AlignVCenter
        text: pane.hasData && pane.groupData.label !== undefined ? pane.groupData.label : ""
        font.family: Theme.fontFamily
        font.pixelSize: 22
        color: Theme.dataLabelValue
        elide: Text.ElideRight
    }

    // --- Subsection cards -------------------------------------------------
    Flickable {
        id: flick
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: paneTitle.bottom
        anchors.bottom: parent.bottom
        anchors.topMargin: 2

        contentHeight: cards.implicitHeight
        clip: true
        // No ScrollBar: flicking is a Flickable behaviour, and a scroll bar is
        // mouse chrome on a device that only ever gets fingers. The clipped card
        // edge is the cue that there is more below.
        boundsBehavior: Flickable.StopAtBounds

        Column {
            id: cards
            width: flick.width
            spacing: 10

            Repeater {
                model: pane.sections

                Rectangle {
                    id: card

                    required property var modelData

                    readonly property bool isBackend: modelData.origin === "backend"
                    readonly property var entries: modelData.settings !== undefined
                                                   ? modelData.settings : []

                    width: cards.width
                    // Sized by content: the Flickable scrolls the stack, so a
                    // card is never itself scrollable or clipped.
                    height: cardBody.implicitHeight + 24
                    color: Theme.tripCardBg
                    radius: Theme.tripCardRadius
                    border.width: 1
                    border.color: Theme.tripCardBorder

                    Column {
                        id: cardBody
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.leftMargin: 14
                        anchors.rightMargin: 14
                        anchors.topMargin: 12
                        spacing: 2

                        // Card title + which half owns these values.
                        Item {
                            width: parent.width
                            height: cardTitle.implicitHeight

                            Text {
                                id: cardTitle
                                anchors.left: parent.left
                                text: card.modelData.label !== undefined
                                      ? card.modelData.label : card.modelData.id
                                // Deliberately well clear of the 15px row
                                // labels below it: the font has a single weight,
                                // so size is the only hierarchy lever there is.
                                font.family: Theme.fontFamily
                                font.pixelSize: 19
                                color: Theme.dataLabelValue
                            }

                            Rectangle {
                                anchors.left: cardTitle.right
                                anchors.leftMargin: 10
                                anchors.verticalCenter: cardTitle.verticalCenter
                                width: originLabel.implicitWidth + 14
                                height: originLabel.implicitHeight + 5
                                radius: 4
                                color: card.isBackend ? "#332f81c4" : "#33ffffff"
                                border.width: 1
                                border.color: card.isBackend ? "#802f81c4" : "#44ffffff"

                                Text {
                                    id: originLabel
                                    anchors.centerIn: parent
                                    text: card.isBackend ? qsTr("palvelin") : qsTr("sovellus")
                                    font.family: Theme.fontFamily
                                    font.pixelSize: 10
                                    color: card.isBackend ? "#9ecbf0" : Theme.dataLabelTitle
                                }
                            }
                        }

                        // Optional one-liner under the card title.
                        Text {
                            width: parent.width
                            // No explicit height: binding it to
                            // implicitHeight feeds a wrapped Text back into
                            // its own layout, and a Column already skips
                            // invisible children.
                            visible: card.modelData.help !== undefined
                                     && card.modelData.help.length > 0
                            text: card.modelData.help !== undefined ? card.modelData.help : ""
                            font.family: Theme.fontFamily
                            font.pixelSize: 12
                            color: Theme.dataLabelTitle
                            wrapMode: Text.WordWrap
                        }

                        // A subsection may declare a runtime status widget with
                        // `status: "<id>"`. Not every fact about a section fits in
                        // a setting row — "is that address reachable?" belongs to
                        // the host and port TOGETHER, not to either one.
                        Loader {
                            width: parent.width
                            active: sourceComponent !== null
                            visible: active
                            height: active && item !== null ? item.implicitHeight : 0
                            // Named in the schema, resolved here. `active` gates
                            // construction, which is what keeps the probe from
                            // firing — and Chromium from starting — for a card
                            // that did not ask for it.
                            sourceComponent: {
                                switch (card.modelData.status) {
                                case "backendProbe": return probeComponent
                                case "systemStatus": return systemComponent
                                case "spotifyAuth": return spotifyComponent
                                default: return null
                                }
                            }
                        }

                        Repeater {
                            model: card.entries

                            Column {
                                required property int index
                                required property var modelData

                                width: cardBody.width

                                SettingRow {
                                    width: parent.width
                                    // Wider than the old two-column layout
                                    // allowed; a slider this size is comfortable
                                    // to drag with a fingertip.
                                    editorWidth: 320
                                    setting: modelData
                                }

                                Rectangle {
                                    visible: index < card.entries.length - 1
                                    width: parent.width
                                    height: 1
                                    color: "#1affffff"
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    // The status widgets a subsection may name. Declared once here rather than
    // inline, so the Loader above is a lookup instead of a chain of conditions.
    Component { id: probeComponent; BackendProbeStatus {} }
    Component { id: systemComponent; SystemStatusPanel {} }
    Component { id: spotifyComponent; SpotifyAuthStatus {} }

    // Shown before the first schema arrives (and if one never does).
    Text {
        anchors.centerIn: parent
        visible: pane.sections.length === 0
        text: qsTr("Valitse osio")
        font.family: Theme.fontFamily
        font.pixelSize: 14
        color: Theme.dataLabelTitle
    }
}
