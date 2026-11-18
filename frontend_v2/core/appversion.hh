#ifndef FRONTEND_V2_APPVERSION_HH
#define FRONTEND_V2_APPVERSION_HH

#include <QString>

/**
 * appversion — which version of the app this binary is (#56): the release it was
 * built as (scripts/release.sh passes FRONTEND_V2_VERSION), or in a development
 * build the commit it was built from. The display says it at login, and the
 * backend lists it in Ylläpito › Näytöt.
 *
 * Both values are compiled into appversion.cpp alone (CMakeLists.txt says why).
 */
namespace appversion {

/** The release, e.g. "v2.0.0"; empty in a development build. */
QString release();

/** The commit the binary was built from; empty when the build had no git. */
QString commit();

/** What this display calls itself: the release, else the short commit, else "". */
QString label();

}  // namespace appversion

#endif  // FRONTEND_V2_APPVERSION_HH
