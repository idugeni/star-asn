import os
from cryptography.fernet import Fernet

from star_attendance.core.config import settings

class SecurityManager:
    def __init__(self):
        # We now rely fully on settings validation - if it's missing, it will crash upstream (fail-fast)
        self.cipher = Fernet(settings.MASTER_SECURITY_KEY.encode())

    def encrypt_password(self, password: str) -> str:
        if not password:
            return ""
        return self.cipher.encrypt(password.encode()).decode()

    def decrypt_password(self, encrypted_password: str) -> str:
        if not encrypted_password:
            return ""
        try:
            return self.cipher.decrypt(encrypted_password.encode()).decode()
        except Exception:
            return ""


# Singleton
security_manager = SecurityManager()
