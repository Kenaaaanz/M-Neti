# billing/utils.py
from decimal import Decimal, ROUND_HALF_UP


def decimal_to_paystack_amount(amount: Decimal) -> int:
    """
    Convert Decimal amount to Paystack amount in kobo.
    Paystack expects amount in the smallest currency unit (kobo for Naira).
    """
    # Convert to float and multiply by 100, then round to nearest integer
    amount_in_kobo = float(amount) * 100
    return int(round(amount_in_kobo))

# Or if you want to keep it in Decimal operations:
def decimal_to_paystack_amount_decimal(amount: Decimal) -> int:
    """
    Convert Decimal amount to Paystack amount using Decimal operations.
    """
    amount_in_kobo = (amount * Decimal('100')).quantize(Decimal('1.'), rounding=ROUND_HALF_UP)
    return int(amount_in_kobo)

# billing/utils/commission_utils.py

def calculate_commission(tenant, service_type, amount, **kwargs):
    """
    Calculate commission for a transaction
    Returns: (commission_amount, net_amount, commission_object)
    """
    from .models import PlatformCommission
    
    try:
        # First, check for ISP-specific commission
        commission = PlatformCommission.objects.filter(
            tenant=tenant,
            service_type=service_type,
            is_active=True
        ).first()
        
        # If no ISP-specific, check for all-ISPs commission
        if not commission:
            commission = PlatformCommission.objects.filter(
                applies_to_all=True,
                service_type=service_type,
                is_active=True
            ).first()
        
        # If still no commission, use default
        if not commission:
            # Create a default commission object
            commission_amount = amount * Decimal('0.075')  # 7.5% default
            net_amount = amount - commission_amount
            return commission_amount, net_amount, None
        
        # Calculate based on commission settings
        if commission.calculation_method == 'percentage':
            commission_amount = amount * commission.rate / Decimal('100')
        elif commission.calculation_method == 'fixed':
            commission_amount = commission.fixed_amount
        elif commission.calculation_method == 'tiered':
            # Implement tiered logic
            commission_amount = amount * commission.rate / Decimal('100')
        else:
            commission_amount = Decimal('0')
        
        net_amount = amount - commission_amount
        
        return commission_amount, net_amount, commission
        
    except Exception as e:
        # Fallback to default calculation
        commission_amount = amount * Decimal('0.075')
        net_amount = amount - commission_amount
        return commission_amount, net_amount, None

def create_commission_transaction(payment, tenant, service_type, amount, **kwargs):
    """Create a commission transaction record"""
    from .models import CommissionTransaction
    
    commission_amount, net_amount, commission_obj = calculate_commission(
        tenant, service_type, amount, **kwargs
    )
    
    commission_txn = CommissionTransaction.objects.create(
        payment=payment,
        tenant=tenant,
        commission=commission_obj,
        transaction_amount=amount,
        commission_amount=commission_amount,
        net_amount=net_amount,
        description=f"Commission for {service_type} payment",
        status='calculated'
    )
    
    # Link to bulk purchase if applicable
    bulk_purchase = kwargs.get('bulk_purchase')
    if bulk_purchase:
        commission_txn.bulk_purchase = bulk_purchase
        commission_txn.save()
    
    return commission_txn

def get_commission_summary(tenant, start_date=None, end_date=None):
    """Get commission summary for a tenant"""
    from django.db.models import Sum
    from .models import CommissionTransaction
    
    filters = {'tenant': tenant}
    if start_date:
        filters['created_at__gte'] = start_date
    if end_date:
        filters['created_at__lte'] = end_date
    
    transactions = CommissionTransaction.objects.filter(**filters)
    
    summary = transactions.aggregate(
        total_transactions=Sum('transaction_amount'),
        total_commission=Sum('commission_amount'),
        total_net=Sum('net_amount')
    )
    
    return {
        'transaction_count': transactions.count(),
        'total_transactions': summary['total_transactions'] or Decimal('0'),
        'total_commission': summary['total_commission'] or Decimal('0'),
        'total_net': summary['total_net'] or Decimal('0'),
        'commission_percentage': (
            (summary['total_commission'] / summary['total_transactions'] * 100)
            if summary['total_transactions'] and summary['total_transactions'] > 0
            else Decimal('0')
        )
    }

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