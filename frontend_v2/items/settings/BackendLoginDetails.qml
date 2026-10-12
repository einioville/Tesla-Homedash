import QtQuick
import frontend_v2

// Details of Ylläpito › Yhteydet's "Kirjautuminen" row: whether this display is
// logged in to the backend, and why not when it is not (issue #64).
SettingDetails {
    level: {
        switch (Server.authState) {
        case "authenticated": return "ok"
        case "authenticating": return "warn"
        case "loginRequired":
        case "noPassword": return "error"
        default: return "unknown"
        }
    }

    statusText: {
        switch (Server.authState) {
        case "authenticated": return qsTr("Kirjautunut · salattu yhteys")
        case "authenticating": return qsTr("Kirjaudutaan…")
        case "loginRequired":
            return Server.authMessage.length > 0
                   ? Server.authMessage : qsTr("Kirjautuminen vaaditaan")
        case "noPassword": return qsTr("Palvelimelle ei ole asetettu salasanaa")
        default: return qsTr("Ei yhteyttä palvelimeen")
        }
    }
}
