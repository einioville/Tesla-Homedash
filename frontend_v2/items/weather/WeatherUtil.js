// Formatting and colour helpers for the Weather view.
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

function visibility(m) {
    if (m === null || m === undefined)
        return "–"
    return m >= 1000 ? Math.round(m / 1000) + " km" : Math.round(m / 50) * 50 + " m"
}

function warnColor(c) {
    return ({ yellow: "#f5c518", orange: "#ff8c1a", red: "#e53935" })[c] || "#f5c518"
}

// A warning's level and kind, its headline before the region ("Keltainen liikennesää").
function warnTitle(w) {
    var h = w.headline || ""
    var i = h.indexOf(":")
    return i > 0 ? h.slice(0, i) : (h || w.event || "")
}

// When a warning is in force, "su 2.00–9.00": the day said once if it does not change.
// onset and expires come as "<weekday> <h.mm>".
function warnWhen(w) {
    if (!w.onset || !w.expires)
        return w.onset ? w.onset + " alkaen" : (w.expires ? w.expires + " asti" : "")
    var a = w.onset.split(" "), b = w.expires.split(" ")
    return a[0] === b[0] ? w.onset + "–" + b[1] : w.onset + " – " + w.expires
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

// An ISO time's clock time laid on `now`'s date. The document holds the day it was fetched
// on, so for the minutes after midnight, until the next refresh, the new day reuses the old
// day's sunrise and sunset.
function todayAt(iso, now) {
    var t = new Date(iso)
    var d = new Date(now.getTime())
    d.setHours(t.getHours(), t.getMinutes(), 0, 0)
    return d.getTime()
}

// 1 by day, 0 by night, ramping over half an hour either side of sunrise and sunset.
function dayness(now, astro) {
    if (!astro || !astro.sunriseIso)
        return 1
    var ramp = 30 * 60000
    var t = now.getTime()
    var up = (t - todayAt(astro.sunriseIso, now) + ramp) / (2 * ramp)
    var down = (todayAt(astro.sunsetIso, now) + ramp - t) / (2 * ramp)
    return Math.max(0, Math.min(1, up, down))
}

// The kind of weather a SmartSymbol shows (night = value + 100), per FMI's mapping guide in
// github.com/fmidev/opendata-resources/symbols/SmartSymbol.
function skyKind(symbol) {
    var c = symbol % 100
    if (c === 1 || c === 2) return "clear"
    if (c === 4) return "partly"
    if (c === 6 || c === 7) return "cloudy"
    if (c === 9) return "fog"
    if (c >= 71) return "thunder"
    if (c >= 51 && c < 60) return "snow"
    if (c === 14 || c === 17 || (c >= 41 && c < 50) || c >= 61) return "sleet"
    if (c >= 11) return "rain"
    return "cloudy"
}

// Backdrop gradient [top, bottom] per kind, by day and by night. All dark, so the cards and
// text read the same over every one; night is near-black with just the hue left.
var SKY = {
    clear:   { day: ["#12304a", "#0c1620"], night: ["#0a1024", "#05070d"] },
    partly:  { day: ["#172a3c", "#0c141c"], night: ["#0d1220", "#06080d"] },
    cloudy:  { day: ["#1e252c", "#0e1114"], night: ["#111418", "#08090b"] },
    fog:     { day: ["#272b2f", "#121416"], night: ["#15171a", "#0a0b0c"] },
    rain:    { day: ["#132431", "#0a1016"], night: ["#0c131a", "#06090c"] },
    sleet:   { day: ["#192b32", "#0c1317"], night: ["#0e161a", "#070a0c"] },
    snow:    { day: ["#25313d", "#10161c"], night: ["#141a22", "#090c10"] },
    thunder: { day: ["#231a37", "#0d0b14"], night: ["#160f24", "#08060c"] }
}

function skyColors(symbol, dayness) {
    var s = SKY[skyKind(symbol || 7)]
    return [mix(s.night[0], s.day[0], dayness), mix(s.night[1], s.day[1], dayness)]
}

function mix(a, b, f) {
    var ca = [1, 3, 5].map(function (i) { return parseInt(a.substr(i, 2), 16) })
    var cb = [1, 3, 5].map(function (i) { return parseInt(b.substr(i, 2), 16) })
    return rgb([0, 1, 2].map(function (k) { return ca[k] + f * (cb[k] - ca[k]) }))
}
