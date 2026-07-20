import QtQuick
import QtQuick.Effects
import Qt.labs.folderlistmodel
import frontend_v2

// Full-screen idle screensaver. After the inactivity timeout (or F10 for testing)
// the screen fades to black and photos from App.screensaverDir are tossed onto a
// pile — the newest lands on top in a white frame at a random tilt/offset, the
// earlier ones peeking out underneath (up to Theme.screensaverStackCount kept),
// like printed photos thrown on a table; the oldest fades out as a new one lands.
// Any tap dismisses it and reveals the last-used view (this overlay never touches
// window.currentView, so the resident view is simply uncovered).
//
// Zero-cost when inactive: the advance timer only runs while active and the whole
// overlay is not rendered once faded out (mirrors the project's freeze convention).
Item {
    id: root

    // Keyboard-test override, kept SEPARATE from the idle machinery on purpose: a
    // key press is itself an "activity" event the IdleWatcher sees, so triggering
    // off Idle.idle would immediately cancel itself. forceShow sidesteps that.
    property bool forceShow: false

    readonly property bool active: Theme.screensaverEnabled
                                   && (Idle.idle || root.forceShow)
                                   && folderModel.count > 0

    // Fade in/out rather than pop. Stay renderable through the fade-out (visible
    // while any opacity remains) so the photos fade with the black backdrop.
    opacity: active ? 1.0 : 0.0
    visible: opacity > 0.0
    Behavior on opacity {
        NumberAnimation { duration: Theme.screensaverFadeMs; easing.type: Easing.InOutQuad }
    }

    // Seed the first photo the moment the screensaver activates. The pile is left
    // intact on deactivate so the fade-out shows the photos fading (and a quick
    // re-activation resumes where it left off).
    onActiveChanged: {
        if (active && pile.count === 0)
            pushNext()
    }

    // Shuffled playback order (a "bag" holding every image index, refilled when
    // emptied) so EVERY photo in the folder is shown exactly once per pass before
    // any repeat — fair coverage no matter how large the folder is.
    property var _shuffleBag: []
    property int _lastIdx: -1

    function _refillBag() {
        var arr = []
        for (var i = 0; i < folderModel.count; ++i)
            arr.push(i)
        // Fisher–Yates shuffle.
        for (var j = arr.length - 1; j > 0; --j) {
            var k = Math.floor(Math.random() * (j + 1))
            var tmp = arr[j]; arr[j] = arr[k]; arr[k] = tmp
        }
        // Don't repeat the just-shown photo across a bag boundary.
        if (arr.length > 1 && arr[0] === _lastIdx) {
            arr[0] = arr[1]
            arr[1] = _lastIdx
        }
        _shuffleBag = arr
    }

    function pushNext() {
        if (folderModel.count === 0)
            return
        if (_shuffleBag.length === 0)
            _refillBag()
        var bag = _shuffleBag
        var idx = bag.shift()
        _shuffleBag = bag
        if (idx === undefined || idx >= folderModel.count)
            idx = 0
        _lastIdx = idx
        pile.append({
            "src": folderModel.get(idx, "fileUrl").toString(),
            "tilt": (Math.random() * 2 - 1) * Theme.screensaverTiltMaxDeg,
            "dx": (Math.random() * 2 - 1) * Theme.screensaverScatterPx,
            "dy": (Math.random() * 2 - 1) * Theme.screensaverScatterPx,
            "exiting": false
        })
        // Cap the pile: once it grows past the stack count, fade the oldest photo
        // (bottom of the pile) out and remove it once the fade completes.
        if (pile.count > Theme.screensaverStackCount)
            _retireBottom()
    }

    // Mark the bottom card as leaving (the delegate fades it out via its opacity
    // Behavior), then remove the row after the fade so a new photo replacing an
    // old one dissolves rather than pops.
    function _retireBottom() {
        pile.setProperty(0, "exiting", true)
        retireTimer.restart()
    }

    Timer {
        id: retireTimer
        interval: Theme.screensaverFadeMs
        repeat: false
        onTriggered: {
            while (pile.count > 0 && pile.get(0).exiting)
                pile.remove(0)
        }
    }

    FolderListModel {
        id: folderModel
        folder: App.screensaverDir
        showDirs: false
        sortField: FolderListModel.Name
        nameFilters: ["*.jpg", "*.jpeg", "*.png", "*.bmp", "*.webp", "*.gif"]
    }

    // Advance to the next photo while active; frozen (stopped) otherwise.
    Timer {
        id: advanceTimer
        interval: Theme.screensaverAdvanceMs
        repeat: true
        running: root.active
        onTriggered: root.pushNext()
    }

    // Solid black behind the pile.
    Rectangle {
        anchors.fill: parent
        color: Theme.screensaverBackground
    }

    ListModel { id: pile }

    // The pile of framed photos. A ListModel (not a JS array) keeps existing
    // delegates alive when a new one is appended, so the lower photos stay put —
    // a thrown pile doesn't reshuffle; the new photo just covers them. Only the
    // freshly created (newest) delegate plays the toss-in animation.
    Repeater {
        model: pile

        Item {
            id: card

            required property int index
            required property string src
            required property real tilt
            required property real dx
            required property real dy
            required property bool exiting

            // Photo aspect ratio (w/h), known once the image has loaded.
            property real photoAspect: 1.0

            readonly property real maxW: root.width * Theme.screensaverSizeFraction
            readonly property real maxH: root.height * 0.78
            // Fit the PHOTO inside the max box (minus the matte), preserving aspect;
            // the white frame is that plus the matte border on every side.
            readonly property real photoW: Math.min(maxW - 2 * Theme.screensaverMatte,
                                                    (maxH - 2 * Theme.screensaverMatte) * photoAspect)
            readonly property real photoH: photoW / photoAspect
            readonly property real frameW: photoW + 2 * Theme.screensaverMatte
            readonly property real frameH: photoH + 2 * Theme.screensaverMatte

            width: frameW
            height: frameH
            z: index  // newest appended = highest index = on top

            // Rest at the overlay centre plus this photo's random scatter.
            x: (root.width - frameW) / 2 + dx
            y: (root.height - frameH) / 2 + dy

            transformOrigin: Item.Center
            rotation: tilt

            // Toss-in on create, fade-out when retired. `entered` flips true on
            // creation (only the newest card is newly created) → the Behaviors
            // fade + settle it in; `exiting` is set on the bottom card when the
            // pile is capped → the opacity Behavior fades it out before removal.
            property bool entered: false

            opacity: exiting ? 0.0 : (entered ? 1.0 : 0.0)
            Behavior on opacity {
                NumberAnimation { duration: Theme.screensaverFadeMs; easing.type: Easing.OutCubic }
            }

            scale: entered ? 1.0 : 1.1
            Behavior on scale {
                NumberAnimation { duration: Theme.screensaverEnterMs; easing.type: Easing.OutBack }
            }

            Component.onCompleted: entered = true

            // Floating-print drop shadow behind the frame.
            RectangularShadow {
                anchors.fill: frame
                radius: Theme.screensaverCornerRadius
                blur: 30
                spread: 6
                offset: Qt.vector2d(0, 6)
                color: "#b0000000"
            }

            // White matte frame + the photo inset within it.
            Rectangle {
                id: frame
                anchors.fill: parent
                color: Theme.screensaverFrameColor
                radius: Theme.screensaverCornerRadius

                Image {
                    id: photo
                    anchors.fill: parent
                    anchors.margins: Theme.screensaverMatte
                    source: card.src
                    fillMode: Image.PreserveAspectFit
                    asynchronous: true
                    smooth: true
                    mipmap: true
                    sourceSize.width: card.maxW
                    sourceSize.height: card.maxH
                    onStatusChanged: {
                        if (status === Image.Ready && implicitHeight > 0)
                            card.photoAspect = implicitWidth / implicitHeight
                    }
                }
            }
        }
    }

    // Dismiss: swallow the wake tap (so it doesn't leak to the view beneath),
    // clear the test override, and register activity — Idle.idle drops, `active`
    // goes false, the overlay fades out and the last-used view is revealed.
    MouseArea {
        anchors.fill: parent
        z: 100  // above every photo card
        enabled: root.active
        onPressed: {
            root.forceShow = false
            Idle.poke()
        }
    }

    // Show/hide the screensaver on demand for testing (no need to wait out the
    // timeout). ApplicationShortcut so it fires regardless of item focus.
    Shortcut {
        sequences: ["F10"]
        context: Qt.ApplicationShortcut
        onActivated: root.forceShow = !root.forceShow
    }
}
