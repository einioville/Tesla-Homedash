import QtQuick
import frontend_v2

// Details of the "Tunnistaudu uudelleen" row: whose grant it is, whether it
// works, when it was made and when it runs out.
//
// The dates come from the backend's grant record, written at each exchange this
// app makes — Spotify reports neither — so a grant made before the record existed
// reads "ei tiedossa" (and amber) until the next re-authorization records one.
// The e-mail needs the user-read-email scope, which only grants issued since it
// was added carry; the display name stands in until then.
SettingDetails {
    id: auth

    // Re-read hourly: the amber "expires within a month" must arrive on a panel
    // that has sat on this view for days, not only when the row is rebuilt.
    property double now: Date.now()

    readonly property bool hasDates: SpotifyAuth.validUntil > 0
    readonly property int daysLeft: hasDates
                                    ? Math.floor((SpotifyAuth.validUntil - now) / 86400000) : 0
    readonly property string account: SpotifyAuth.email.length > 0 ? SpotifyAuth.email
                                                                   : SpotifyAuth.displayName
    readonly property bool hasRecord: hasDates || account.length > 0

    // Red only when the backend says the grant does not work. A record past its
    // (deliberately conservative) 180 days on a grant Spotify still accepts is
    // amber: invalid is what the player experiences, not what the estimate says.
    level: !SpotifyAuth.authorized ? "error"
         : (!hasDates || daysLeft <= 30) ? "warn" : "ok"

    statusText: {
        if (!SpotifyAuth.authorized)
            return SpotifyAuth.reason.length > 0
                   ? qsTr("Ei voimassa · %1").arg(SpotifyAuth.reason) : qsTr("Ei voimassa")
        if (!hasDates)
            return qsTr("Voimassa · päättymispäivä ei tiedossa")
        if (daysLeft <= 0)
            return qsTr("Vanhenee pian — tunnistaudu uudelleen")
        if (daysLeft <= 30)
            return qsTr("Vanhenee %1 päivän kuluttua").arg(daysLeft)
        return qsTr("Voimassa")
    }

    // Nothing to list for a grant that is gone and was never recorded; a working
    // grant lists its rows even when unknown, since "ei tiedossa" is itself the
    // prompt to re-authorize.
    rows: !SpotifyAuth.authorized && !hasRecord ? [] : [
        { label: qsTr("Käyttäjä"),
          value: account.length > 0 ? account : qsTr("Ei tiedossa") },
        { label: qsTr("Tunnistettu"),
          value: hasDates ? Qt.formatDate(new Date(SpotifyAuth.authorizedAt), "d.M.yyyy")
                          : qsTr("Ei tiedossa") },
        { label: qsTr("Voimassa asti"),
          value: hasDates ? Qt.formatDate(new Date(SpotifyAuth.validUntil), "d.M.yyyy")
                          : qsTr("Ei tiedossa") }
    ]

    Timer {
        interval: 3600000
        running: true
        repeat: true
        onTriggered: auth.now = Date.now()
    }
}
