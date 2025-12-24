# accounts/models.py
from django.contrib.auth.models import AbstractUser
from django.db import models
from django_countries.fields import CountryField
from django.core.exceptions import ValidationError
from django.utils import timezone as tz
import uuid
import re
from decimal import Decimal
from django.conf import settings
from datetime import timezone

class Tenant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    company_name = models.CharField(max_length=255)
    subdomain = models.CharField(max_length=100, unique=True)
    custom_domain = models.CharField(max_length=255, blank=True)
    contact_email = models.EmailField()
    contact_phone = models.CharField(max_length=20, blank=True)
    
    # Branding
    logo = models.ImageField(upload_to='tenant_logos/', blank=True, null=True)
    primary_color = models.CharField(max_length=7, default='#2563eb')
    secondary_color = models.CharField(max_length=7, default='#7c3aed')
    accent_color = models.CharField(max_length=7, default='#f59e0b')
    light_color = models.CharField(max_length=7, default='#eff6ff')
    dark_color = models.CharField(max_length=7, default='#1e3a8a')
    text_color = models.CharField(max_length=7, default='#1f2937')

    # UI Colors
    success_color = models.CharField(max_length=7, default='#10b981')
    warning_color = models.CharField(max_length=7, default='#f59e0b')
    error_color = models.CharField(max_length=7, default='#ef4444')
    info_color = models.CharField(max_length=7, default='#3b82f6')

    # ISP Settings
    bandwidth_limit = models.IntegerField(default=1000)
    client_limit = models.IntegerField(default=1000)
    auto_disconnect_enabled = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    
    # Subscription
    subscription_plan = models.CharField(max_length=20, choices=[
        ('starter', 'Starter'),
        ('professional', 'Professional'),
        ('enterprise', 'Enterprise'),
    ], default='starter')
    subscription_end = models.DateTimeField(null=True, blank=True)
    
    # VERIFICATION FIELDS - ADD THESE
    is_verified = models.BooleanField(default=False)
    verification_date = models.DateTimeField(null=True, blank=True)
    verification_notes = models.TextField(blank=True)
    
    # Documentation fields
    business_registration = models.FileField(upload_to='tenant_docs/business_registration/', blank=True, null=True)
    tax_certificate = models.FileField(upload_to='tenant_docs/tax_certificate/', blank=True, null=True)
    id_document = models.FileField(upload_to='tenant_docs/id_document/', blank=True, null=True)
    bank_details = models.FileField(upload_to='tenant_docs/bank_details/', blank=True, null=True)
    
    # Additional compliance fields
    business_type = models.CharField(max_length=100, blank=True)
    registration_number = models.CharField(max_length=100, blank=True)
    tax_id = models.CharField(max_length=100, blank=True)
    years_in_operation = models.IntegerField(null=True, blank=True)
    contact_person = models.CharField(max_length=100, blank=True)
    contact_position = models.CharField(max_length=100, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenants'
        verbose_name = "ISP Provider"
        verbose_name_plural = "ISP Providers"

    def clean(self):
        if self.subdomain:
            if not re.match(r'^[a-z0-9]([a-z0-9-]*[a-z0-9])?$', self.subdomain):
                raise ValidationError('Subdomain can only contain lowercase letters, numbers, and hyphens')
            reserved = ['www', 'admin', 'api', 'app', 'mail', 'test']
            if self.subdomain in reserved:
                raise ValidationError('This subdomain is reserved')

    def save(self, *args, **kwargs):
        # Ensure colors have # prefix
        if self.primary_color and not self.primary_color.startswith('#'):
            self.primary_color = '#' + self.primary_color
        if self.secondary_color and not self.secondary_color.startswith('#'):
            self.secondary_color = '#' + self.secondary_color
        if self.accent_color and not self.accent_color.startswith('#'):
            self.accent_color = '#' + self.accent_color
        
        # Set verification date when verified
        if self.is_verified and not self.verification_date:
            self.verification_date = tz.now()
        
        super().save(*args, **kwargs)

    @property
    def primary_domain(self):
        if self.custom_domain:
            return self.custom_domain
        return f"{self.subdomain}.mneti.com"

    @property
    def dashboard_url(self):
        return f"https://{self.primary_domain}/isp/dashboard/"

    def is_subscription_active(self):
        if not self.subscription_end:
            return True
        return tz.now() < self.subscription_end

    def __str__(self):
        return f"{self.name} ({self.primary_domain})"
    
    def get_default_admin(self):
        """Get the default ISP admin for this tenant"""
        return self.customuser_set.filter(role='isp_admin').first()
    
    def get_all_admins(self):
        """Get all ISP admins for this tenant"""
        return self.customuser_set.filter(role='isp_admin')
    
    def get_admin_count(self):
        return self.customuser_set.filter(
            role__in=['isp_admin', 'isp_staff'],
            is_active=True
        ).count()

    def has_admin(self):
        """Check if tenant has at least one ISP admin"""
        return self.customuser_set.filter(role='isp_admin').exists()
    
    @property
    def primary_admin(self):
        """Get the primary admin (first created)"""
        return self.customuser_set.filter(role='isp_admin').order_by('date_joined').first()


class CustomUser(AbstractUser):
    COMPANY_ACCOUNT_TYPES = [
        ('prepaid', 'Prepaid'),
        ('postpaid', 'Postpaid'),
        ('corporate', 'Corporate'),
    ]
    
    # Personal Information
    tenant = models.ForeignKey(
        Tenant, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True, 
        related_name='users'
    )
    company_account_number = models.CharField(
        max_length=20, 
        unique=False, 
        blank=True, 
        null=True, 
        default=None
    )
    phone = models.CharField(
        max_length=15,
        blank=True,
        null=True,
        verbose_name='Phone Number'
    )
    role = models.CharField(max_length=20, choices=[
        ('superadmin', 'Super Admin'),
        ('isp_admin', 'ISP Administrator'),
        ('isp_staff', 'ISP Staff'),
        ('customer', 'Customer'),
    ], default='customer')

    # Location fields - moved from separate address field
    address = models.TextField(blank=True, help_text="Full address")
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    country = CountryField(blank=True)
    zip_code = models.CharField(max_length=20, blank=True)
    
    # Customer-specific fields
    subscription_plan = models.CharField(max_length=50, blank=True)
    bandwidth_limit = models.IntegerField(default=100)
    data_usage = models.FloatField(default=0)
    account_balance = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_active_customer = models.BooleanField(default=True)
    last_payment_date = models.DateTimeField(null=True, blank=True)
    next_payment_date = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Account Information
    account_type = models.CharField(max_length=10, choices=COMPANY_ACCOUNT_TYPES, default='prepaid')
    email_verified = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    
    # Preferences
    language = models.CharField(max_length=10, default='en', choices=[('en', 'English'), ('es', 'Spanish')])
    timezone = models.CharField(max_length=50, default='UTC')
    date_format = models.CharField(max_length=20, default='MM/DD/YYYY')
    dark_mode = models.BooleanField(default=False)
    
    # Notification Preferences
    email_notifications = models.BooleanField(default=True)
    sms_notifications = models.BooleanField(default=False)
    billing_reminders = models.BooleanField(default=True)
    service_updates = models.BooleanField(default=True)
    promotional_offers = models.BooleanField(default=False)
    
    # Security
    two_factor_enabled = models.BooleanField(default=False)
    # In your models.py (CustomUser model)
class CustomUser(AbstractUser):
    # ... existing fields ...
    
    # Dark mode field (if not already there)
    dark_mode = models.BooleanField(default=False)
    
    # 2FA fields
    two_factor_enabled = models.BooleanField(default=False)
    otp_secret = models.CharField(max_length=32, blank=True, null=True)
    otp_created_at = models.DateTimeField(blank=True, null=True)
    
    # ... rest of your model ...
    last_password_change = models.DateTimeField(auto_now_add=True)
    
    # Timestamps
    date_joined = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)

    registration_status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending Approval'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
        ],
        default='pending'
    )
    registration_date = models.DateTimeField(default=tz.now)
    approval_date = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        'self', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='approved_users'
    )

    # GPS coordinates
    latitude = models.DecimalField(
        max_digits=9, 
        decimal_places=6,
        null=True, 
        blank=True,
        help_text="Latitude coordinate for mapping"
    )
    longitude = models.DecimalField(
        max_digits=9, 
        decimal_places=6,
        null=True, 
        blank=True,
        help_text="Longitude coordinate for mapping"
    )
    
    # Location metadata
    location_verified = models.BooleanField(default=False)
    location_verified_at = models.DateTimeField(null=True, blank=True)
    location_verified_by = models.ForeignKey(
        'self', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='verified_locations'
    )
    
    # Geocoding fields
    geocoded_address = models.TextField(blank=True)
    geocoded_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'custom_users'
        unique_together = [['tenant', 'company_account_number']]
        ordering = ['-date_joined']
        indexes = [
            models.Index(fields=['email']),
            models.Index(fields=['company_account_number']),
            models.Index(fields=['is_active']),
            models.Index(fields=['latitude', 'longitude']),
        ]

    @property
    def has_location(self):
        """Check if user has location coordinates"""
        return bool(self.latitude and self.longitude)
    
    @property
    def location_status(self):
        """Get location status for color coding"""
        if not self.has_location:
            return 'no_location'
        elif not self.location_verified:
            return 'unverified'
        return 'verified'
    
    def get_role_display(self):
        """Get human-readable role name"""
        role_map = {
            'superadmin': 'Super Administrator',
            'isp_admin': 'ISP Administrator', 
            'isp_staff': 'ISP Staff',
            'customer': 'Customer'
        }
        return role_map.get(self.role, self.role)
    
    def get_registration_status_display(self):
        """Get human-readable registration status"""
        status_map = {
            'pending': 'Pending Approval',
            'approved': 'Approved',
            'rejected': 'Rejected'
        }
        return status_map.get(self.registration_status, self.registration_status)
    
    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()
    
    @property
    def billing_address(self):
        parts = []
        if self.address:
            parts.append(self.address)
        if self.city:
            parts.append(self.city)
        if self.state:
            parts.append(self.state)
        if self.zip_code:
            parts.append(self.zip_code)
        if self.country:
            parts.append(str(self.country))
        return ", ".join(parts) if any(parts) else "No address specified"
    
        
    def save(self, *args, **kwargs):
        # Generate a unique company_account_number if not provided
        if not self.company_account_number:
            import uuid
            unique_id = uuid.uuid4().hex[:8].upper()
            
            if self.role == 'superadmin':
                prefix = "SUPER"
            elif self.tenant:
                prefix = self.tenant.subdomain.upper()[:6]
            else:
                prefix = "USER"
                
            self.company_account_number = f"{prefix}{unique_id}"
        
        # Ensure superusers have superadmin role
        if self.is_superuser:
            self.role = 'superadmin'
            
        # For new customer users, assign to a default tenant if none selected
        if self.pk is None and self.role == 'customer' and not self.tenant:
            default_tenant = Tenant.objects.filter(is_active=True).first()
            if default_tenant:
                self.tenant = default_tenant
                
        # Set registration_date for new users if not set
        if self.pk is None and not self.registration_date:
            self.registration_date = tz.now()
            
        try:
            return super().save(*args, **kwargs)
        except Exception as e:
            # Handle unique constraint errors
            if 'unique' in str(e).lower():
                import uuid
                unique_id = uuid.uuid4().hex[:12].upper()
                if self.role == 'superadmin':
                    self.company_account_number = f"SUPER{unique_id}"
                elif self.tenant:
                    self.company_account_number = f"{self.tenant.subdomain.upper()}{unique_id}"
                else:
                    self.company_account_number = f"USER{unique_id}"
                return super().save(*args, **kwargs)
            else:
                raise e

    def is_payment_overdue(self):
        if self.role != 'customer' or not self.next_payment_date:
            return False
        return tz.now() > self.next_payment_date

    def days_overdue(self):
        if not self.is_payment_overdue():
            return 0
        return (tz.now() - self.next_payment_date).days

    def __str__(self):
        return f"{self.company_account_number} - {self.username} ({self.role})"


