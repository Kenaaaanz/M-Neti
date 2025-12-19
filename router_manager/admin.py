from django.contrib import admin
from django.utils.html import format_html
from .models import RouterConfig, Device, PortForwardingRule, Router, ConnectedDevice, RouterLog, GuestNetwork

@admin.register(RouterConfig)
class RouterConfigAdmin(admin.ModelAdmin):
    list_display = ['name', 'tenant', 'router_type', 'router_model', 'ip_address', 'is_online']
    list_filter = ['router_type', 'is_online', 'tenant']
    search_fields = ['name', 'ip_address']
    readonly_fields = ['created_at']

@admin.register(Router)
class RouterAdmin(admin.ModelAdmin):
    list_display = ('user', 'model', 'mac_address', 'ssid', 'online_status', 'security_status', 'created_at')
    list_filter = ('model', 'is_online', 'security_type', 'band', 'created_at')
    search_fields = ('user__email', 'user__username', 'mac_address', 'ssid', 'model')
    readonly_fields = ('created_at', 'updated_at', 'last_seen')
    fieldsets = (
        ('Basic Information', {
            'fields': ('user', 'model', 'mac_address')
        }),
        ('WiFi Settings', {
            'fields': ('ssid', 'password', 'security_type', 'hide_ssid', 'band', 'channel_width')
        }),
        ('Security Settings', {
            'fields': ('firewall_enabled', 'remote_access', 'upnp_enabled')
        }),
        ('Status', {
            'fields': ('is_online', 'last_seen', 'created_at', 'updated_at')
        }),
    )
    
    def online_status(self, obj):
        color = 'green' if obj.is_online else 'red'
        return format_html('<span style="color: {};">{}</span>', color, obj.online_status)
    online_status.short_description = 'Status'
    
    def security_status(self, obj):
        color_map = {
            'Excellent': 'green',
            'Good': 'blue',
            'Fair': 'orange',
            'Poor': 'red'
        }
        color = color_map.get(obj.security_status, 'black')
        return format_html('<span style="color: {};">{}</span>', color, obj.security_status)
    security_status.short_description = 'Security'

@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ['device_name', 'user', 'tenant', 'router', 'device_type', 'is_online', 'is_blocked']
    list_filter = ['tenant', 'device_type', 'is_online', 'is_blocked']
    search_fields = ['device_name', 'mac_address', 'ip_address']
    readonly_fields = ['created_at']

@admin.register(ConnectedDevice)
class ConnectedDeviceAdmin(admin.ModelAdmin):
    list_display = ('name', 'router', 'ip_address', 'device_type', 'is_online', 'blocked', 'last_seen')
    list_filter = ('device_type', 'connection_type', 'blocked', 'is_active', 'router')
    search_fields = ('name', 'ip_address', 'mac_address', 'router__ssid')
    readonly_fields = ('first_seen', 'last_seen', 'data_usage_readable', 'signal_strength_percentage')
    list_editable = ('blocked',)
    fieldsets = (
        ('Device Identification', {
            'fields': ('name', 'router', 'device_type')
        }),
        ('Network Information', {
            'fields': ('ip_address', 'mac_address', 'connection_type')
        }),
        ('Status', {
            'fields': ('is_active', 'blocked', 'signal_strength', 'signal_strength_percentage')
        }),
        ('Usage', {
            'fields': ('data_usage', 'data_usage_readable', 'first_seen', 'last_seen')
        }),
    )
    
    def is_online(self, obj):
        color = 'green' if obj.is_online else 'red'
        status = 'Online' if obj.is_online else 'Offline'
        return format_html('<span style="color: {};">{}</span>', color, status)
    is_online.short_description = 'Online'

@admin.register(RouterLog)
class RouterLogAdmin(admin.ModelAdmin):
    list_display = ('router', 'log_type', 'short_message', 'created_at')
    list_filter = ('log_type', 'created_at', 'router')
    search_fields = ('message', 'router__ssid', 'router__user__email')
    readonly_fields = ('created_at',)
    
    def short_message(self, obj):
        return obj.message[:50] + '...' if len(obj.message) > 50 else obj.message
    short_message.short_description = 'Message'

@admin.register(GuestNetwork)
class GuestNetworkAdmin(admin.ModelAdmin):
    list_display = ('router', 'ssid', 'enabled', 'bandwidth_limit', 'access_duration')
    list_filter = ('enabled', 'created_at')
    search_fields = ('ssid', 'router__ssid', 'router__user__email')
    readonly_fields = ('created_at', 'updated_at')

@admin.register(PortForwardingRule)
class PortForwardingRuleAdmin(admin.ModelAdmin):
    list_display = ['customer', 'router', 'external_port', 'internal_ip', 'internal_port', 'is_active']
    list_filter = ['is_active', 'protocol', 'router']
    search_fields = ['customer__username', 'internal_ip']
    readonly_fields = ['created_at']