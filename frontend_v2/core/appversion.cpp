#include "appversion.hh"

namespace appversion {

QString release() {
#ifdef FRONTEND_V2_VERSION
    return QStringLiteral(FRONTEND_V2_VERSION);
#else
    return {};
#endif
}

QString commit() {
#ifdef FRONTEND_V2_BUILD_COMMIT
    return QStringLiteral(FRONTEND_V2_BUILD_COMMIT);
#else
    return {};
#endif
}

QString label() {
    const QString name = release();
    return name.isEmpty() ? commit().left(7) : name;
}

}  // namespace appversion