class CustomerLocation(models.Model):
    """Store customer location history and details"""
    customer = models.ForeignKey(
        CustomUser, 
        on_delete=models.CASCADE,
        related_name='locations'
    )
    
    # Coordinates
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    
    # Address information
    address = models.TextField()
    city = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, blank=True, default="Kenya")
    
    # Accuracy and metadata
    accuracy = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    source = models.CharField(max_length=50, choices=[
        ('manual', 'Manual Entry'),
        ('gps', 'GPS Device'),
        ('browser', 'Browser Geolocation'),
        ('geocode', 'Address Geocoding'),
        ('admin', 'Admin Set'),
    ], default='manual')
    
    # Status
    is_primary = models.BooleanField(default=True)
    is_verified = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_customer_locations'
    )
    
    # Timestamps
    created_at = models.DateTimeField(default=tz.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-is_primary', '-created_at']
        indexes = [
            models.Index(fields=['customer', 'is_primary']),
        ]
    
    def __str__(self):
        return f"{self.customer.username} - {self.latitude},{self.longitude}"
    
    def save(self, *args, **kwargs):
        if self.is_primary:
            # Update customer's main location
            self.customer.latitude = self.latitude
            self.customer.longitude = self.longitude
            self.customer.address = self.address
            self.customer.city = self.city
            self.customer.country = self.country
            self.customer.save()
        super().save(*args, **kwargs)


class ISPZone(models.Model):
    """Define ISP service zones/areas"""
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='zones')
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    color = models.CharField(max_length=7, default='#3B82F6')  # Hex color
    
    # GeoJSON polygon for zone boundaries
    geojson = models.JSONField(blank=True, null=True)
    
    # Bounding box
    min_lat = models.DecimalField(max_digits=9, decimal_places=6)
    max_lat = models.DecimalField(max_digits=9, decimal_places=6)
    min_lng = models.DecimalField(max_digits=9, decimal_places=6)
    max_lng = models.DecimalField(max_digits=9, decimal_places=6)
    
    # Statistics
    customer_count = models.IntegerField(default=0)
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=tz.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return f"{self.tenant.name} - {self.name}"
    
    def update_customer_count(self):
        """Update customer count in this zone"""
        count = CustomUser.objects.filter(
            tenant=self.tenant,
            role='customer',
            latitude__range=(self.min_lat, self.max_lat),
            longitude__range=(self.min_lng, self.max_lng)
        ).count()
        self.customer_count = count
        self.save()


