"""Phase 21 tests: secret encryption at rest (Fernet-based)."""

from __future__ import annotations

import pytest

from src.security.secrets import (
    SecretDecryptionError,
    decrypt_secret,
    encrypt_secret,
    generate_key,
)


class TestGenerateKey:
    def test_returns_a_string(self):
        assert isinstance(generate_key(), str)

    def test_keys_are_unique(self):
        assert generate_key() != generate_key()


class TestEncryptDecryptRoundTrip:
    def test_round_trips_plaintext(self):
        key = generate_key()
        token = encrypt_secret("sk-super-secret-value", key)
        assert decrypt_secret(token, key) == "sk-super-secret-value"

    def test_ciphertext_does_not_contain_plaintext(self):
        key = generate_key()
        token = encrypt_secret("sk-super-secret-value", key)
        assert "sk-super-secret-value" not in token

    def test_round_trips_unicode(self):
        key = generate_key()
        token = encrypt_secret("clé secrète 🔑 日本語", key)
        assert decrypt_secret(token, key) == "clé secrète 🔑 日本語"

    def test_round_trips_empty_string(self):
        key = generate_key()
        token = encrypt_secret("", key)
        assert decrypt_secret(token, key) == ""

    def test_two_encryptions_of_the_same_plaintext_differ(self):
        # Fernet includes randomness/IV, so ciphertexts should not be
        # deterministic even for identical plaintext + key.
        key = generate_key()
        assert encrypt_secret("same value", key) != encrypt_secret("same value", key)


class TestDecryptionFailures:
    def test_wrong_key_raises(self):
        token = encrypt_secret("secret", generate_key())
        with pytest.raises(SecretDecryptionError):
            decrypt_secret(token, generate_key())

    def test_corrupted_token_raises(self):
        key = generate_key()
        token = encrypt_secret("secret", key)
        corrupted = token[:-4] + "abcd"
        with pytest.raises(SecretDecryptionError):
            decrypt_secret(corrupted, key)

    def test_garbage_token_raises(self):
        with pytest.raises(SecretDecryptionError):
            decrypt_secret("not-a-real-token", generate_key())
