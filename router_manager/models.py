# router_manager/models.py
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
import uuid
from django.db import models
from django.utils import timezone
from datetime import time
from django.contrib.auth import get_user_model
from accounts.models import Tenant, CustomUser

User = get_user_model()


class RouterConfig(models.Model):
    ROUTER_TYPES = [
        ('huawei', 'Huawei'),
        ('tenda', 'Tenda'),
        ('mikrotik', 'MikroTik'),
        ('ubiquiti', 'Ubiquiti'),
        ('tplink', 'TP-Link'),
        ('other', 'Other'),
    ]
    
    HUAWEI_MODELS = [
        ('hg8245h', 'HG8245H'),
        ('hg8245q', 'HG8245Q'),
        ('hg8145v5', 'HG8145V5'),
        ('hs8546v5', 'HS8546V5'),
        ('eg8145v5', 'EG8145V5'),
        ('other_huawei', 'Other Huawei'),
    ]
    
    TENDA_MODELS = [
        ('ac10', 'AC10'),
        ('ac18', 'AC18'),
        ('f3', 'F3'),
        ('f6', 'F6'),
        ('fh456', 'FH456'),
        ('other_tenda', 'Other Tenda'),
    ]
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='router_configs')
    name = models.CharField(max_length=100)
    router_type = models.CharField(max_length=20, choices=ROUTER_TYPES)
    router_model = models.CharField(max_length=50, blank=True)
    ip_address = models.GenericIPAddressField()
    username = models.CharField(max_length=100, default='admin')
    password = models.CharField(max_length=100)
    web_port = models.IntegerField(default=80)
    is_online = models.BooleanField(default=False)
    last_checked = models.DateTimeField(null=True, blank=True)
    
    # Huawei specific
    huawei_ont_id = models.CharField(max_length=50, blank=True)
    
    # Assignment fields
    assigned_to = models.ForeignKey(
        CustomUser, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='assigned_routers',
        verbose_name="Assigned Customer",
        limit_choices_to={'role': 'customer'}  # Only customers can be assigned
    )
    is_available = models.BooleanField(
        default=True, 
        verbose_name="Available for Assignment",
        help_text="Check if this router is available for assignment to customers"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-is_available', '-created_at']
        verbose_name = "Router Configuration"
        verbose_name_plural = "Router Configurations"
    
    def __str__(self):
        if self.assigned_to:
            return f"{self.name} ({self.router_type}) - Assigned to {self.assigned_to.username}"
        return f"{self.name} ({self.router_type})"
    
    def save(self, *args, **kwargs):
        """Override save to update is_available based on assignment"""
        # Auto-update is_available based on assigned_to
        if self.assigned_to:
            self.is_available = False
        else:
            self.is_available = True
        super().save(*args, **kwargs)
    
    def assign_to_customer(self, customer):
        """Assign this router config to a customer"""
        if self.assigned_to and self.assigned_to != customer:
            raise ValueError(f"Router already assigned to {self.assigned_to.username}")
        
        if customer.role != 'customer':
            raise ValueError("Can only assign routers to customers")
        
        # Update router config
        self.assigned_to = customer
        self.save()
        
        # Get or create customer's router
        router, created = Router.objects.get_or_create(
            user=customer,
            defaults={
                'model': f"{self.router_type} {self.router_model}",
                'mac_address': f"00:00:00:00:00:{customer.id:02x}",
                'router_config': self,
                'is_online': self.is_online,
                'tenant': customer.tenant,
                'ssid': f"{customer.username}_Network",
                'password': f"Pass{uuid.uuid4().hex[:8]}",
            }
        )
        
        # Update existing router if found
        if not created:
            router.router_config = self
            router.model = f"{self.router_type} {self.router_model}"
            router.is_online = self.is_online
            router.save()
        
        return router
    
    def unassign(self):
        """Unassign from customer"""
        customer = self.assigned_to
        self.assigned_to = None
        self.save()
        
        # Keep the link but mark as unassigned
        Router.objects.filter(router_config=self).update(router_config=None)
        
        return customer
    
    @property
    def status_display(self):
        """Get display status"""
        if not self.is_available:
            return f"Assigned to {self.assigned_to.username}"
        elif self.is_online:
            return "Online - Available"
        else:
            return "Offline - Available"
    
    @property
    def status_color(self):
        """Get status color for display"""
        if not self.is_available:
            return "warning"
        elif self.is_online:
            return "success"
        else:
            return "danger"


class Router(models.Model):
    SECURITY_TYPES = [
        ('wpa2', 'WPA2-Personal (Recommended)'),
        ('wpa3', 'WPA3-Personal'),
        ('wpa', 'WPA/WPA2-Personal'),
        ('wep', 'WEP (Insecure)'),
        ('none', 'None (Open Network)'),
    ]
    
    BAND_TYPES = [
        ('2.4ghz', '2.4 GHz (Longer range)'),
        ('5ghz', '5 GHz (Faster speed)'),
        ('both', 'Both (Dual-band)'),
    ]
    
    CHANNEL_WIDTHS = [
        ('20mhz', '20 MHz'),
        ('40mhz', '40 MHz'),
        ('80mhz', '80 MHz'),
        ('auto', 'Auto (Recommended)'),
    ]
    
    user = models.OneToOneField(
        CustomUser, 
        on_delete=models.CASCADE, 
        related_name='router'
    )
    tenant = models.ForeignKey(
        Tenant, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='routers'
    )
    
    # Link to ISP router configuration
    router_config = models.ForeignKey(
        RouterConfig, 
        on_delete=models.SET_NULL,
        null=True, 
        blank=True,
        related_name='customer_routers',
        verbose_name="ISP Router Configuration",
        help_text="Link to ISP-managed router configuration"
    )
    
    mac_address = models.CharField(max_length=17, unique=True)
    model = models.CharField(max_length=100)
    ssid = models.CharField(max_length=32, default='ConnectWise_Network')
    password = models.CharField(max_length=64)
    security_type = models.CharField(max_length=10, choices=SECURITY_TYPES, default='wpa2')
    hide_ssid = models.BooleanField(default=False)
    band = models.CharField(max_length=10, choices=BAND_TYPES, default='both')
    channel_width = models.CharField(max_length=10, choices=CHANNEL_WIDTHS, default='auto')
    firewall_enabled = models.BooleanField(default=True)
    remote_access = models.BooleanField(default=False)
    upnp_enabled = models.BooleanField(default=False)
    last_seen = models.DateTimeField(auto_now=True)
    is_online = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.model} - {self.mac_address} ({self.user.email})"
    
    def save(self, *args, **kwargs):
        """Override save to auto-set tenant from user"""
        if not self.tenant and self.user:
            self.tenant = self.user.tenant
        super().save(*args, **kwargs)
    
    @property
    def online_status(self):
        return "Online" if self.is_online else "Offline"
    
    @property
    def security_status(self):
        if self.security_type == 'wpa3':
            return "Excellent"
        elif self.security_type == 'wpa2':
            return "Good"
        elif self.security_type == 'wpa':
            return "Fair"
        else:
            return "Poor"
    
    @property
    def has_isp_config(self):
        """Check if router has ISP configuration"""
        return self.router_config is not None
    
    @property
    def configuration_details(self):
        """Get linked router configuration details"""
        if self.router_config:
            return {
                'name': self.router_config.name,
                'type': self.router_config.get_router_type_display(),
                'model': self.router_config.router_model,
                'ip_address': self.router_config.ip_address,
                'port': self.router_config.web_port,
                'is_online': self.router_config.is_online,
            }
        return None
    
    def sync_with_config(self):
        """Sync router settings with ISP configuration"""
        if not self.router_config:
            return False
        
        # Update online status from config
        self.is_online = self.router_config.is_online
        
        # Auto-generate model name if not set
        if not self.model and self.router_config.router_model:
            self.model = f"{self.router_config.router_type} {self.router_config.router_model}"
        
        self.save()
        return True
    
    def get_configuration_url(self):
        """Get configuration URL if available"""
        if self.router_config:
            return f"http://{self.router_config.ip_address}:{self.router_config.web_port}"
        return None
    