class LoginActivity(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='login_activities')
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='login_activities')
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=[
        ('success', 'Success'),
        ('failed', 'Failed'),
    ])
    
    class Meta:
        db_table = 'login_activities'
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.user.username} - {self.status} - {self.timestamp}"


class UserSession(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='sessions')
    session_key = models.CharField(max_length=40)
    user_agent = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    location = models.CharField(max_length=100, blank=True)
    device_type = models.CharField(max_length=50, blank=True)
    last_activity = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['-last_activity']
    
    def __str__(self):
        return f"{self.user} - {self.device_type} - {self.ip_address}"


class LoginHistory(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='login_history')
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    success = models.BooleanField(default=True)
    reason = models.CharField(max_length=100, blank=True)

    class Meta:
        db_table = 'login_history'


class SupportConversation(models.Model):
    """Conversation between customer and support"""
    tenant = models.ForeignKey('Tenant', on_delete=models.CASCADE, related_name='support_conversations', null=True, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='support_conversations', null=True, blank=True)
    subject = models.CharField(max_length=200)
    status = models.CharField(max_length=20, choices=[
        ('open', 'Open'),
        ('in_progress', 'In Progress'),
        ('resolved', 'Resolved'),
        ('closed', 'Closed'),
    ], default='open')
    priority = models.CharField(max_length=20, choices=[
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    ], default='medium')
    category = models.CharField(max_length=50, choices=[
        ('billing', 'Billing'),
        ('technical', 'Technical'),
        ('account', 'Account'),
        ('service', 'Service'),
        ('general', 'General'),
    ], default='general')
    
    created_at = models.DateTimeField(default=tz.now)
    updated_at = models.DateTimeField(auto_now=True)
    last_message_at = models.DateTimeField(default=tz.now)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, 
                                   related_name='assigned_conversations')
    is_read_by_customer = models.BooleanField(default=True)
    is_read_by_support = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['-last_message_at']
        db_table = 'support_conversations'
    
    def __str__(self):
        return f"{self.subject} - {self.user.username}"
    
    def mark_as_read(self, user):
        """Mark conversation as read by user"""
        if user.role in ['isp_admin', 'isp_staff']:
            self.is_read_by_support = True
        else:
            self.is_read_by_customer = True
        self.save()
    
    def get_unread_count(self, user):
        """Get unread messages count for user"""
        return self.messages.filter(is_read=False).exclude(sender=user).count()


