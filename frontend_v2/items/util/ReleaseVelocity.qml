import QtQuick

// The speed a drag is let go at, measured over only the last `window` ms of its
// movement: a finger (or mouse) that stops before lifting is let go at rest.
// A speed kept from the last move event would still read as a flick after a
// pause, and move events arrive in bursts — a 1 ms gap between two of them is a
// spike of thousands of px/s.
QtObject {
    property int window: 100

    property var samples: []

    // `position`: along the drag's axis, px.
    function start(position) {
        samples = [{ position: position, time: Date.now() }]
    }

    function move(position) {
        const now = Date.now()
        samples.push({ position: position, time: now })
        while (samples.length > 1 && now - samples[0].time > window)
            samples.shift()
    }

    // px/s at release at `position`; 0 when the drag was still for `window` ms.
    function release(position) {
        const now = Date.now()
        const first = samples.find(s => now - s.time <= window)
        if (first === undefined || now - first.time < 16)
            return 0
        return (position - first.position) / (now - first.time) * 1000
    }
}
