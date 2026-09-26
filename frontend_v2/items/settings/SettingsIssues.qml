import QtQuick
import frontend_v2

// Problems the Options view can detect and point at a fix for. `issues` is a
// plain binding over the singletons, so an issue appears and clears by itself
// the moment its cause does; nothing is polled here except the clock.
//
// Each issue: {id, level ("error" | "warn"), title, detail, key, section}. `key`
// names the setting row that is the fix and `section` the group holding it, looked
// up in Settings.groups rather than hardcoded — "" when that row is not in the
// schema right now (its half is absent), in which case no "Korjaa" is offered.
//
// While the backend is unreachable only that is reported: every other check
// reads state the backend supplies, which is stale until it is back.
QtObject {
    id: detector

    // Re-read hourly so "expires within a month" arrives on a panel that stays
    // on this view for days.
    property double now: Date.now()

    readonly property var issues: {
        const list = detector.detect()
        for (const issue of list)
            issue.section = detector.sectionOf(issue.key)
        return list
    }

    readonly property bool hasErrors: issues.some(issue => issue.level === "error")

    // The id of the group whose subsections hold `key`, or "". Reads
    // Settings.groups, so the `issues` binding follows the schema too.
    function sectionOf(key) {
        for (const group of Settings.groups) {
            for (const section of group.sections || []) {
                for (const setting of section.settings || []) {
                    if (setting.key === key)
                        return group.id
                }
            }
        }
        return ""
    }

    function detect() {
        const list = []
        if (!Server.connected) {
            list.push({
                id: "backend",
                level: "error",
                title: qsTr("Ei yhteyttä palvelimeen"),
                detail: Server.stateText.length > 0
                        ? qsTr("%1 · tarkista palvelimen osoite").arg(Server.stateText)
                        : qsTr("Tarkista palvelimen osoite"),
                key: "backendHost"
            })
            return list
        }

        if (SpotifyAuth.needsReauth) {
            list.push({
                id: "spotifyAuth",
                level: "error",
                title: qsTr("Spotify-tunnistautuminen ei ole voimassa"),
                detail: SpotifyAuth.reason,
                key: "spotifyReauth"
            })
        } else if (SpotifyAuth.authorized && SpotifyAuth.validUntil > 0) {
            const days = Math.floor((SpotifyAuth.validUntil - detector.now) / 86400000)
            if (days <= 30) {
                list.push({
                    id: "spotifyAuthExpiring",
                    level: "warn",
                    title: qsTr("Spotify-tunnistautuminen vanhenee pian"),
                    detail: qsTr("Voimassa %1 asti")
                            .arg(Qt.formatDate(new Date(SpotifyAuth.validUntil), "d.M.yyyy")),
                    key: "spotifyReauth"
                })
            }
        }

        // Only with a working grant: without one the backend cannot look, and the
        // grant is already the reported problem.
        const device = SpotifyDevice.configuredStatus
        if (SpotifyAuth.authorized && device.configured !== undefined) {
            if (!device.configured) {
                list.push({
                    id: "spotifyDevice",
                    level: "error",
                    title: qsTr("Spotify-laitetta ei ole valittu"),
                    detail: qsTr("Soittimen painikkeet eivät ohjaa Spotifyta"),
                    key: "spotifyIdentifyDevice"
                })
            } else if (device.detected === false) {
                list.push({
                    id: "spotifyDeviceMissing",
                    level: "warn",
                    title: qsTr("Spotify-laite ei näy Spotifyssa"),
                    detail: qsTr("%1 on sammuksissa tai valittu laite on väärä")
                            .arg(device.name.length > 0 ? device.name : qsTr("Laite")),
                    key: "spotifyIdentifyDevice"
                })
            }
        }

        // valuesRevision makes these invokable reads live (see Settings.valueOf).
        const revision = Settings.valuesRevision
        if (Settings.valueOf("screensaverEnabled") === true
                && String(Settings.valueOf("screensaverDir") || "").length === 0) {
            list.push({
                id: "screensaverDir",
                level: "warn",
                title: qsTr("Näytönsäästäjällä ei ole kuvakansiota"),
                detail: qsTr("Näytönsäästäjä ei käynnisty ilman kansiota"),
                key: "screensaverDir"
            })
        }
        return list
    }

    property Timer clock: Timer {
        interval: 3600000
        running: true
        repeat: true
        onTriggered: detector.now = Date.now()
    }
}
