# billing/utils/commission_utils.py
from decimal import Decimal
from ..models import PlatformCommission, Tenant, CommissionTransaction, Payment

def calculate_commission(tenant, service_type, amount, **kwargs):
    """
    Calculate commission for a transaction
    Returns: (commission_amount, net_amount, commission_object)
    """
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
    from ..models import CommissionTransaction
    
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