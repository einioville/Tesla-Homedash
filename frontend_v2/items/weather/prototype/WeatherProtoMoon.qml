import QtQuick

// PROTOTYPE — the moon's lit fraction drawn as a disc (illuminated % from FMI's moonphase).
Canvas {
    id: moon

    property real illuminated: 0      // 0..100
    property bool waxing: true

    onIlluminatedChanged: requestPaint()
    onWaxingChanged: requestPaint()

    onPaint: {
        var ctx = getContext("2d")
        ctx.reset()
        var r = Math.min(width, height) / 2 - 1
        var cx = width / 2, cy = height / 2
        ctx.fillStyle = "#2a2f38"
        ctx.beginPath()
        ctx.arc(cx, cy, r, 0, Math.PI * 2)
        ctx.fill()

        var p = Math.max(0, Math.min(1, illuminated / 100))
        if (!waxing) {
            ctx.translate(2 * cx, 0)
            ctx.scale(-1, 1)
        }
        // Lit part: right limb from top to bottom, then the terminator back up. The
        // terminator is a half ellipse whose bulge k runs from +r (new) to -r (full).
        var k = r * (1 - 2 * p), q = 0.5523
        ctx.fillStyle = "#f3eccf"
        ctx.beginPath()
        ctx.moveTo(cx, cy - r)
        ctx.arc(cx, cy, r, -Math.PI / 2, Math.PI / 2, false)
        ctx.bezierCurveTo(cx + k * q, cy + r, cx + k, cy + r * q, cx + k, cy)
        ctx.bezierCurveTo(cx + k, cy - r * q, cx + k * q, cy - r, cx, cy - r)
        ctx.fill()
    }
}
