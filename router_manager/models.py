# router_manager/models.py
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from accounts.models import Tenant, CustomUser
import uuid


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
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='router_configs')  # Changed related_name
    name = models.CharField(max_length=100)
    router_type = models.CharField(max_length=20, choices=ROUTER_TYPES)
    router_model = models.CharField(max_length=50, blank=True)
    ip_address = models.GenericIPAddressField()
    username = models.CharField(max_length=100, default='admin')
    password = models.CharField(max_length=100)
    web_port = models.IntegerField(default=80)
    is_online = models.BooleanField(default=False)
    last_checked = models.DateTimeField(null=True, blank=True)  # Added this field
    
    # Huawei specific
    huawei_ont_id = models.CharField(max_length=50, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.name} ({self.router_type})"


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
    
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='router')
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


class Device(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='devices')
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='devices')
    router = models.ForeignKey(Router, on_delete=models.CASCADE, related_name='devices')  # FIXED: Changed from RouterConfig to Router
    
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
    
    router = models.ForeignKey(Router, on_delete=models.CASCADE, related_name='connected_devices')  # Changed related_name
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
    router = models.ForeignKey(RouterConfig, on_delete=models.CASCADE, related_name='port_rules')
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