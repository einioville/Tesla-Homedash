.pragma library

// Value formatting shared by the stat and status cards. A missing value
// (undefined, null or NaN) reads "—" everywhere.

function has(v) {
    return v !== undefined && v !== null && !isNaN(v)
}

// `v` to `dec` decimals, with the unit after a space when one is given.
function num(v, unit, dec) {
    return has(v) ? v.toFixed(dec) + (unit ? " " + unit : "") : "—"
}

// Bytes in steps of 1024, named B / kB / MB / GB / TB: "512 B", "12.3 MB".
function bytes(v) {
    if (!has(v))
        return "—"
    const units = ["B", "kB", "MB", "GB", "TB"]
    let i = 0
    while (v >= 1024 && i < units.length - 1) {
        v /= 1024
        ++i
    }
    return (i === 0 ? v.toFixed(0) : v.toFixed(1)) + " " + units[i]
}

// A span of seconds as its two largest units: "2 pv 3 h", "3 h 12 min", "12 min".
function duration(seconds) {
    if (!has(seconds))
        return "—"
    const s = Math.floor(seconds)
    const d = Math.floor(s / 86400)
    const h = Math.floor((s % 86400) / 3600)
    const m = Math.floor((s % 3600) / 60)
    if (d > 0)
        return d + " pv " + h + " h"
    if (h > 0)
        return h + " h " + m + " min"
    return m + " min"
}

// An epoch-ms moment: today as a clock time ("klo 14:02"), earlier this year with
// its date ("3.10. 14:02"), older with the year ("3.10.2025") — a time without its
// day means nothing on a panel left on for days.
function moment(ms) {
    if (!has(ms))
        return "—"
    const date = new Date(ms)
    const today = new Date()
    if (date.toDateString() === today.toDateString())
        return "klo " + Qt.formatTime(date, "hh:mm")
    if (date.getFullYear() === today.getFullYear())
        return Qt.formatDateTime(date, "d.M. hh:mm")
    return Qt.formatDate(date, "d.M.yyyy")
}
