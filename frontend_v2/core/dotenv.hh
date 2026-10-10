#ifndef FRONTEND_V2_DOTENV_HH
#define FRONTEND_V2_DOTENV_HH

#include <QString>

/**
 * dotenv — shared access to the repo-root `.env` the frontend borrows from the
 * backend, with real environment variables taking precedence.
 *
 * Extracted from AppConfig because Settings needs the same lookup: a local
 * setting may declare an `"env"` key in its schema, making the environment
 * supply that setting's DEFAULT (so an existing deployment's .env keeps working
 * until the user overrides it in the Options view). Both readers must agree on
 * where .env is and how it parses, so the logic lives in one place.
 *
 * The file is located and parsed lazily on first use and cached for the process
 * lifetime — it is read at startup and never changes underneath a running app.
 */
namespace dotenv {

/**
 * Returns the value for `key`: the real environment variable if set and
 * non-empty, then the repo-root .env entry if non-empty, then `fallback`.
 * An empty placeholder line in .env therefore reads as "unset".
 */
QString valueOr(const char *key, const QString &fallback = QString());

/** True when `key` has a non-empty value from either source. */
bool isSet(const char *key);

/** Absolute path of the .env that was loaded, or empty if none was found. */
QString sourcePath();

}  // namespace dotenv

#endif  // FRONTEND_V2_DOTENV_HH