class Device(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='devices')
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='devices')
    router = models.ForeignKey(Router, on_delete=models.CASCADE, related_name='devices')
    
    mac_address = models.CharField(max_length=17)
    ip_address = models.GenericIPAddressField()
    device_name = models.CharField(max_length=255, blank=True)
    device_type = models.CharField(max_length=50, choices=[
        ('computer', 'Computer'),
        ('phone', 'Phone'),
        ('tablet', 'Tablet'),
        ('iot', 'IoT Device'),
        ('other', 'Other'),
    ])
    
    # Status
    is_online = models.BooleanField(default=False)
    is_blocked = models.BooleanField(default=False)
    data_usage = models.FloatField(default=0)  # GB
    last_seen = models.DateTimeField(null=True, blank=True)
    connected_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'devices'
        unique_together = ['tenant', 'mac_address']

    def __str__(self):
        return f"{self.device_name} ({self.mac_address})"


class ConnectedDevice(models.Model):
    DEVICE_TYPES = [
        ('computer', 'Computer'),
        ('phone', 'Phone'),
        ('tablet', 'Tablet'),
        ('tv', 'TV'),
        ('game_console', 'Game Console'),
        ('iot', 'IoT Device'),
        ('other', 'Other'),
    ]
    
    CONNECTION_TYPES = [
        ('wired', 'Wired'),
        ('wireless_2.4', 'Wireless (2.4 GHz)'),
        ('wireless_5', 'Wireless (5 GHz)'),
        ('guest', 'Guest Network'),
    ]
    
    router = models.ForeignKey(Router, on_delete=models.CASCADE, related_name='connected_devices')
    name = models.CharField(max_length=100, blank=True)
    ip_address = models.GenericIPAddressField()
    mac_address = models.CharField(max_length=17)
    device_type = models.CharField(max_length=15, choices=DEVICE_TYPES, default='other')
    connection_type = models.CharField(max_length=15, choices=CONNECTION_TYPES, default='wireless_2.4')
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)
    signal_strength = models.IntegerField(
        validators=[MinValueValidator(-100), MaxValueValidator(0)],
        null=True,
        blank=True,
        help_text="Signal strength in dBm (0 to -100)"
    )
    data_usage = models.BigIntegerField(default=0, help_text="Data usage in bytes")
    blocked = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['-last_seen']
        indexes = [
            models.Index(fields=['router', 'last_seen']),
            models.Index(fields=['mac_address']),
        ]
    
    def __str__(self):
        return f"{self.name or 'Unknown Device'} - {self.ip_address}"
    
    @property
    def is_online(self):
        from django.utils import timezone
        return self.last_seen >= timezone.now() - timezone.timedelta(minutes=5)
    
    @property
    def data_usage_readable(self):
        """Convert bytes to human-readable format"""
        if self.data_usage >= 1024 ** 3:  # GB
            return f"{self.data_usage / (1024 ** 3):.2f} GB"
        elif self.data_usage >= 1024 ** 2:  # MB
            return f"{self.data_usage / (1024 ** 2):.2f} MB"
        elif self.data_usage >= 1024:  # KB
            return f"{self.data_usage / 1024:.2f} KB"
        else:
            return f"{self.data_usage} B"
    
    @property
    def signal_strength_percentage(self):
        """Convert dBm to percentage (approx)"""
        if not self.signal_strength:
            return 0
        # Convert dBm (-100 to 0) to percentage (0% to 100%)
        return max(0, min(100, 2 * (self.signal_strength + 100)))


