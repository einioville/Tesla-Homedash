#ifndef FRONTEND_V2_MEDIAIMAGECACHE_HH
#define FRONTEND_V2_MEDIAIMAGECACHE_HH

#include <QImage>
#include <QMutex>
#include <QMutexLocker>
#include <QString>

/**
 * MediaImageCache — thread-safe single-slot store for the latest decoded cover
 * art. MediaData (GUI thread) writes the decoded QImage after an off-thread
 * decode; MediaImageProvider reads it (possibly on a QML image-loader thread),
 * so all access is mutex-guarded. Shared between the two via shared_ptr so
 * neither dangles at shutdown regardless of teardown order.
 */
class MediaImageCache {
public:
    void put(const QString &id, const QImage &image) {
        QMutexLocker lock(&m_mutex);
        m_id = id;
        m_image = image;
    }

    QImage get(const QString &id) const {
        QMutexLocker lock(&m_mutex);
        return (id == m_id) ? m_image : QImage();
    }

private:
    mutable QMutex m_mutex;
    QString m_id;
    QImage m_image;
};

#endif  // FRONTEND_V2_MEDIAIMAGECACHE_HH
