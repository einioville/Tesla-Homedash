// PROTOTYPE — formatting + colour helpers for the Weather view.
.pragma library

var WEEKDAYS_LONG = { ma: "maanantai", ti: "tiistai", ke: "keskiviikko", to: "torstai",
                      pe: "perjantai", la: "lauantai", su: "sunnuntai" }

// FMI SmartSymbol (night = value + 100), icons in resources/icons/weather/smartsymbol.
function icon(code) {
    return code ? "qrc:/resources/icons/weather/smartsymbol/" + code + ".svg" : ""
}

function temp(t) {
    if (t === null || t === undefined)
        return "–"
    var r = Math.round(t)
    return (r === 0 ? 0 : r) + "°"
}

// Finnish decimal comma.
function num(v, decimals) {
    if (v === null || v === undefined)
        return "–"
    return Number(v).toFixed(decimals === undefined ? 1 : decimals).replace(".", ",")
}

function capitalize(s) {
    return s ? s.charAt(0).toUpperCase() + s.slice(1) : ""
}

function dayLength(min) {
    return Math.floor(min / 60) + " h " + (min % 60) + " min"
}

function signed(v, decimals) {
    if (v === null || v === undefined)
        return "–"
    return (v > 0 ? "+" : v < 0 ? "-" : "±") + num(Math.abs(v), decimals)
}

function visibility(m) {
    if (m === null || m === undefined)
        return "–"
    return m >= 1000 ? Math.round(m / 1000) + " km" : Math.round(m / 50) * 50 + " m"
}

function cloudText(oktas) {
    if (oktas === null || oktas === undefined || oktas > 8)
        return "–"
    return ["selkeää", "melkein selkeää", "melkein selkeää", "puolipilvistä", "puolipilvistä",
            "puolipilvistä", "melkein pilvistä", "melkein pilvistä", "pilvistä"][Math.round(oktas)]
}

function warnColor(c) {
    return ({ yellow: "#f5c518", orange: "#ff8c1a", red: "#e53935" })[c] || "#f5c518"
}

// A blue → teal → yellow → orange → red ramp over temperature, for range bars.
function tempColor(t) {
    var stops = [[-20, [70, 110, 255]], [-5, [90, 180, 255]], [5, [80, 210, 190]],
                 [12, [240, 210, 70]], [20, [255, 150, 50]], [30, [235, 70, 60]]]
    if (t <= stops[0][0]) return rgb(stops[0][1])
    for (var i = 1; i < stops.length; i++) {
        if (t <= stops[i][0]) {
            var a = stops[i - 1], b = stops[i]
            var f = (t - a[0]) / (b[0] - a[0])
            return rgb([0, 1, 2].map(function (k) { return a[1][k] + f * (b[1][k] - a[1][k]) }))
        }
    }
    return rgb(stops[stops.length - 1][1])
}

function rgb(c) {
    return "#" + c.map(function (v) {
        var h = Math.round(v).toString(16)
        return h.length < 2 ? "0" + h : h
    }).join("")
}

function hour2(h) {
    return (h < 10 ? "0" : "") + h
}
