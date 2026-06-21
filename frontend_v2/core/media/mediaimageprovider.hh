#ifndef FRONTEND_V2_MEDIAIMAGEPROVIDER_HH
#define FRONTEND_V2_MEDIAIMAGEPROVIDER_HH

#include <QQuickImageProvider>
#include <memory>

#include "mediaimagecache.hh"

/**
 * MediaImageProvider — serves decoded cover art to QML via image://media/<id>.
 * Reads from a shared MediaImageCache; QML re-requests whenever
 * MediaData.coverArtId changes (the id is the image content hash, so the QML
 * Image URL cache keys on the actual art). Owned by the QQmlEngine
 * (engine.addImageProvider).
 */
class MediaImageProvider : public QQuickImageProvider {
public:
    explicit MediaImageProvider(std::shared_ptr<MediaImageCache> cache)
        : QQuickImageProvider(QQuickImageProvider::Image), m_cache(std::move(cache)) {}

    QImage requestImage(const QString &id, QSize *size, const QSize &requestedSize) override {
        Q_UNUSED(requestedSize);
        const QImage image = m_cache->get(id);
        if (size) {
            *size = image.size();
        }
        return image;
    }

private:
    std::shared_ptr<MediaImageCache> m_cache;
};

#endif  // FRONTEND_V2_MEDIAIMAGEPROVIDER_HH
