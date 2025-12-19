# accounts/management/commands/fix_user_tenants.py
from django.core.management.base import BaseCommand
from accounts.models import CustomUser, Tenant

class Command(BaseCommand):
    help = 'Assign tenants to users without tenants'

    def handle(self, *args, **options):
        # Get or create a default tenant
        default_tenant, created = Tenant.objects.get_or_create(
            name='Default ISP',
            defaults={
                'company_name': 'Default ISP Company',
                'subdomain': 'default',
                'contact_email': 'admin@default.com',
                'contact_phone': '+254700000000'
            }
        )
        
        if created:
            self.stdout.write(self.style.SUCCESS(f'Created default tenant: {default_tenant.name}'))
        
        # Assign tenants to users based on their roles
        users_without_tenants = CustomUser.objects.filter(tenant__isnull=True)
        
        for user in users_without_tenants:
            if user.role in ['isp_admin', 'isp_staff']:
                # ISP users get their own tenant
                tenant, created = Tenant.objects.get_or_create(
                    name=f"{user.username}'s ISP",
                    defaults={
                        'company_name': f"{user.username}'s Company",
                        'subdomain': user.username.lower(),
                        'contact_email': user.email,
                        'contact_phone': user.phone or '+254700000000'
                    }
                )
                user.tenant = tenant
                user.save()
                self.stdout.write(self.style.SUCCESS(f'Assigned tenant to ISP user: {user.username} -> {tenant.name}'))
            
            else:
                # Customers get the default tenant
                user.tenant = default_tenant
                user.save()
                self.stdout.write(self.style.SUCCESS(f'Assigned default tenant to customer: {user.username}'))
        
        self.stdout.write(self.style.SUCCESS(
            f'Successfully assigned tenants to {users_without_tenants.count()} users'
        ))