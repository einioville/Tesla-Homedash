#include "scram.hh"

#include <QCryptographicHash>
#include <QList>
#include <QMessageAuthenticationCode>
#include <QPasswordDigestor>
#include <QRandomGenerator>

namespace scram {

namespace {

QByteArray hmac(const QByteArray &key, const QByteArray &message) {
    return QMessageAuthenticationCode::hash(message, key, QCryptographicHash::Sha256);
}

// "a=1,b=2" -> the value of `name`, or nothing.
std::optional<QByteArray> attribute(const QByteArray &message, char name) {
    for (const QByteArray &part : message.split(',')) {
        if (part.size() >= 2 && part.at(0) == name && part.at(1) == '=') {
            return part.mid(2);
        }
    }
    return std::nullopt;
}

}  // namespace

ClientStart start() {
    QByteArray random(24, Qt::Uninitialized);  // a whole number of quint32s
    QRandomGenerator::system()->fillRange(reinterpret_cast<quint32 *>(random.data()),
                                          random.size() / sizeof(quint32));
    ClientStart out;
    // Base64 has no comma, the one character a nonce may not hold.
    out.nonce = random.toBase64();
    out.firstBare = QByteArrayLiteral("n=homedash,r=") + out.nonce;
    out.first = QByteArray(kGs2Header) + out.firstBare;
    return out;
}

std::optional<ClientFinal> answer(const QString &password, const ClientStart &start,
                                  const QByteArray &serverFirst, const QByteArray &binding) {
    const auto nonce = attribute(serverFirst, 'r');
    const auto saltText = attribute(serverFirst, 's');
    const auto iterationsText = attribute(serverFirst, 'i');
    if (!nonce || !saltText || !iterationsText || !nonce->startsWith(start.nonce) ||
        nonce->size() <= start.nonce.size()) {
        return std::nullopt;
    }
    const auto salt = QByteArray::fromBase64Encoding(*saltText,
                                                     QByteArray::AbortOnBase64DecodingErrors);
    bool numeric = false;
    const int iterations = iterationsText->toInt(&numeric);
    if (!salt || salt.decoded.size() < 16 || !numeric || iterations < kMinIterations ||
        iterations > kMaxIterations) {
        return std::nullopt;
    }

    // NFKC, the core of SASLprep — what the backend applies to the .env password.
    const QByteArray normalized =
        password.normalized(QString::NormalizationForm_KC).toUtf8();
    const QByteArray salted = QPasswordDigestor::deriveKeyPbkdf2(
        QCryptographicHash::Sha256, normalized, salt.decoded, iterations, 32);
    const QByteArray clientKey = hmac(salted, QByteArrayLiteral("Client Key"));
    const QByteArray storedKey = QCryptographicHash::hash(clientKey, QCryptographicHash::Sha256);
    const QByteArray serverKey = hmac(salted, QByteArrayLiteral("Server Key"));

    const QByteArray withoutProof = QByteArrayLiteral("c=") +
                                    (QByteArray(kGs2Header) + binding).toBase64() +
                                    QByteArrayLiteral(",r=") + *nonce;
    const QByteArray authMessage = start.firstBare + ',' + serverFirst + ',' + withoutProof;
    const QByteArray signature = hmac(storedKey, authMessage);
    QByteArray proof = clientKey;
    for (qsizetype i = 0; i < proof.size(); ++i) {
        proof[i] = static_cast<char>(proof.at(i) ^ signature.at(i));
    }

    ClientFinal out;
    out.message = withoutProof + QByteArrayLiteral(",p=") + proof.toBase64();
    out.expectedServerFinal = QByteArrayLiteral("v=") + hmac(serverKey, authMessage).toBase64();
    return out;
}

}  // namespace scram
