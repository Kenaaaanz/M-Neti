# billing/services.py
from django.utils import timezone
from .models import Payment
import logging

logger = logging.getLogger(__name__)

class SubscriptionService:
    """Service for handling subscription activations"""
    
    @staticmethod
    def activate_user_subscription(user, plan, payment=None):
        """
        Activate or extend a user's subscription
        
        Args:
            user: CustomUser instance
            plan: SubscriptionPlan instance
            payment: Optional Payment instance for tracking
        """
        try:
            from .models import Subscription

            # Check for existing active subscription
            existing_sub = Subscription.objects.filter(
                user=user,
                is_active=True,
                end_date__gte=timezone.now()
            ).first()
            
            if existing_sub:
                # Extend existing subscription
                existing_sub.end_date = existing_sub.end_date + timezone.timedelta(days=plan.duration_days)
                existing_sub.save()
                
                # Update next payment date
                if user.next_payment_date:
                    user.next_payment_date = user.next_payment_date + timezone.timedelta(days=plan.duration_days)
                else:
                    user.next_payment_date = existing_sub.end_date
                user.save()
                
                logger.info(f"Extended subscription for {user.username}: {plan.name}")
                return existing_sub
            else:
                # Create new subscription
                subscription = Subscription.objects.create(
                    user=user,
                    plan=plan,
                    start_date=timezone.now(),
                    end_date=timezone.now() + timezone.timedelta(days=plan.duration_days),
                    is_active=True
                )
                
                # Update next payment date
                user.next_payment_date = subscription.end_date
                user.is_active_customer = True
                user.save()
                
                logger.info(f"Created new subscription for {user.username}: {plan.name}")
                return subscription
                
        except Exception as e:
            logger.error(f"Failed to activate subscription for {user.username}: {e}")
            raise
    
    @staticmethod
    def auto_activate_from_payment(payment):
        """
        Auto-activate subscription from payment
        """
        if payment.status == 'completed' and payment.plan and payment.user:
            try:
                SubscriptionService.activate_user_subscription(
                    user=payment.user,
                    plan=payment.plan,
                    payment=payment
                )
                
                # Mark payment as subscription activated
                payment.subscription_activated = True
                payment.save(update_fields=['subscription_activated'])
                
                return True
            except Exception as e:
                logger.error(f"Auto-activation failed for payment {payment.reference}: {e}")
        
        return False

# Create singleton instance
subscription_service = SubscriptionService()