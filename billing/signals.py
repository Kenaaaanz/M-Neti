# billing/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from .models import Payment, Subscription
import logging

logger = logging.getLogger(__name__)

@receiver(post_save, sender=Payment)
def handle_payment_completion(sender, instance, created, **kwargs):
    """
    Automatically activate subscription when payment is completed
    """
    try:
        # Only process if payment is completed and has a plan
        if instance.status == 'completed' and instance.plan and instance.user:
            
            # Check if subscription was already activated
            if instance.subscription_activated:
                return
            
            # Check if user already has an active subscription
            existing_sub = Subscription.objects.filter(
                user=instance.user,
                is_active=True
            ).first()
            
            if existing_sub:
                # Extend existing subscription
                existing_sub.end_date = existing_sub.end_date + timezone.timedelta(days=instance.plan.duration_days)
                existing_sub.save()
                logger.info(f"Extended subscription for user {instance.user.username}")
            else:
                # Create new subscription
                Subscription.objects.create(
                    user=instance.user,
                    plan=instance.plan,
                    start_date=timezone.now(),
                    end_date=timezone.now() + timezone.timedelta(days=instance.plan.duration_days),
                    is_active=True
                )
                logger.info(f"Created new subscription for user {instance.user.username}")
            
            # Update customer's next payment date
            if instance.user.next_payment_date:
                instance.user.next_payment_date = instance.user.next_payment_date + timezone.timedelta(days=instance.plan.duration_days)
            else:
                instance.user.next_payment_date = timezone.now() + timezone.timedelta(days=instance.plan.duration_days)
            instance.user.save()
            
            # Mark payment as subscription activated
            instance.subscription_activated = True
            instance.save(update_fields=['subscription_activated'])
            
            logger.info(f"Auto-activated subscription for payment {instance.reference}")
            
    except Exception as e:
        logger.error(f"Failed to auto-activate subscription for payment {instance.reference}: {e}")

from accounts.utils_module.map_updates import send_map_update

@receiver(post_save, sender='billing.Subscription')
def handle_subscription_activation(sender, instance, created, **kwargs):
    """
    Handle subscription activation - update map pin color
    """
    try:
        # ... existing code ...
        
        # Send WebSocket update
        if instance.user.tenant:
            send_map_update(
                instance.user.tenant.id,
                'subscription_activated',
                {
                    'user_id': instance.user.id,
                    'subscription_id': instance.id,
                    'plan_name': instance.plan.name if instance.plan else None,
                    'is_active': instance.is_active
                }
            )
        
    except Exception as e:
        logger.error(f"Error handling subscription activation: {e}")

@receiver(post_save, sender='billing.Payment')
def handle_payment_completion(sender, instance, created, **kwargs):
    """
    Handle payment completion - update map pin color
    """
    try:
        # Only process completed payments
        if instance.status == 'completed' and instance.user:
            user = instance.user
            
            # Clear customer locations cache to force refresh
            if hasattr(user, 'tenant') and user.tenant:
                cache_key = f'customer_locations_{user.tenant.id}'
                cache.delete(cache_key)
                
                logger.info(f"Cleared cache for tenant {user.tenant.id} after payment completion")
            
            # If payment has a plan, mark user as active
            if instance.plan:
                user.is_active_customer = True
                
                # Set next payment date based on plan duration
                from datetime import timedelta
                user.next_payment_date = timezone.now() + timedelta(days=instance.plan.duration_days)
                
                user.save(update_fields=['is_active_customer', 'next_payment_date'])
                
                logger.info(f"Updated user {user.username} status after payment for plan {instance.plan.name}")
            
    except Exception as e:
        logger.error(f"Error handling payment completion: {e}")