class SupportMessage(models.Model):
    """Individual messages in support conversations"""
    conversation = models.ForeignKey(SupportConversation, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='support_messages', null=True, blank=True)
    message = models.TextField()
    attachment = models.FileField(upload_to='support_attachments/', null=True, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=tz.now)
    
    class Meta:
        ordering = ['created_at']
        db_table = 'support_messages'
    
    def __str__(self):
        return f"Message from {self.sender.username} at {self.created_at}"
    
    def save(self, *args, **kwargs):
        # Update conversation's last_message_at
        if self.conversation:
            self.conversation.last_message_at = tz.now()
            self.conversation.save()
        super().save(*args, **kwargs)


class SupportAttachment(models.Model):
    """Support attachment model"""
    message = models.ForeignKey(SupportMessage, on_delete=models.CASCADE, related_name='attachments')
    file = models.FileField(upload_to='support_attachments/%Y/%m/%d/')
    file_name = models.CharField(max_length=255)
    file_type = models.CharField(max_length=100)
    file_size = models.IntegerField()
    uploaded_at = models.DateTimeField(default=tz.now)
    
    class Meta:
        db_table = 'support_attachments'
    
    def __str__(self):
        return self.file_name


class AdminLog(models.Model):
    ACTION_CHOICES = [
        ('create_admin', 'Create Admin'),
        ('toggle_admin_status', 'Toggle Admin Status'),
        ('remove_admin', 'Remove Admin'),
        ('send_password_reset', 'Send Password Reset'),
        ('edit_permissions', 'Edit Permissions'),
        ('login', 'Admin Login'),
        ('logout', 'Admin Logout'),
    ]
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='admin_logs')
    admin = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='admin_actions')
    action = models.CharField(max_length=50, choices=ACTION_CHOICES)
    description = models.TextField()
    details = models.JSONField(blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['tenant', 'timestamp']),
            models.Index(fields=['admin', 'timestamp']),
        ]
    
    def __str__(self):
        return f"{self.admin.username} - {self.action} - {self.timestamp}"

