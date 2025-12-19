from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

class Command(BaseCommand):
    help = 'Create a superadmin user for CloudConnect'

    def handle(self, *args, **options):
        User = get_user_model()
        
        username = 'superadmin'
        email = 'admin@cloudconnect.com'
        password = 'Onsare@4427'
        
        if not User.objects.filter(username=username).exists():
            User.objects.create_superuser(
                username=username,
                email=email,
                password=password,
                company_account_number='SUPER001',
                role='superadmin'
            )
            self.stdout.write(
                self.style.SUCCESS(f'SuperAdmin {username} created successfully!')
            )
            self.stdout.write(
                self.style.WARNING(f'Password: {password} - CHANGE THIS IMMEDIATELY!')
            )
        else:
            self.stdout.write(
                self.style.WARNING('SuperAdmin already exists!')
            )