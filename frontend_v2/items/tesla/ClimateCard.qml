import QtQuick
import QtQuick.Layouts
import frontend_v2

// Climate panel — the QML port of ClimateControllerCard. A top-left-anchored
// gradient card laying out inside/outside/target temperatures, the HVAC power
// button, the steering + seat heaters and the target-temperature ± arrows,
// reproducing the original 5-column grid. All data binds to the Tesla
// singleton; the controls call its HVAC invokables.
GradientCard {
    id: climate

    // Forwarded to the breathing HVAC glow so it idles while the dashboard is
    // hidden (DashboardView binds this to its isCurrent).
    property bool isCurrent: true

    gradientCx: 0.0
    gradientCy: 0.0

    GridLayout {
        id: grid
        anchors.fill: parent
        anchors.margins: 10
        columns: 5
        rowSpacing: 10
        columnSpacing: 10

        TemperatureCard {
            Layout.row: 0; Layout.column: 0; Layout.columnSpan: 2
            Layout.alignment: Qt.AlignLeft | Qt.AlignTop
            title: "Sisä"
            value: Tesla.insideTemp
            unit: "°C"
        }

        Text {
            Layout.row: 0; Layout.column: 2
            Layout.alignment: Qt.AlignHCenter | Qt.AlignTop
            text: "Ilmastointi"
            color: Theme.dataLabelValue
            font.family: Theme.fontFamily
            font.pointSize: 16
            horizontalAlignment: Text.AlignHCenter
        }

        TemperatureCard {
            Layout.row: 0; Layout.column: 3; Layout.columnSpan: 2
            Layout.alignment: Qt.AlignRight | Qt.AlignTop
            title: "Ulko"
            value: Tesla.outsideTemp
            unit: "°C"
        }

        // Reserves the central band (rows 1-2, cols 1-3) for the HVAC power
        // button. The button itself is centred on the whole card below (see
        // ClimateStarter), not placed in this cell, so its horizontal position
        // no longer depends on the grid's asymmetric column widths (col 0
        // carries the SteeringWidget; col 4 is empty). Keeping this cell with
        // the original size hints preserves the band's geometry and avoids
        // colliding with the SteeringWidget at row 2 / col 0.
        Item {
            id: starterCell
            Layout.row: 1; Layout.column: 1; Layout.rowSpan: 2; Layout.columnSpan: 3
            Layout.alignment: Qt.AlignCenter
            implicitWidth: 100
            implicitHeight: 100
        }

        SteeringWidget {
            Layout.row: 2; Layout.column: 0
            Layout.alignment: Qt.AlignHCenter | Qt.AlignBottom
            level: Tesla.hvacSteeringWheelHeatLevel
        }

        // Bottom control strip spanning all five columns. An equal fillWidth
        // spacer sits between every pair (CSS space-between): the two seat
        // heaters land hard against the left/right ends — only the GridLayout's
        // 10px padding shows beyond them — and the ± arrows and target readout
        // are spread evenly across the middle.
        RowLayout {
            Layout.row: 3; Layout.column: 0; Layout.columnSpan: 5
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignBottom
            spacing: 0

            SeatWidget {
                Layout.alignment: Qt.AlignBottom
                level: Tesla.seatHeaterLeft
                mirrored: false
            }

            Item { Layout.fillWidth: true }

            // Target-temperature down (blue glow).
            Item {
                Layout.alignment: Qt.AlignBottom
                implicitWidth: 40
                implicitHeight: 40
                GlowIcon {
                    anchors.fill: parent
                    iconSize: 40
                    glowRadiusPx: 20
                    source: "qrc:/resources/icons/arrow_left.svg"
                    glow: Theme.glowMinus
                }
                MouseArea { anchors.fill: parent; onClicked: Tesla.minusTemp() }
            }

            Item { Layout.fillWidth: true }

            TemperatureCard {
                Layout.alignment: Qt.AlignBottom
                title: "Target"
                value: Tesla.hvacLeftTemperatureRequest
                unit: "°C"
            }

            Item { Layout.fillWidth: true }

            // Target-temperature up (red glow).
            Item {
                Layout.alignment: Qt.AlignBottom
                implicitWidth: 40
                implicitHeight: 40
                GlowIcon {
                    anchors.fill: parent
                    iconSize: 40
                    glowRadiusPx: 20
                    source: "qrc:/resources/icons/arrow_right.svg"
                    glow: Theme.glowPlus
                }
                MouseArea { anchors.fill: parent; onClicked: Tesla.plusTemp() }
            }

            Item { Layout.fillWidth: true }

            SeatWidget {
                Layout.alignment: Qt.AlignBottom
                level: Tesla.seatHeaterRight
                mirrored: true
            }
        }
    }

    // HVAC power button. Centred on the CARD, not on the grid's columns-1-3
    // span — that span is off-centre because col 0 carries the SteeringWidget
    // while col 4 is empty, so an AlignCenter there drifts the button sideways.
    // horizontalCenter pins it to the true card centre (directly under the
    // "Ilmastointi" label) at any width; the vertical position is read straight
    // from the reserved starterCell band, so it matches the old placement and
    // stays put on resize with no magic offset.
    ClimateStarter {
        id: starter
        z: 1
        width: 100
        height: 100
        iconSize: 100
        anchors.horizontalCenter: parent.horizontalCenter
        y: grid.y + starterCell.y + (starterCell.height - height) / 2
        powerState: Tesla.hvacPower
        isCurrent: climate.isCurrent
        onClicked: Tesla.switchClimate()
    }
}
