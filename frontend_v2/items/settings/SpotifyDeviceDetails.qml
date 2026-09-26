import QtQuick
import frontend_v2

// Details of the "Tunnista laite" row: which Connect device config.json names,
// and whether Spotify can see it right now.
//
// Spotify lists only devices that are up and signed in, so "not detected" means
// switched off OR a wrong id — the two look identical from the backend, which is
// why that case is amber and says both. Grey means the backend could not look at
// all (no working grant, Spotify not answering), which is not a verdict on the
// device.
SettingDetails {
    id: device

    readonly property var status: SpotifyDevice.configuredStatus
    readonly property bool loaded: status.configured !== undefined

    // A grant that starts or stops working changes what the backend can see.
    readonly property bool authorized: SpotifyAuth.authorized
    onAuthorizedChanged: SpotifyDevice.refreshStatus(true)
    // Throttled in C++: this row is rebuilt on every settings write.
    Component.onCompleted: SpotifyDevice.refreshStatus()

    level: {
        if (!loaded || !status.configured)
            return loaded ? "error" : "unknown"
        if (status.detected === true)
            return status.isRestricted ? "warn" : "ok"
        return status.detected === false ? "warn" : "unknown"
    }

    statusText: {
        if (!loaded)
            return Server.connected ? qsTr("Tarkistetaan…") : qsTr("Ei yhteyttä palvelimeen")
        if (!status.configured)
            return qsTr("Laitetta ei ole valittu")
        if (status.detected === true)
            return status.isRestricted
                   ? qsTr("Tunnistettu, mutta laite ei salli etäohjausta")
                   : qsTr("Tunnistettu ja tavoitettavissa")
        if (status.detected === false)
            return qsTr("Ei näy Spotifyssa — sammuksissa tai väärä laite")
        return status.reason.length > 0
               ? qsTr("Tilaa ei voitu tarkistaa · %1").arg(status.reason)
               : qsTr("Tilaa ei voitu tarkistaa")
    }

    rows: !loaded || !status.configured ? [] : [
        { label: qsTr("Laite"),
          value: status.name.length === 0 ? qsTr("Ei tiedossa")
               : status.type.length > 0 ? qsTr("%1 (%2)").arg(status.name).arg(status.type)
                                        : status.name },
        { label: qsTr("Tunnus"), value: status.id }
    ]
}
