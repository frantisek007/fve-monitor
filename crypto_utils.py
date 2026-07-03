from cryptography.fernet import Fernet
import base64
import hashlib

class CryptoUtils:
    def __init__(self, master_key):
        key_bytes = hashlib.sha256(master_key.encode()).digest()
        self.cipher = Fernet(base64.urlsafe_b64encode(key_bytes))
    
    def encrypt(self, text):
        if not text:
            return None
        return self.cipher.encrypt(text.encode()).decode()
    
    def decrypt(self, encrypted_text):
        if not encrypted_text:
            return None
        return self.cipher.decrypt(encrypted_text.encode()).decode()
