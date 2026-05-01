"""
Security utilities for OmniCode backend.
Handles token encryption using Fernet and JWT validation.
"""

from cryptography.fernet import Fernet, InvalidToken
from jose import jwt, JWTError
from datetime import datetime, timedelta
from typing import Optional
import base64

from app.core.config import get_settings


class TokenEncryptor:
    """Handles Fernet encryption/decryption for sensitive tokens like GitHub tokens."""

    def __init__(self, encryption_key: str):
        self._fernet = self._create_fernet(encryption_key)

    @staticmethod
    def _create_fernet(key: str) -> Fernet:
        key_bytes = key.encode()
        padded_key = base64.urlsafe_b64encode(key_bytes.ljust(32, b'\0')[:32])
        return Fernet(padded_key)

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a string and return base64-encoded ciphertext."""
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> Optional[str]:
        """Decrypt base64-encoded ciphertext and return plaintext."""
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except InvalidToken:
            return None

    @staticmethod
    def generate_key() -> str:
        """Generate a new Fernet-compatible encryption key."""
        return Fernet.generate_key().decode()


class JWTValidator:
    """Handles JWT token validation for API requests."""

    def __init__(self, secret: str, algorithm: str = "HS256"):
        self._secret = secret
        self._algorithm = algorithm

    def create_token(
        self,
        subject: str,
        expires_delta: Optional[timedelta] = None,
        additional_claims: Optional[dict] = None,
    ) -> str:
        """Create a new JWT token."""
        if expires_delta is None:
            expires_delta = timedelta(hours=24)

        now = datetime.utcnow()
        payload = {
            "sub": subject,
            "iat": now,
            "exp": now + expires_delta,
        }
        if additional_claims:
            payload.update(additional_claims)

        return jwt.encode(payload, self._secret, algorithm=self._algorithm)

    def verify_token(self, token: str) -> Optional[dict]:
        """Verify and decode a JWT token. Returns payload dict or None if invalid."""
        try:
            return jwt.decode(token, self._secret, algorithms=[self._algorithm])
        except JWTError:
            return None

    def get_subject(self, token: str) -> Optional[str]:
        """Extract subject from a token."""
        payload = self.verify_token(token)
        return payload.get("sub") if payload else None


class SecurityManager:
    """High-level security operations combining encryption and JWT."""

    def __init__(self):
        settings = get_settings()
        self._token_encryptor = TokenEncryptor(settings.encryption_key)
        self._jwt_validator = JWTValidator(settings.jwt_secret)

    def encrypt_token(self, token: str) -> str:
        """Encrypt a sensitive token (e.g., GitHub access token)."""
        return self._token_encryptor.encrypt(token)

    def decrypt_token(self, encrypted_token: str) -> Optional[str]:
        """Decrypt a stored token."""
        return self._token_encryptor.decrypt(encrypted_token)

    def create_api_token(self, user_id: str, expires_hours: int = 24) -> str:
        """Create a JWT API token for a user."""
        return self._jwt_validator.create_token(
            subject=user_id,
            expires_delta=timedelta(hours=expires_hours),
        )

    def verify_api_token(self, token: str) -> Optional[str]:
        """Verify an API token and return user_id or None."""
        return self._jwt_validator.get_subject(token)

    def validate_bearer_token(self, authorization: Optional[str]) -> Optional[str]:
        """Extract and validate user from Authorization: Bearer header."""
        if not authorization:
            return None

        parts = authorization.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return None

        return self.verify_api_token(parts[1])


security_manager = SecurityManager()