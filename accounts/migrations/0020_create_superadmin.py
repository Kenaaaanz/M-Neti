# billing/migrations/000X_create_superadmin.py
from django.db import migrations
from django.contrib.auth.hashers import make_password
import uuid

def create_superadmin(apps, schema_editor):
    # Get models
    CustomUser = apps.get_model('accounts', 'CustomUser')
    
    # Check if superadmin already exists
    if not CustomUser.objects.filter(email='gichabakenani@gmail.com').exists():
        superadmin = CustomUser.objects.create(
            username='Kenani',
            email='gichabakenani@gmail.com',
            first_name='Kenani',
            last_name='Gichaba',
            phone='+254790251635',
            role='superadmin',
            registration_status='approved',
            is_active=True,
            is_staff=True,
            is_superuser=True,
            password=make_password('admin@123')  # Change this password!
        )
        print(f"✅ Superadmin created: {superadmin.email}")

def delete_superadmin(apps, schema_editor):
    CustomUser = apps.get_model('accounts', 'CustomUser')
    CustomUser.objects.filter(email='gichabakenani@gmail.com').delete()
    print(f"🗑️ Superadmin deleted")

class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0019_activitylog'),  
    ]

    operations = [
        migrations.RunPython(create_superadmin, delete_superadmin),
    ]