# router_manager/signals.py - Create this file
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.core.cache import cache
import logging

logger = logging.getLogger(__name__)

@receiver(post_save, sender='router_manager.Router')
def handle_router_status_change(sender, instance, created, **kwargs):
    """
    Handle router status changes - update map pin color
    """
    try:
        if instance.user and hasattr(instance.user, 'tenant') and instance.user.tenant:
            # Clear cache to force map refresh
            cache_key = f'customer_locations_{instance.user.tenant.id}'
            cache.delete(cache_key)
            
            logger.info(f"Cleared cache after router {instance.id} status change to {instance.is_online}")
    
    except Exception as e:
        logger.error(f"Error handling router status change: {e}")


@receiver(post_save, sender='router_manager.Device')
def handle_device_status_change(sender, instance, created, **kwargs):
    """
    Handle device status changes - update map pin color
    """
    try:
        if instance.router and instance.router.user:
            user = instance.router.user
            
            if hasattr(user, 'tenant') and user.tenant:
                # Clear cache to force map refresh
                cache_key = f'customer_locations_{user.tenant.id}'
                cache.delete(cache_key)
                
                logger.info(f"Cleared cache after device {instance.id} status change to {instance.is_online}")
    
    except Exception as e:
        logger.error(f"Error handling device status change: {e}")