#ifndef FRONTEND_V2_USBIMPORT_HH
#define FRONTEND_V2_USBIMPORT_HH

#include <QByteArray>
#include <QJsonObject>
#include <QObject>
#include <QString>
#include <QVariantList>
#include <QVariantMap>

class ServerClient;

/**
 * UsbImport — drives the Options view's screensaver photo import from a USB stick
 * (the "Tuo USB:ltä" button on the Kuvakansio row).
 *
 * The BACKEND does every step (usb_import_service): it lists the USB drives,
 * mounts the chosen one, counts the images in its tesla_homedash_screensaver
 * folder and copies them into the screensaver folder. This side sends the user's
 * choices and renders the one state document the backend sends back.
 *
 * `phase` is the backend's, as a plain string QML can switch on:
 *   "idle"     no dialog
 *   "listing"  looking for drives
 *   "drives"   `drives` lists them (possibly none)
 *   "scanning" mounting the chosen one and counting its photos
 *   "ready"    `found` / `count` / `bytes` describe what can be imported
 *   "copying"  `copied` + `skipped` of `total` done
 *   "done"     finished (or stopped); `unmounted` = safe to pull the stick
 *   "error"    see `message`
 *
 * Registered with the QML engine as the singleton `UsbImport` (see main.cpp).
 */
class UsbImport : public QObject {
    Q_OBJECT
    Q_PROPERTY(QString phase READ phase NOTIFY stateChanged)
    Q_PROPERTY(QString message READ message NOTIFY stateChanged)
    // [{device, label, size, fstype, model, mountpoint}]
    Q_PROPERTY(QVariantList drives READ drives NOTIFY stateChanged)
    // The drive being scanned or imported from, same shape; empty before a scan.
    Q_PROPERTY(QVariantMap device READ device NOTIFY stateChanged)
    Q_PROPERTY(bool found READ found NOTIFY stateChanged)
    Q_PROPERTY(int count READ count NOTIFY stateChanged)
    // double, not qint64: QML numbers are doubles anyway, and a byte count is
    // exact in one far beyond any stick.
    Q_PROPERTY(double bytes READ bytes NOTIFY stateChanged)
    Q_PROPERTY(int copied READ copied NOTIFY stateChanged)
    Q_PROPERTY(int skipped READ skipped NOTIFY stateChanged)
    Q_PROPERTY(int total READ total NOTIFY stateChanged)
    Q_PROPERTY(bool unmounted READ unmounted NOTIFY stateChanged)

public:
    explicit UsbImport(QObject *parent = nullptr);

    QString phase() const { return m_phase; }
    QString message() const { return m_message; }
    QVariantList drives() const { return m_state.value(QStringLiteral("drives")).toList(); }
    QVariantMap device() const { return m_state.value(QStringLiteral("device")).toMap(); }
    bool found() const { return m_state.value(QStringLiteral("found")).toBool(); }
    int count() const { return m_state.value(QStringLiteral("count")).toInt(); }
    double bytes() const { return m_state.value(QStringLiteral("bytes")).toDouble(); }
    int copied() const { return m_state.value(QStringLiteral("copied")).toInt(); }
    int skipped() const { return m_state.value(QStringLiteral("skipped")).toInt(); }
    int total() const { return m_state.value(QStringLiteral("total")).toInt(); }
    bool unmounted() const { return m_state.value(QStringLiteral("unmounted")).toBool(); }

    void attachServer(ServerClient *client);

    // Opens the dialog and lists the drives.
    Q_INVOKABLE void begin();
    // Lists the drives again, in the same flow (the "Päivitä" / "Takaisin" buttons).
    Q_INVOKABLE void listDrives();
    // Mounts `device` (a `drives` entry's device path) and counts its photos.
    Q_INVOKABLE void scan(const QString &device);
    // Copies the scanned photos.
    Q_INVOKABLE void start();
    // Closes the dialog. A copy stops after the current file and the backend
    // unmounts whatever it mounted.
    Q_INVOKABLE void close();

signals:
    void stateChanged();

private:
    void onPacket(quint8 type, const QByteArray &payload);
    // The flow lives on the backend's side of the socket; losing it ends the
    // flow here, or the dialog would wait on a reply that can never come.
    void onConnectionChanged();
    void send(quint8 type, const QJsonObject &fields = QJsonObject());
    void setLocal(const QString &phase, const QString &message = QString());

    ServerClient *m_server = nullptr;
    QString m_phase = QStringLiteral("idle");
    QString m_message;
    QVariantMap m_state;
    // Flow epoch, generated here because this side knows when a dialog opened.
    // Sent in every request and echoed in every USB_IMPORT_STATE; a state with
    // any other value belongs to a dialog that was closed and is dropped.
    // Incremented before the first flow, so 0 — what a missing field reads as —
    // never matches a live one.
    quint32 m_flowId = 0;
};

#endif  // FRONTEND_V2_USBIMPORT_HH
