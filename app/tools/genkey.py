"""Yeni bir SESSION_ENCRYPTION_KEY üretir: python -m app.tools.genkey"""

from app.utils.crypto import SessionCipher

if __name__ == "__main__":
    print(SessionCipher.generate_key())
