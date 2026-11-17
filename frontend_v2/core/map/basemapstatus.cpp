#include "basemapstatus.hh"

#include "../logger.hh"

#include <QFile>
#include <QJsonDocument>
#include <QJsonObject>
#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QUrlQuery>

namespace {
const Logger logger = Logger::get("map");

// The EOX type's provider file, the one BasemapPlugin's maps read.
const char *const kEoxProvider = ":/config/map-providers/satellite";
const char *const kUserAgent = "Tesla-Homedash/1.0";

constexpr int kUpIntervalMs = 2 * 60 * 1000;
constexpr int kConfirmIntervalMs = 20 * 1000;
constexpr int kDownIntervalMs = 60 * 1000;
constexpr int kTimeoutMs = 10 * 1000;
constexpr int kFailuresToFallBack = 3;
constexpr int kSuccessesToReturn = 3;

// The zoom-0 tile of a %z/%y/%x template: the smallest request either server answers.
QUrl tileZero(QString tmpl) {
    tmpl.replace(QLatin1String("%z"), QLatin1String("0"))
        .replace(QLatin1String("%y"), QLatin1String("0"))
        .replace(QLatin1String("%x"), QLatin1String("0"));
    return QUrl(tmpl);
}
}  // namespace

BasemapStatus::BasemapStatus(const QString &mmlTilesUrl, QObject *parent)
    : QObject(parent), m_network(new QNetworkAccessManager(this)) {
    if (mmlTilesUrl.isEmpty())
        return;
    m_mml = tileZero(mmlTilesUrl);
    m_mmlKey = QUrlQuery(m_mml).queryItemValue(QStringLiteral("api-key"));

    QFile provider(QString::fromLatin1(kEoxProvider));
    if (provider.open(QIODevice::ReadOnly)) {
        m_eox = tileZero(QJsonDocument::fromJson(provider.readAll())
                             .object()
                             .value(QStringLiteral("UrlTemplate"))
                             .toString());
    }
    if (!m_eox.isValid())
        logger.warning(QStringLiteral("No EOX tile URL in %1; an MML outage cannot be told from "
                                      "this display being offline")
                           .arg(QString::fromLatin1(kEoxProvider)));

    m_next.setSingleShot(true);
    connect(&m_next, &QTimer::timeout, this, &BasemapStatus::probeMml);
    m_next.start(0);
}

QNetworkReply *BasemapStatus::get(const QUrl &url) {
    QNetworkRequest request(url);
    request.setHeader(QNetworkRequest::UserAgentHeader, QString::fromLatin1(kUserAgent));
    request.setTransferTimeout(kTimeoutMs);
    return m_network->get(request);
}

BasemapStatus::Answer BasemapStatus::answerOf(QNetworkReply *reply, QString *reason) const {
    const int status = reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
    if (status == 0) {
        // Qt's error text can quote the URL, and MML's carries the key.
        QString text = reply->errorString();
        if (!m_mmlKey.isEmpty())
            text.replace(m_mmlKey, QStringLiteral("…"));
        *reason = text;
        return Answer::None;
    }
    const QString type = reply->header(QNetworkRequest::ContentTypeHeader).toString();
    if (status == 200 && type.startsWith(QLatin1String("image/")))
        return Answer::Image;
    *reason = status == 200 ? QStringLiteral("HTTP 200 with %1, not an image").arg(type)
                            : QStringLiteral("HTTP %1").arg(status);
    return Answer::NotImage;
}

void BasemapStatus::probeMml() {
    QNetworkReply *reply = get(m_mml);
    connect(reply, &QNetworkReply::finished, this, [this, reply]() {
        reply->deleteLater();
        QString reason;
        switch (answerOf(reply, &reason)) {
        case Answer::Image:
            settle(true, QString());
            break;
        case Answer::NotImage:
            settle(false, reason);
            break;
        case Answer::None:
            if (m_eox.isValid())
                probeEox(reason);
            else
                settle(false, reason);
            break;
        }
    });
}

void BasemapStatus::probeEox(const QString &mmlReason) {
    QNetworkReply *reply = get(m_eox);
    connect(reply, &QNetworkReply::finished, this, [this, reply, mmlReason]() {
        reply->deleteLater();
        QString eoxReason;
        if (answerOf(reply, &eoxReason) == Answer::None) {
            if (!m_offlineLogged) {
                m_offlineLogged = true;
                logger.info(QStringLiteral("Map tiles: neither MML (%1) nor EOX (%2) answers; the "
                                           "display looks offline, so the maps keep their imagery")
                                .arg(mmlReason, eoxReason));
            }
            scheduleNext();
            return;
        }
        settle(false, mmlReason);
    });
}

void BasemapStatus::settle(bool mmlUp, const QString &reason) {
    m_offlineLogged = false;
    if (!mmlUp)
        logger.debug(QStringLiteral("MML tile probe failed: %1").arg(reason));
    if (mmlUp == m_reachable) {
        m_streak = 0;
    } else if (++m_streak >= (m_reachable ? kFailuresToFallBack : kSuccessesToReturn)) {
        m_streak = 0;
        m_reachable = mmlUp;
        if (m_reachable)
            logger.info(QStringLiteral("MML's tile service answers again; the maps show its "
                                       "imagery"));
        else
            logger.warning(QStringLiteral("MML's tile service does not answer (%1); the maps show "
                                          "EOX's imagery until it is back")
                               .arg(reason));
        emit mmlReachableChanged();
    }
    scheduleNext();
}

void BasemapStatus::scheduleNext() {
    if (!m_reachable)
        m_next.start(kDownIntervalMs);
    else
        m_next.start(m_streak > 0 ? kConfirmIntervalMs : kUpIntervalMs);
}
