#ifndef FRONTEND_V2_SCRAM_HH
#define FRONTEND_V2_SCRAM_HH

#include <QByteArray>
#include <QString>

#include <optional>

/**
 * SCRAM-SHA-256-PLUS (RFC 5802 / RFC 7677), the client's half — the mirror of
 * backend/src/auth_service/scram.py; keep the two in step.
 *
 * The display proves it knows the password without sending it, and checks that
 * the backend knows the password's verifier. The channel binding
 * (tls-server-end-point: the SHA-256 of the certificate this side saw) is inside
 * the proof, so a man in the middle presenting its own certificate cannot finish
 * the exchange — which is what makes it safe to pin a certificate never seen
 * before once the login succeeds.
 */
namespace scram {

// Channel binding required, type tls-server-end-point, no authorization identity.
inline constexpr char kGs2Header[] = "p=tls-server-end-point,,";

// The weakest key derivation this side accepts from a server-first-message: a man
// in the middle could otherwise ask for one round and crack the captured proof
// cheaply. The backend asks for 200 000 (scram.ITERATIONS); the cap stops one
// from tying the display's CPU up for minutes.
inline constexpr int kMinIterations = 100'000;
inline constexpr int kMaxIterations = 5'000'000;

/** One login's client side: the first message out, and what checks the rest. */
struct ClientStart {
    QByteArray nonce;
    QByteArray firstBare;  // "n=homedash,r=<nonce>"
    QByteArray first;      // kGs2Header + firstBare
};

/** The client-final-message, and the server-final-message that proves the server. */
struct ClientFinal {
    QByteArray message;
    QByteArray expectedServerFinal;
};

/** A fresh nonce and the client-first-message carrying it. */
ClientStart start();

/**
 * Answers a server-first-message. Runs PBKDF2, so it is slow on purpose (seconds
 * on a Raspberry Pi): call it off the GUI thread. Nothing when the message is
 * malformed, does not extend this side's nonce, or asks for a salt or round count
 * outside the accepted range.
 */
std::optional<ClientFinal> answer(const QString &password, const ClientStart &start,
                                  const QByteArray &serverFirst, const QByteArray &binding);

}  // namespace scram

#endif  // FRONTEND_V2_SCRAM_HH
