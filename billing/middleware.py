# billing/middleware.py
import logging
from django.utils import timezone
from .models import Payment
from datetime import timedelta

logger = logging.getLogger(__name__)

class AutoPaymentMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        response = self.get_response(request)
        
        # Check for completed payments that need processing
        # This runs on every request but you might want to throttle it
        if request.user.is_authenticated and hasattr(request.user, 'tenant'):
            try:
                # Process any pending payments that were completed
                completed_payments = Payment.objects.filter(
                    user__tenant=request.user.tenant,
                    status='completed',
                    subscription_activated=False  # Add this field to Payment model
                )
                
                for payment in completed_payments:
                    payment.auto_activate_subscription()
                    payment.subscription_activated = True
                    payment.save()
                    
            except Exception as e:
                logger.error(f"Auto-payment middleware error: {e}")
        
        return response