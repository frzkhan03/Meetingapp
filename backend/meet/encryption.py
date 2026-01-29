"""
Encryption utilities for PyTalk
Provides encryption and decryption functions for sensitive data.
Uses Fernet symmetric encryption (AES-128-CBC with HMAC).
"""

import base64
import hashlib
import secrets
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from django.conf import settings


class EncryptionError(Exception):
    """Custom exception for encryption errors"""
    pass


class DataEncryption:
    """
    Handles encryption and decryption of sensitive data.
    Uses Fernet (symmetric encryption) with a key derived from settings.
    """

    def __init__(self, key=None):
        """Initialize with encryption key from settings or provided key"""
        self._key = key or getattr(settings, 'ENCRYPTION_KEY', None)
        if not self._key:
            raise EncryptionError('No encryption key configured')
        self._fernet = self._create_fernet()

    def _create_fernet(self):
        """Create Fernet instance with derived key"""
        # Use PBKDF2 to derive a proper Fernet key from the settings key
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b'pytalk_salt_v1',  # Static salt (key should be unique per deployment)
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(self._key.encode()))
        return Fernet(key)

    def encrypt(self, data):
        """
        Encrypt data.

        Args:
            data: String or bytes to encrypt

        Returns:
            Base64-encoded encrypted string
        """
        if isinstance(data, str):
            data = data.encode('utf-8')
        try:
            encrypted = self._fernet.encrypt(data)
            return encrypted.decode('utf-8')
        except Exception as e:
            raise EncryptionError(f'Encryption failed: {str(e)}')

    def decrypt(self, encrypted_data):
        """
        Decrypt data.

        Args:
            encrypted_data: Base64-encoded encrypted string

        Returns:
            Decrypted string
        """
        if isinstance(encrypted_data, str):
            encrypted_data = encrypted_data.encode('utf-8')
        try:
            decrypted = self._fernet.decrypt(encrypted_data)
            return decrypted.decode('utf-8')
        except InvalidToken:
            raise EncryptionError('Invalid token or corrupted data')
        except Exception as e:
            raise EncryptionError(f'Decryption failed: {str(e)}')


# Singleton instance for convenience
_encryption_instance = None


def get_encryptor():
    """Get or create the singleton encryption instance"""
    global _encryption_instance
    if _encryption_instance is None:
        _encryption_instance = DataEncryption()
    return _encryption_instance


def encrypt_data(data):
    """Convenience function to encrypt data"""
    return get_encryptor().encrypt(data)


def decrypt_data(encrypted_data):
    """Convenience function to decrypt data"""
    return get_encryptor().decrypt(encrypted_data)


class SecureToken:
    """
    Generates and validates secure tokens for various purposes
    (password reset, email verification, etc.)
    """

    @staticmethod
    def generate(length=32):
        """Generate a cryptographically secure random token"""
        return secrets.token_urlsafe(length)

    @staticmethod
    def generate_hash(token):
        """Generate a hash of a token for storage"""
        return hashlib.sha256(token.encode()).hexdigest()

    @staticmethod
    def verify(token, stored_hash):
        """Verify a token against a stored hash"""
        return secrets.compare_digest(
            hashlib.sha256(token.encode()).hexdigest(),
            stored_hash
        )


class PasswordHasher:
    """
    Additional password hashing utilities.
    Django handles main password hashing, this is for additional uses.
    """

    @staticmethod
    def hash_password(password, salt=None):
        """
        Hash a password with PBKDF2.
        For use cases outside Django's auth system.
        """
        if salt is None:
            salt = secrets.token_bytes(16)
        elif isinstance(salt, str):
            salt = salt.encode()

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=260000,  # OWASP recommended minimum
        )
        key = kdf.derive(password.encode())

        # Return salt + hash encoded as base64
        return base64.b64encode(salt + key).decode()

    @staticmethod
    def verify_password(password, stored_hash):
        """Verify a password against a stored hash"""
        try:
            decoded = base64.b64decode(stored_hash.encode())
            salt = decoded[:16]
            stored_key = decoded[16:]

            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=260000,
            )
            new_key = kdf.derive(password.encode())

            return secrets.compare_digest(new_key, stored_key)
        except Exception:
            return False


def mask_sensitive_data(data, visible_chars=4):
    """
    Mask sensitive data for logging/display.
    Shows only the first and last few characters.
    """
    if not data or len(data) <= visible_chars * 2:
        return '*' * len(data) if data else ''

    return f"{data[:visible_chars]}{'*' * (len(data) - visible_chars * 2)}{data[-visible_chars:]}"
