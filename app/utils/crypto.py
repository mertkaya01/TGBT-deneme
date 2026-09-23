"""Userbot oturum string'lerinin şifrelenmesi (Fernet / AES-128-CBC + HMAC)."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class SessionDecryptError(Exception):
    """Oturum çözülemedi (yanlış anahtar veya bozuk veri)."""


class SessionCipher:
    def __init__(self, key: str) -> None:
        try:
            self._fernet = Fernet(key.encode())
        except (ValueError, TypeError) as exc:
            raise ValueError(
                "SESSION_ENCRYPTION_KEY geçerli bir Fernet anahtarı değil. "
                "Üretmek için: python -m app.tools.genkey"
            ) from exc

    def encrypt(self, plain: str) -> str:
        return self._fernet.encrypt(plain.encode()).decode()

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken as exc:
            raise SessionDecryptError("Oturum verisi çözülemedi") from exc

    @staticmethod
    def generate_key() -> str:
        return Fernet.generate_key().decode()
