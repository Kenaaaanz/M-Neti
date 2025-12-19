# billing/management/commands/check_subscriptions.py
from django.core.management.base import BaseCommand
from django.utils import timezone
from billing.services import subscription_service
from accounts.models import CustomUser
from router_manager.models import Device
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Check and update subscription statuses'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--send-reminders',
            action='store_true',
            help='Send renewal reminders to users',
        )
    
    def handle(self, *args, **options):
        self.stdout.write("Starting subscription check...")
        
        # Check for expired subscriptions
        deactivated_count = subscription_service.check_expired_subscriptions()
        
        if deactivated_count > 0:
            self.stdout.write(
                self.style.WARNING(f"Deactivated {deactivated_count} expired subscriptions")
            )
        else:
            self.stdout.write("No expired subscriptions found")
        
        # Send renewal reminders if requested
        if options['send_reminders']:
            self.stdout.write("Sending renewal reminders...")
            subscription_service.send_renewal_reminders()
            self.stdout.write("Renewal reminders sent")
        
        # Display current stats
        active_users = CustomUser.objects.filter(
            role='customer', 
            is_active_customer=True
        ).count()
        
        expired_users = CustomUser.objects.filter(
            role='customer',
            is_active_customer=False,
            next_payment_date__lt=timezone.now()
        ).count()
        
        self.stdout.write(
            self.style.SUCCESS(
                f"Subscription check completed. Active: {active_users}, Expired: {expired_users}"
            )
        )