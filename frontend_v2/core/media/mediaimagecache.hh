#ifndef FRONTEND_V2_MEDIAIMAGECACHE_HH
#define FRONTEND_V2_MEDIAIMAGECACHE_HH

#include <QHash>
#include <QImage>
#include <QMutex>
#include <QMutexLocker>
#include <QString>

/**
 * MediaImageCache — thread-safe store of the decoded covers MediaData keeps in
 * memory, by content-hash id: the current one, the ones a skip would most likely
 * bring and a few recent ones. MediaData (GUI thread) writes and evicts;
 * MediaImageProvider reads, possibly on a QML image-loader thread, so all access
 * is mutex-guarded. Shared between the two via shared_ptr so neither dangles at
 * shutdown regardless of teardown order.
 */
class MediaImageCache {
public:
    void put(const QString &id, const QImage &image) {
        QMutexLocker lock(&m_mutex);
        m_images.insert(id, image);
    }

    void remove(const QString &id) {
        QMutexLocker lock(&m_mutex);
        m_images.remove(id);
    }

    QImage get(const QString &id) const {
        QMutexLocker lock(&m_mutex);
        return m_images.value(id);
    }

private:
    mutable QMutex m_mutex;
    QHash<QString, QImage> m_images;
};

#endif  // FRONTEND_V2_MEDIAIMAGECACHE_HH
