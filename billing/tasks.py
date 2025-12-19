# billing/tasks.py
from celery import shared_task
from django.utils import timezone
from .models import Payment, Subscription
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)

@shared_task
def verify_pending_payments():
    """
    Check pending payments and verify their status
    Runs every 10 minutes
    """
    try:
        # Get payments that have been pending for more than 30 minutes
        thirty_minutes_ago = timezone.now() - timedelta(minutes=30)
        pending_payments = Payment.objects.filter(
            status='pending',
            created_at__lte=thirty_minutes_ago,
            payment_method__in=['paystack', 'stripe']  # Only auto-verify online payments
        )
        
        for payment in pending_payments:
            try:
                # Verify payment status based on payment method
                if payment.payment_method == 'paystack':
                    from .views import verify_paystack_payment
                    verify_paystack_payment(payment.reference)
                # Add other payment methods as needed
                
                logger.info(f"Verified payment {payment.reference}")
                
            except Exception as e:
                logger.error(f"Failed to verify payment {payment.reference}: {e}")
        
        return f"Verified {pending_payments.count()} payments"
        
    except Exception as e:
        logger.error(f"Payment verification task failed: {e}")
        return f"Error: {e}"

@shared_task
def process_offline_payments():
    """
    Process manual/offline payments that need review
    Runs daily
    """
    try:
        # Find manual payments marked as "review_required"
        manual_payments = Payment.objects.filter(
            payment_method__in=['cash', 'bank_transfer', 'mobile_money'],
            status='pending',
            created_at__lte=timezone.now() - timedelta(hours=1)  # Wait 1 hour for admin review
        )
        
        # Auto-approve small payments or those with proper references
        for payment in manual_payments:
            try:
                # Check if payment has a valid reference (M-PESA code, receipt #, etc.)
                if payment.reference and len(payment.reference) > 5:
                    # Auto-approve if amount is reasonable
                    if payment.amount <= 10000:  # Auto-approve payments under 10,000 KSH
                        payment.status = 'completed'
                        payment.save()
                        logger.info(f"Auto-approved manual payment: {payment.reference}")
                    else:
                        # Flag for admin review
                        payment.status = 'review_required'
                        payment.save()
                        logger.info(f"Flagged for review: {payment.reference} - Amount: {payment.amount}")
                
            except Exception as e:
                logger.error(f"Failed to process manual payment {payment.id}: {e}")
        
        return f"Processed {manual_payments.count()} manual payments"
        
    except Exception as e:
        logger.error(f"Manual payment processing task failed: {e}")
        return f"Error: {e}"