class SMSTemplate(models.Model):
    """Template for SMS messages with variables"""
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='sms_templates')
    name = models.CharField(max_length=100)
    content = models.TextField()
    variables = models.JSONField(default=list, help_text="Available variables: {name}, {username}, {account}, {balance}, {plan}, {due_date}")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} ({self.tenant.name})"

class BulkSMS(models.Model):
    """Bulk SMS campaign"""
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='bulk_sms_campaigns')
    admin = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='sent_sms_campaigns')
    template = models.ForeignKey(SMSTemplate, on_delete=models.SET_NULL, null=True, blank=True)
    custom_message = models.TextField(blank=True)
    recipients = models.ManyToManyField(CustomUser, related_name='received_sms', limit_choices_to={'role': 'customer'})
    status = models.CharField(max_length=20, choices=[
        ('draft', 'Draft'),
        ('scheduled', 'Scheduled'),
        ('sending', 'Sending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled')
    ], default='draft')
    scheduled_time = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    sent_count = models.IntegerField(default=0)
    failed_count = models.IntegerField(default=0)
    total_recipients = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"BulkSMS #{self.id} - {self.get_status_display()} - {self.created_at}"
    
    def save(self, *args, **kwargs):
        if not self.pk:  # New object
            self.sent_count = 0
            self.failed_count = 0
        super().save(*args, **kwargs)

