# billing/utils/encryption.py
"""
Encryption utilities for sensitive data storage
Uses Django's signing module for secure encryption/decryption
"""

from django.core import signing
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

class DataEncryption:
    """
    Encryption utility for sensitive data
    
    Usage:
        encrypted = DataEncryption.encrypt("my_secret_data")
        decrypted = DataEncryption.decrypt(encrypted)
    """
    
    @staticmethod
    def encrypt(value: str) -> str:
        """
        Encrypt a string value
        
        Args:
            value: The string to encrypt
            
        Returns:
            Encrypted string or None if encryption fails
        """
        if not value or not isinstance(value, str):
            return None
        
        try:
            # signing.dumps() returns a signed and timestamped string
            encrypted = signing.dumps(value, salt=settings.SECRET_KEY)
            return encrypted
        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            return None
    
    @staticmethod
    def decrypt(encrypted_value: str) -> str:
        """
        Decrypt an encrypted string
        
        Args:
            encrypted_value: The encrypted string
            
        Returns:
            Decrypted string or empty string if decryption fails
        """
        if not encrypted_value or not isinstance(encrypted_value, str):
            return ''
        
        try:
            # signing.loads() decrypts and verifies the signature
            decrypted = signing.loads(encrypted_value, salt=settings.SECRET_KEY)
            return decrypted
        except signing.BadSignature:
            logger.warning("Decryption failed: Bad signature")
            return ''
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            return ''
    
    @staticmethod
    def encrypt_for_db(value: str) -> str:
        """Alias for encrypt() for database storage"""
        return DataEncryption.encrypt(value)
    
    @staticmethod
    def decrypt_from_db(encrypted_value: str) -> str:
        """Alias for decrypt() for database retrieval"""
        return DataEncryption.decrypt(encrypted_value)
    
    @staticmethod
    def is_encrypted(value: str) -> bool:
        """
        Check if a string appears to be encrypted
        
        Args:
            value: The string to check
            
        Returns:
            True if it looks like an encrypted string
        """
        if not value:
            return False
        
        # Django's signed strings have a specific format with colon separators
        parts = value.split(':')
        return len(parts) >= 2 and parts[0].startswith('g')
    
    @staticmethod
    def safe_encrypt(value: str, default: str = '') -> str:
        """
        Safely encrypt a value, returning default if encryption fails
        
        Args:
            value: The string to encrypt
            default: Default value if encryption fails
            
        Returns:
            Encrypted string or default
        """
        encrypted = DataEncryption.encrypt(value)
        return encrypted if encrypted is not None else default