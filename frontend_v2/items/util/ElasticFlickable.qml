import QtQuick
import frontend_v2

// A vertical Flickable with soft ends: content can be dragged past the top or
// bottom (Qt moves it half the finger's distance there, so it pulls with
// resistance), a fast flick overshoots the end, and on release it springs back
// to the limit. Use it for any scrolling content in place of a bare Flickable,
// so every list in the app has the same edges.
//
// VerticalFlick, not the default AutoFlickDirection, so a section shorter than
// the view still gives under the finger instead of feeling dead — and a stray
// sideways drag never moves it horizontally.
Flickable {
    flickableDirection: Flickable.VerticalFlick
    boundsBehavior: Flickable.DragAndOvershootBounds
    boundsMovement: Flickable.FollowBoundsBehavior

    rebound: Transition {
        NumberAnimation {
            properties: "x,y"
            duration: Theme.reboundDuration
            easing.type: Easing.OutCubic
        }
    }
}