class SMSLog(models.Model):
    """Individual SMS log"""
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='sms_logs')
    bulk_sms = models.ForeignKey(BulkSMS, on_delete=models.CASCADE, related_name='sms_logs', null=True, blank=True)
    customer = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='sms_logs')
    message = models.TextField()
    status = models.CharField(max_length=20, choices=[
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('delivered', 'Delivered'),
        ('failed', 'Failed')
    ], default='pending')
    status_message = models.TextField(blank=True)
    cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    provider_reference = models.CharField(max_length=100, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['customer', 'status']),
            models.Index(fields=['sent_at']),
        ]
    
    def __str__(self):
        return f"SMS to {self.customer.username} - {self.status}"

class SMSProviderConfig(models.Model):
    """Configuration for SMS providers"""
    PROVIDERS = [
        ('africastalking', 'Africa\'s Talking'),
        ('twilio', 'Twilio'),
        ('smsalert', 'SMS Alert'),
        ('nexmo', 'Vonage (Nexmo)'),
        ('custom', 'Custom API'),
    ]
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='sms_providers')
    provider_name = models.CharField(max_length=50, choices=PROVIDERS, default='africastalking')
    is_active = models.BooleanField(default=True)
    api_key = models.CharField(max_length=255)
    api_secret = models.CharField(max_length=255, blank=True)
    sender_id = models.CharField(max_length=20)
    default_sender = models.CharField(max_length=20, blank=True)
    base_url = models.URLField(blank=True)
    cost_per_sms = models.DecimalField(max_digits=6, decimal_places=4, default=1.0)
    
    # Rate limiting
    max_sms_per_day = models.IntegerField(default=1000)
    sms_sent_today = models.IntegerField(default=0)
    last_reset_date = models.DateField(auto_now_add=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['tenant', 'provider_name']
    
    def __str__(self):
        return f"{self.tenant.name} - {self.get_provider_name_display()}"
    
    def reset_daily_count(self):
        """Reset daily SMS count if it's a new day"""
        today = timezone.now().date()
        if self.last_reset_date != today:
            self.sms_sent_today = 0
            self.last_reset_date = today
            self.save()

class VerificationLog(models.Model):
    """Log for verification-related actions"""
    ACTION_CHOICES = [
        ('verified', 'Verified'),
        ('unverified', 'Unverified'),
        ('document_requested', 'Document Requested'),
        ('status_updated', 'Status Updated'),
        ('paystack_configured', 'PayStack Configured'),
        ('paystack_reset', 'PayStack Reset'),
    ]
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='verification_logs')
    action = models.CharField(max_length=50, choices=ACTION_CHOICES)
    performed_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)
    details = models.JSONField(blank=True, null=True)
    
    class Meta:
        ordering = ['-timestamp']
    
    def __str__(self):
        return f"{self.get_action_display()} - {self.tenant.name} - {self.timestamp}"
    
# In accounts/models.py, add this model
class ActivityLog(models.Model):
    """Log user activities"""
    ACTION_CHOICES = [
        ('login', 'User Login'),
        ('logout', 'User Logout'),
        ('create_user', 'Create User'),
        ('update_user', 'Update User'),
        ('delete_user', 'Delete User'),
        ('mark_payment_completed', 'Mark Payment Completed'),
        ('update_payment_status', 'Update Payment Status'),
        ('delete_payment', 'Delete Payment'),
        ('send_receipt', 'Send Receipt'),
        ('bulk_payment_action', 'Bulk Payment Action'),
        ('create_subscription', 'Create Subscription'),
        ('update_subscription', 'Update Subscription'),
    ]
    
    user = models.ForeignKey(
        CustomUser, 
        on_delete=models.SET_NULL, 
        null=True, 
        related_name='activity_logs'
    )
    action = models.CharField(max_length=50, choices=ACTION_CHOICES)
    details = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Activity Log'
        verbose_name_plural = 'Activity Logs'
    
    def __str__(self):
        return f"{self.user.username if self.user else 'System'} - {self.action} - {self.created_at.strftime('%Y-%m-%d %H:%M')}"