class RouterLog(models.Model):
    LOG_TYPES = [
        ('config_change', 'Configuration Change'),
        ('reboot', 'Router Reboot'),
        ('firmware_update', 'Firmware Update'),
        ('security_event', 'Security Event'),
        ('connection', 'Connection Event'),
    ]
    
    router = models.ForeignKey(Router, on_delete=models.CASCADE, related_name='logs')
    log_type = models.CharField(max_length=20, choices=LOG_TYPES)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['router', 'created_at']),
        ]
    
    def __str__(self):
        return f"{self.router} - {self.log_type} - {self.created_at}"


class GuestNetwork(models.Model):
    router = models.OneToOneField(Router, on_delete=models.CASCADE, related_name='guest_network')
    ssid = models.CharField(max_length=32, default='ConnectWise_Guest')
    password = models.CharField(max_length=64, blank=True)
    enabled = models.BooleanField(default=False)
    bandwidth_limit = models.PositiveIntegerField(
        default=10,
        help_text="Bandwidth limit in Mbps"
    )
    access_duration = models.PositiveIntegerField(
        default=24,
        help_text="Access duration in hours"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Guest Network - {self.router}"


class PortForwardingRule(models.Model):
    router = models.ForeignKey(Router, on_delete=models.CASCADE, related_name='port_rules')  # FIXED: Changed from RouterConfig to Router
    customer = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='port_rules')
    external_port = models.IntegerField()
    internal_ip = models.GenericIPAddressField()
    internal_port = models.IntegerField()
    protocol = models.CharField(max_length=10, choices=[('tcp', 'TCP'), ('udp', 'UDP'), ('both', 'Both')])
    is_active = models.BooleanField(default=True)
    description = models.CharField(max_length=200)
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'port_forwarding_rules'

    def __str__(self):
        return f"{self.external_port} -> {self.internal_ip}:{self.internal_port}"


