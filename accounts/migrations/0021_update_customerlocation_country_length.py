from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0020_create_superadmin'),
    ]

    operations = [
        migrations.AlterField(
            model_name='customerlocation',
            name='country',
            field=models.CharField(blank=True, default='Kenya', max_length=100),
        ),
    ]