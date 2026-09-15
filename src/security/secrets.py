"""Encryption for secrets at rest, using the already-vendored ``cryptography``
package (Fernet symmetric encryption) rather than adding a new dependency.

This is a small, focused helper — not a secrets manager. It answers one
question: given a key, how do I store a sensitive string (an API key, a
webhook secret, ...) on disk without it being plaintext. The key itself is the
caller's responsibility to keep safe (an environment variable, a file with
restrictive permissions, or an OS keychain); this module never persists a key.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class SecretDecryptionError(ValueError):
    """Raised when a ciphertext cannot be decrypted with the given key.

    Wraps :class:`cryptography.fernet.InvalidToken` so callers only need to
    catch one, module-local exception type.
    """


def generate_key() -> str:
    """Generate a new base64-encoded Fernet key, as a string.

    Callers store this somewhere safe (an env var, a local key file with
    restrictive permissions) — it is what :func:`encrypt_secret`/
    :func:`decrypt_secret` need to do their work.
    """
    return Fernet.generate_key().decode("ascii")


def encrypt_secret(plaintext: str, key: str) -> str:
    """Encrypt ``plaintext`` with ``key``, returning an opaque token string."""
    fernet = Fernet(key.encode("ascii"))
    return fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str, key: str) -> str:
    """Decrypt a token produced by :func:`encrypt_secret`.

    Raises :class:`SecretDecryptionError` if ``key`` is wrong or ``token`` is
    malformed/tampered with — never returns a partially-decrypted result.
    """
    fernet = Fernet(key.encode("ascii"))
    try:
        return fernet.decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise SecretDecryptionError("cannot decrypt: wrong key or corrupted token") from exc