class FirmwareUpdate(models.Model):
    """Model for firmware updates"""
    STATUS_CHOICES = [
        ('available', 'Available'),
        ('downloading', 'Downloading'),
        ('installing', 'Installing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('scheduled', 'Scheduled'),
    ]
    
    router = models.ForeignKey('Router', on_delete=models.CASCADE, related_name='firmware_updates')
    version = models.CharField(max_length=20)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='available')
    changelog = models.TextField(blank=True)
    download_size = models.CharField(max_length=20, blank=True)
    release_date = models.DateField(null=True, blank=True)
    scheduled_for = models.DateTimeField(null=True, blank=True)
    installed_at = models.DateTimeField(null=True, blank=True)
    auto_update = models.BooleanField(default=False)
    requires_reboot = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-release_date', '-created_at']
    
    def __str__(self):
        return f"{self.version} - {self.router}"
    
    @property
    def is_latest(self):
        """Check if this is the latest version for this router"""
        latest = FirmwareUpdate.objects.filter(
            router=self.router
        ).exclude(id=self.id).order_by('-release_date').first()
        
        if not latest:
            return True
        
        return self.release_date >= latest.release_date if self.release_date and latest.release_date else False


class ParentalControlSchedule(models.Model):
    """Model for parental control schedules"""
    SCHEDULE_TYPES = [
        ('time', 'Time-based'),
        ('always', 'Always Block'),
        ('bedtime', 'Bedtime'),
        ('study', 'Study Time'),
        ('custom', 'Custom'),
    ]
    
    router = models.ForeignKey('Router', on_delete=models.CASCADE, related_name='parental_schedules')
    name = models.CharField(max_length=100)
    schedule_type = models.CharField(max_length=20, choices=SCHEDULE_TYPES, default='time')
    
    # Time settings
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    days = models.JSONField(default=list)  # List of days: ['mon', 'tue', etc.]
    
    # Content filtering
    block_social_media = models.BooleanField(default=False)
    block_gaming = models.BooleanField(default=False)
    block_streaming = models.BooleanField(default=False)
    custom_sites = models.JSONField(default=list, blank=True)  # List of custom sites to block
    
    # Device targeting
    devices = models.ManyToManyField('ConnectedDevice', related_name='parental_schedules', blank=True)
    apply_to_all = models.BooleanField(default=True)
    
    # Status
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-is_active', '-created_at']
    
    def __str__(self):
        return f"{self.name} - {self.router}"
    
    @property
    def is_active_now(self):
        """Check if schedule is active based on current time"""
        if not self.is_active:
            return False
        
        now = timezone.now()
        current_time = now.time()
        current_day = now.strftime('%a').lower()[:3]  # 'mon', 'tue', etc.
        
        # Check if today is in schedule days
        if current_day not in self.days:
            return False
        
        # For 'always' type, always active
        if self.schedule_type == 'always':
            return True
        
        # For bedtime (overnight) schedules
        if self.schedule_type == 'bedtime':
            return self.start_time <= current_time or current_time <= self.end_time
        
        # For normal time-based schedules
        if self.start_time and self.end_time:
            if self.start_time < self.end_time:
                # Normal schedule (e.g., 4 PM to 6 PM)
                return self.start_time <= current_time <= self.end_time
            else:
                # Overnight schedule (e.g., 9 PM to 7 AM)
                return self.start_time <= current_time or current_time <= self.end_time
        
        return False
    
    def get_days_display(self):
        """Get human-readable days string"""
        day_map = {
            'mon': 'Monday',
            'tue': 'Tuesday',
            'wed': 'Wednesday',
            'thu': 'Thursday',
            'fri': 'Friday',
            'sat': 'Saturday',
            'sun': 'Sunday',
        }
        return ', '.join(day_map.get(day, day) for day in self.days)