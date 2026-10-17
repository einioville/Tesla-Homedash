import QtQuick
import frontend_v2

// Detail pane: the subsections of the ONE section selected in the sidebar.
//
// Each subsection is its own card — the same card the sidebar carries
// (Theme.tripCardBg / tripCardRadius / tripCardBorder) — stacked in a Flickable,
// so a general section such as Yleinen reads as "Näytönsäästäjä", "Sijainti ja
// aika", "Luna" rather than one undifferentiated list of rows.
//
// The pane itself is transparent: the cards are the containers, and nesting them
// inside a further card would just draw a border around borders.
Item {
    id: pane

    // The selected group from Settings.groups, or undefined while none is
    // selected / the list is still empty.
    property var groupData
    // The view's isCurrent, for the widgets that record or poll only while it is.
    property bool live: false

    // The last write result, {key, text, error}, shown beside that row's title.
    // Held by the view rather than by the row: a schema change that alters the
    // cards' shape rebuilds them (see `layout`), and the row that made the write
    // may not outlive it.
    property var rowFeedback: ({ key: "", text: "", error: false })

    readonly property bool hasData: groupData !== undefined && groupData !== null
    readonly property var sections: hasData && groupData.sections !== undefined
                                    ? groupData.sections : []
    // A group may name a screen of its own (`view`) that replaces the cards — a
    // section that SHOWS something rather than setting it. Resolved in the view
    // table at the bottom of this file.
    readonly property string viewId: hasData && groupData.view !== undefined ? groupData.view : ""

    // --- Rows that survive a write ------------------------------------------
    // Every write rebuilds Settings.groups — at once for a local key, on the
    // schema broadcast for a backend one — and a Repeater handed a new array
    // destroys and recreates every delegate. Rebuilt rows cannot animate: a
    // switch would reappear already moved, and nested rows would pop in.
    //
    // So the cards are built from `layout`, which is replaced only when the
    // section's SHAPE changes — a different section, a schema with other
    // entries, options or tiers — and each row reads its current entry by key
    // from `liveEntries`. A write changes only `value` (and the local `modified`
    // flag), so it leaves the shape alone, the delegates stay, and their
    // bindings carry the new value in.
    property var layout: []
    property string layoutShape: ""

    readonly property var liveEntries: {
        const out = {}
        for (let i = 0; i < sections.length; ++i) {
            const entries = sections[i].settings !== undefined ? sections[i].settings : []
            for (let j = 0; j < entries.length; ++j)
                out[entries[j].key] = entries[j]
        }
        return out
    }

    function shapeOf(list) {
        const out = []
        for (let i = 0; i < list.length; ++i) {
            const section = Object.assign({}, list[i])
            const entries = section.settings !== undefined ? section.settings : []
            section.settings = []
            for (let j = 0; j < entries.length; ++j) {
                const entry = Object.assign({}, entries[j])
                delete entry.value
                delete entry.modified
                // Facts that change with the value (the DEBUG log's end time).
                delete entry.runtime
                section.settings.push(entry)
            }
            out.push(section)
        }
        return JSON.stringify(out)
    }

    function syncLayout() {
        const shape = pane.shapeOf(pane.sections)
        if (shape === pane.layoutShape)
            return
        pane.layoutShape = shape
        pane.layout = pane.sections
    }

    onSectionsChanged: syncLayout()
    Component.onCompleted: syncLayout()

    // --- On-screen keyboard -------------------------------------------------
    // The keyboard (Main.qml) covers the bottom half of the screen, which is where
    // most rows sit. How far it reaches up over the flickable, in the flickable's
    // own coordinates; 0 while it is down. Qt.inputMethod.keyboardRectangle is in
    // scene coordinates and only settles once the slide-in has finished.
    readonly property real keyboardInset: {
        const kb = Qt.inputMethod.keyboardRectangle
        if (!Qt.inputMethod.visible || kb.height <= 0)
            return 0
        return Math.max(0, flick.height - flick.mapFromItem(null, 0, kb.y).y)
    }
    readonly property Item focusedItem: Window.activeFocusItem

    // Either can come first: focus moves on the press, the inset once the panel
    // has settled — and moving between fields changes only the focus.
    onKeyboardInsetChanged: revealFocused()
    onFocusedItemChanged: revealFocused()

    // Scrolls the focused field into the strip left visible above the keyboard.
    function revealFocused() {
        const item = pane.focusedItem
        if (pane.keyboardInset <= 0 || item === null || !pane.isInsideFlick(item))
            return
        const margin = 16
        const top = item.mapToItem(flick.contentItem, 0, 0).y
        const visibleHeight = flick.height - pane.keyboardInset
        let target = flick.contentY
        if (top + item.height + margin > flick.contentY + visibleHeight)
            target = top + item.height + margin - visibleHeight
        else if (top - margin < flick.contentY)
            target = top - margin
        target = Math.max(0, Math.min(target, flick.contentHeight + flick.bottomMargin - flick.height))
        if (target !== flick.contentY) {
            revealAnimation.to = target
            revealAnimation.restart()
        }
    }

    // The rendered row for a setting key, or null. Rows name themselves
    // ("settingRow:<key>"), so this needs no registry that could go stale.
    function rowItem(key) {
        const name = "settingRow:" + key
        const stack = [cards]
        while (stack.length > 0) {
            const item = stack.pop()
            if (item.objectName === name)
                return item
            for (let i = 0; i < item.children.length; ++i)
                stack.push(item.children[i])
        }
        return null
    }

    // Scrolls a row to the middle of the pane (clamped), at once — the spotlight
    // measures the row straight after.
    function revealRow(row) {
        revealAnimation.stop()
        const top = row.mapToItem(flick.contentItem, 0, 0).y
        const target = top + row.height / 2 - flick.height / 2
        flick.contentY = Math.max(0, Math.min(target, flick.contentHeight - flick.height))
    }

    function isInsideFlick(item) {
        for (let p = item.parent; p !== null; p = p.parent) {
            if (p === flick.contentItem)
                return true
        }
        return false
    }

    NumberAnimation {
        id: revealAnimation
        target: flick
        property: "contentY"
        duration: 200
        easing.type: Easing.OutCubic
    }

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

    // --- A section's own screen --------------------------------------------
    // In place of the cards, for a group naming a `view`. Built only while that
    // section is selected, so whatever it polls stops when the user moves on.
    Loader {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: paneTitle.bottom
        anchors.bottom: parent.bottom
        anchors.topMargin: 2
        active: pane.viewId !== ""
        visible: active
        sourceComponent: {
            switch (pane.viewId) {
            case "systemStatus": return systemSectionComponent
            default: return null
            }
        }
    }

    // --- Subsection cards -------------------------------------------------
    ElasticFlickable {
        id: flick
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: paneTitle.bottom
        anchors.bottom: parent.bottom
        anchors.topMargin: 2
        visible: pane.viewId === ""

        contentHeight: cards.implicitHeight
        // Room to scroll the last rows up above the keyboard while it is up.
        bottomMargin: pane.keyboardInset
        clip: true
        // No ScrollBar: flicking is a Flickable behaviour, and a scroll bar is
        // mouse chrome on a device that only ever gets fingers. The clipped card
        // edge is the cue that there is more below.

        Column {
            id: cards
            width: flick.width
            spacing: 10

            Repeater {
                model: pane.layout

                Rectangle {
                    id: card

                    required property var modelData

                    readonly property var entries: modelData.settings !== undefined
                                                   ? modelData.settings : []

                    // How the entries hang together, one {parent, rule, depth} per
                    // entry. An entry is NESTED under the setting its first `key`
                    // rule names when that setting sits earlier in this card with
                    // nothing between them but its own nested entries — the timeout
                    // under its switch. Anything looser (a later setting, another
                    // card, a row in between) would draw the entry under the wrong
                    // parent, so its rules only fade it, as SettingRow does for
                    // every rule that is not the nesting one.
                    readonly property var links: {
                        const out = []
                        for (let i = 0; i < entries.length; ++i) {
                            let link = { parent: -1, rule: null, depth: 0 }
                            for (const rule of rules.list(entries[i].relevantWhen)) {
                                if (rule.key === undefined)
                                    continue
                                let p = -1
                                for (let j = 0; j < i; ++j) {
                                    if (entries[j].key === rule.key)
                                        p = j
                                }
                                // Nested entries follow their parent as one block,
                                // so the entry just above is the parent or inside it.
                                let k = i - 1
                                while (k >= 0 && k !== p)
                                    k = out[k].parent
                                if (p >= 0 && k === p) {
                                    link = { parent: p, rule: rule, depth: out[p].depth + 1 }
                                    break
                                }
                            }
                            out.push(link)
                        }
                        return out
                    }

                    // Whether each entry is on screen: a nested entry is hidden
                    // while its rule fails or its parent is hidden itself — a
                    // value set for a feature that is off is no business of the
                    // screen. Parents come first, so one pass resolves the chain.
                    readonly property var shownEntries: {
                        const revision = Settings.valuesRevision
                        const out = []
                        for (const link of links)
                            out.push(link.parent < 0 || (out[link.parent] && rules.ruleHolds(link.rule)))
                        return out
                    }

                    // What was on screen before the latest change, to tell which
                    // entries just appeared or went.
                    property var lastShown: []

                    // Entries that appear slide out from under the row above them
                    // one after another, top first, like dominoes; entries that go
                    // fold back up, bottom first. Ranked per change, so the first
                    // revealed entry starts at once however far down it sits.
                    function animateShown() {
                        const now = card.shownEntries
                        const was = card.lastShown
                        card.lastShown = now
                        if (was.length !== now.length)
                            return
                        let rank = 0
                        const going = []
                        for (let i = 0; i < now.length; ++i) {
                            if (now[i] === was[i])
                                continue
                            const item = entryRepeater.itemAt(i)
                            if (item === null)
                                continue
                            if (now[i])
                                item.show(rank++ * Theme.revealStagger)
                            else
                                going.push(item)
                        }
                        for (let k = 0; k < going.length; ++k)
                            going[going.length - 1 - k].hide(k * Theme.revealStagger / 2)
                    }

                    onShownEntriesChanged: animateShown()
                    Component.onCompleted: lastShown = shownEntries

                    // The header band is a translucent BLACK wash rather than a
                    // fixed colour: the card itself is translucent over the
                    // dashboard background, so darkening has to compose with
                    // whatever is behind it.
                    readonly property color headerBg: "#33000000"
                    readonly property color headerRule: "#38ffffff"

                    width: cards.width
                    // Sized by content: the Flickable scrolls the stack, so a
                    // card is never itself scrollable or clipped.
                    height: cardBody.implicitHeight
                    color: Theme.tripCardBg
                    radius: Theme.tripCardRadius
                    border.width: 1
                    border.color: Theme.tripCardBorder

                    Column {
                        id: cardBody
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        spacing: 0

                        // --- Header band ---------------------------------
                        // Spans the full card, so the rule under the title
                        // meets both borders instead of floating inside a
                        // padded column.
                        Item {
                            id: cardHeader
                            width: parent.width
                            height: cardTitle.implicitHeight + 20

                            // Rounded at the TOP only, via the per-corner radii
                            // (Qt 6.7+). Squaring the bottom with a second
                            // rectangle would NOT work: the wash is translucent,
                            // so the overlap composites twice and paints a
                            // visibly darker strip under the title. Inset by one
                            // pixel so the card's border stays visible.
                            Rectangle {
                                anchors.fill: parent
                                anchors.leftMargin: card.border.width
                                anchors.rightMargin: card.border.width
                                anchors.topMargin: card.border.width
                                topLeftRadius: card.radius - card.border.width
                                topRightRadius: card.radius - card.border.width
                                bottomLeftRadius: 0
                                bottomRightRadius: 0
                                color: card.headerBg
                            }

                            Text {
                                id: cardTitle
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.leftMargin: 14
                                anchors.rightMargin: 14
                                anchors.verticalCenter: parent.verticalCenter
                                text: card.modelData.label !== undefined
                                      ? card.modelData.label : card.modelData.id
                                // Deliberately well clear of the 15px row labels
                                // below it. The bundled font ships a single
                                // weight, so `bold` is Qt's synthesized embolden
                                // — enough to separate the band from the rows.
                                font.family: Theme.fontFamily
                                font.pixelSize: 19
                                font.bold: true
                                color: Theme.dataLabelValue
                                elide: Text.ElideRight
                            }

                            // Edge to edge: inset only by the border it meets.
                            Rectangle {
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.bottom: parent.bottom
                                anchors.leftMargin: card.border.width
                                anchors.rightMargin: card.border.width
                                height: 1
                                color: card.headerRule
                            }
                        }

                        // --- Card body -----------------------------------
                        // No vertical padding of its own. Every row already centres
                        // its content with at least 12px above and below, so a card
                        // margin on top of that would make the first and last rows
                        // lopsided — more space toward the card edge than toward the
                        // divider. Only the intro block pads itself.
                        Item {
                            width: parent.width
                            height: cardContent.implicitHeight

                            Column {
                                id: cardContent
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.top: parent.top
                                anchors.leftMargin: 14
                                anchors.rightMargin: 14

                                // Intro: the card's help line and status widget. Unlike
                                // a row it has no padding of its own, so it gets some —
                                // at the bottom too when nothing follows it (a
                                // settings-free card such as the Tesla field table).
                                Column {
                                    width: parent.width
                                    visible: introHelp.visible || introStatus.active
                                    topPadding: 12
                                    bottomPadding: card.entries.length > 0 ? 2 : 12
                                    spacing: 2

                                    // Optional one-liner under the card title.
                                    Text {
                                        id: introHelp
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
                                        id: introStatus
                                        width: parent.width
                                        active: sourceComponent !== null
                                        visible: active
                                        height: active && item !== null ? item.implicitHeight : 0
                                        // Named in the schema, resolved here. `active` gates
                                        // construction, which is what keeps the probe from
                                        // firing for a card that did not ask for it.
                                        sourceComponent: {
                                            switch (card.modelData.status) {
                                            case "backendProbe": return probeComponent
                                            case "appUpdate": return updateComponent
                                            case "screenPower": return screenPowerComponent
                                            case "teslaProperties": return teslaFieldsComponent
                                            case "equalizer": return equalizerComponent
                                            case "pairedDisplays": return pairedDisplaysComponent
                                            default: return null
                                            }
                                        }
                                    }
                                }

                                Repeater {
                                    id: entryRepeater
                                    model: card.entries

                                    // A nested entry is indented one step per level,
                                    // beside a rail running down from its parent. The
                                    // parent has no divider above its first nested
                                    // entry, the nested entries are divided from each
                                    // other only from the indent, and a full-width
                                    // divider closes the block — so it reads as one
                                    // unit with the setting it belongs to.
                                    // A Reveal, so an entry whose parent setting
                                    // turns on slides out from under it instead of
                                    // popping in (the card orders them, above).
                                    Reveal {
                                        id: entry

                                        required property int index
                                        required property var modelData

                                        readonly property int depth: card.links[index].depth
                                        // The next entry actually on screen, or -1: it
                                        // decides the divider and where the rails end.
                                        readonly property int next: {
                                            for (let j = index + 1; j < card.shownEntries.length; ++j) {
                                                if (card.shownEntries[j])
                                                    return j
                                            }
                                            return -1
                                        }
                                        readonly property int nextDepth: next >= 0 ? card.links[next].depth : 0
                                        // The depth of the entry on screen just above,
                                        // 0 at the top: it decides where the rails begin.
                                        readonly property int prevDepth: {
                                            for (let j = index - 1; j >= 0; --j) {
                                                if (card.shownEntries[j])
                                                    return card.links[j].depth
                                            }
                                            return 0
                                        }

                                        width: cardContent.width
                                        fullHeight: settingRow.height + (divider.visible ? 1 : 0)
                                        // Placed without animating when the card is
                                        // built; only later changes animate.
                                        Component.onCompleted: snap(card.shownEntries[index] === true)

                                        // One rail per level. It runs through the
                                        // divider to the next nested entry, and is
                                        // inset by the row's 12px padding at BOTH ends
                                        // of its block — flush at the top with only the
                                        // bottom inset, it would sit above the text it
                                        // marks and make a lone nested row look low.
                                        Repeater {
                                            model: entry.depth

                                            Rectangle {
                                                required property int index

                                                readonly property bool opens: entry.prevDepth <= index
                                                readonly property bool closes: entry.next < 0 || entry.nextDepth <= index

                                                x: index * Theme.settingChildIndent + 6
                                                y: opens ? 12 : 0
                                                width: 2
                                                height: entry.fullHeight - y - (closes ? 12 : 0)
                                                radius: 1
                                                color: Theme.settingChildRail
                                            }
                                        }

                                        SettingRow {
                                            id: settingRow
                                            x: entry.depth * Theme.settingChildIndent
                                            width: parent.width - x
                                            feedback: pane.rowFeedback
                                            // Wider than SettingRow's default: a slider
                                            // this size is comfortable to drag with a
                                            // fingertip.
                                            editorWidth: 320
                                            // The current entry, by key: the
                                            // delegate outlives writes, its
                                            // modelData does not change with them.
                                            setting: {
                                                const live = pane.liveEntries[entry.modelData.key]
                                                return live !== undefined ? live : entry.modelData
                                            }
                                        }

                                        // None above this entry's own first nested
                                        // entry; otherwise from the next entry's indent.
                                        Rectangle {
                                            id: divider
                                            visible: entry.next >= 0 && entry.nextDepth <= entry.depth
                                            anchors.bottom: parent.bottom
                                            x: entry.nextDepth * Theme.settingChildIndent
                                            width: parent.width - x
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
        }
    }

    // Evaluates the entries' `relevantWhen` rules for the nesting above.
    SettingRules { id: rules }

    // The status widgets a subsection may name. Declared once here rather than
    // inline, so the Loader above is a lookup instead of a chain of conditions.
    Component { id: probeComponent; BackendProbeStatus {} }
    Component { id: updateComponent; UpdatePanel {} }
    Component { id: screenPowerComponent; ScreenPowerStatus {} }
    Component { id: teslaFieldsComponent; TeslaFieldTable {} }
    Component { id: equalizerComponent; EqualizerPanel { live: pane.live } }
    Component { id: pairedDisplaysComponent; PairedDisplaysPanel {} }

    // The screens a group may name with `view`.
    Component { id: systemSectionComponent; SystemStatusSection {} }

    // Shown while there is no section at all: the bundled schema failed to load
    // and no backend schema has arrived.
    Text {
        anchors.centerIn: parent
        visible: pane.sections.length === 0 && pane.viewId === ""
        text: qsTr("Valitse osio")
        font.family: Theme.fontFamily
        font.pixelSize: 14
        color: Theme.dataLabelTitle
    }
}
