from django import forms
from django.core.validators import validate_ipv46_address, MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from .models import Router, GuestNetwork, RouterConfig, PortForwardingRule, ConnectedDevice
from accounts.models import CustomUser
import re


class RouterForm(forms.ModelForm):
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'w-full pl-10 pr-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition',
            'placeholder': 'Confirm WiFi password'
        }),
        required=False,
        help_text="Re-enter the WiFi password to confirm"
    )
    
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'w-full pl-10 pr-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition',
            'placeholder': 'WiFi Password',
            'render_value': True
        }),
        min_length=8,
        help_text="Minimum 8 characters. Use a mix of letters, numbers, and symbols."
    )
    
    class Meta:
        model = Router
        fields = ['mac_address', 'model', 'ssid', 'password', 'security_type', 
                 'hide_ssid', 'band', 'channel_width', 'firewall_enabled', 
                 'remote_access', 'upnp_enabled']
        widgets = {
            'mac_address': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition',
                'placeholder': 'AA:BB:CC:DD:EE:FF',
                'pattern': '^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$'
            }),
            'model': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition',
                'placeholder': 'Router Model'
            }),
            'ssid': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition',
                'placeholder': 'Network Name',
                'maxlength': '32'
            }),
            'security_type': forms.Select(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition'
            }),
            'band': forms.Select(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition'
            }),
            'channel_width': forms.Select(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition'
            }),
            'hide_ssid': forms.CheckboxInput(attrs={
                'class': 'form-checkbox h-5 w-5 text-blue-600 rounded focus:ring-blue-500'
            }),
            'firewall_enabled': forms.CheckboxInput(attrs={
                'class': 'form-checkbox h-5 w-5 text-blue-600 rounded focus:ring-blue-500'
            }),
            'remote_access': forms.CheckboxInput(attrs={
                'class': 'form-checkbox h-5 w-5 text-blue-600 rounded focus:ring-blue-500'
            }),
            'upnp_enabled': forms.CheckboxInput(attrs={
                'class': 'form-checkbox h-5 w-5 text-blue-600 rounded focus:ring-blue-500'
            }),
        }
        help_texts = {
            'mac_address': 'Format: AA:BB:CC:DD:EE:FF or AA-BB-CC-DD-EE-FF',
            'ssid': 'Maximum 32 characters',
            'hide_ssid': 'Makes your network invisible to others',
            'remote_access': 'Warning: Enabling remote access can be a security risk',
            'upnp_enabled': 'Allows automatic port forwarding (can be a security risk)',
        }
    
    def clean_mac_address(self):
        mac_address = self.cleaned_data.get('mac_address')
        if mac_address:
            # Validate MAC address format
            mac_pattern = r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$'
            if not re.match(mac_pattern, mac_address):
                raise forms.ValidationError(
                    'Invalid MAC address format. Use format: AA:BB:CC:DD:EE:FF'
                )
        return mac_address
    
    def clean_password(self):
        password = self.cleaned_data.get('password')
        if password and len(password) < 8:
            raise forms.ValidationError('Password must be at least 8 characters long')
        return password
    
    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        confirm_password = cleaned_data.get('confirm_password')
        
        if password and confirm_password and password != confirm_password:
            raise forms.ValidationError("Passwords don't match")
        
        # Security warning for poor security choices
        security_type = cleaned_data.get('security_type')
        if security_type in ['wep', 'none']:
            self.add_warning('security_type', 
                'WARNING: Using WEP or no security makes your network vulnerable to attacks!')
        
        return cleaned_data
    
    def add_warning(self, field, message):
        """Add a warning message to a specific field"""
        if field not in self._errors:
            self._errors[field] = self.error_class()
        self._errors[field].append(message)


class GuestNetworkForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'w-full pl-10 pr-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition',
            'placeholder': 'Guest Password',
            'render_value': True
        }),
        required=False,
        min_length=8
    )
    
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'w-full pl-10 pr-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition',
            'placeholder': 'Confirm Guest Password'
        }),
        required=False
    )
    
    class Meta:
        model = GuestNetwork
        fields = ['ssid', 'password', 'enabled', 'bandwidth_limit', 'access_duration']
        widgets = {
            'ssid': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition',
                'placeholder': 'Guest Network Name',
                'maxlength': '32'
            }),
            'enabled': forms.CheckboxInput(attrs={
                'class': 'form-checkbox h-5 w-5 text-blue-600 rounded focus:ring-blue-500'
            }),
            'bandwidth_limit': forms.NumberInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition',
                'min': 1,
                'max': 1000,
                'step': 1
            }),
            'access_duration': forms.NumberInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition',
                'min': 1,
                'max': 744,  # 31 days * 24 hours
                'step': 1
            }),
        }
        help_texts = {
            'ssid': 'Maximum 32 characters',
            'password': 'Leave blank for open guest network (not recommended)',
            'bandwidth_limit': 'Maximum download/upload speed in Mbps',
            'access_duration': 'Hours before guest access expires (1-744)',
        }
    
    def clean_password(self):
        password = self.cleaned_data.get('password')
        if password and len(password) < 8:
            raise forms.ValidationError('Password must be at least 8 characters long')
        return password
    
    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        confirm_password = cleaned_data.get('confirm_password')
        
        if password and confirm_password and password != confirm_password:
            raise forms.ValidationError("Passwords don't match")
        
        # Warning if no password is set
        enabled = cleaned_data.get('enabled')
        if enabled and not password:
            self.add_warning('password', 
                'WARNING: Guest network will be open (no password required).')
        
        return cleaned_data


class AdvancedSettingsForm(forms.ModelForm):
    class Meta:
        model = Router
        fields = ['hide_ssid', 'channel_width', 'band']
        widgets = {
            'hide_ssid': forms.CheckboxInput(attrs={
                'class': 'form-checkbox h-5 w-5 text-blue-600 rounded focus:ring-blue-500'
            }),
            'channel_width': forms.Select(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition'
            }),
            'band': forms.Select(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition'
            }),
        }
        help_texts = {
            'hide_ssid': 'Hides your network from device scans (more secure but less convenient)',
            'channel_width': 'Wider channels = faster speeds but more interference',
            'band': '5GHz = faster, shorter range; 2.4GHz = slower, longer range',
        }


class WiFiPasswordForm(forms.ModelForm):
    current_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'w-full pl-10 pr-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition',
            'placeholder': 'Current WiFi password'
        }),
        required=True,
        help_text="Enter your current WiFi password"
    )
    
    new_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'w-full pl-10 pr-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition',
            'placeholder': 'New WiFi Password'
        }),
        min_length=8,
        help_text="Minimum 8 characters. Use a mix of letters, numbers, and symbols."
    )
    
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'w-full pl-10 pr-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition',
            'placeholder': 'Confirm new WiFi password'
        }),
        required=True,
        help_text="Re-enter the new WiFi password"
    )
    
    class Meta:
        model = Router
        fields = ['password']
        widgets = {
            'password': forms.PasswordInput(attrs={
                'class': 'w-full pl-10 pr-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition',
                'placeholder': 'New WiFi Password'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        # Don't show the default password field
        self.fields.pop('password')
    
    def clean_new_password(self):
        new_password = self.cleaned_data.get('new_password')
        if new_password and len(new_password) < 8:
            raise forms.ValidationError('New password must be at least 8 characters long')
        return new_password
    
    def clean(self):
        cleaned_data = super().clean()
        current_password = cleaned_data.get('current_password')
        new_password = cleaned_data.get('new_password')
        confirm_password = cleaned_data.get('confirm_password')
        
        # Check if current password is correct
        if self.user and hasattr(self.user, 'router'):
            router = self.user.router
            if current_password != router.password:
                raise forms.ValidationError('Current password is incorrect')
        
        # Check if new passwords match
        if new_password and confirm_password and new_password != confirm_password:
            raise forms.ValidationError("New passwords don't match")
        
        # Check if new password is different from current
        if current_password and new_password and current_password == new_password:
            raise forms.ValidationError('New password must be different from current password')
        
        # Update the password field for model saving
        if new_password:
            cleaned_data['password'] = new_password
        
        return cleaned_data

# router_manager/forms.py - Add these forms
from django import forms
from django.utils import timezone
from datetime import timedelta
from .models import FirmwareUpdate, ParentalControlSchedule, Router
import re

class FirmwareUpdateForm(forms.ModelForm):
    """Form for scheduling firmware updates"""
    
    schedule_type = forms.ChoiceField(
        choices=[
            ('now', 'Install Now'),
            ('schedule', 'Schedule Later'),
            ('custom', 'Custom Time'),
        ],
        widget=forms.RadioSelect(attrs={'class': 'space-y-2'}),
        initial='now',
        label="When to Update"
    )
    
    scheduled_date = forms.DateField(
        widget=forms.DateInput(
            attrs={
                'type': 'date',
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition',
                'min': timezone.now().date().isoformat(),
            }
        ),
        required=False,
        label="Date"
    )
    
    scheduled_time = forms.ChoiceField(
        choices=[
            ('02:00', '2:00 AM (Recommended)'),
            ('03:00', '3:00 AM'),
            ('04:00', '4:00 AM'),
            ('custom', 'Custom Time'),
        ],
        widget=forms.Select(attrs={
            'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition'
        }),
        required=False,
        label="Time"
    )
    
    custom_time = forms.TimeField(
        widget=forms.TimeInput(
            attrs={
                'type': 'time',
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition',
            }
        ),
        required=False,
        label="Custom Time"
    )
    
    auto_reboot = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-checkbox h-5 w-5 text-blue-600 rounded focus:ring-blue-500'
        }),
        label="Auto-reboot after update"
    )
    
    backup_settings = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-checkbox h-5 w-5 text-blue-600 rounded focus:ring-blue-500'
        }),
        label="Backup router settings before update"
    )
    
    notify_customer = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-checkbox h-5 w-5 text-blue-600 rounded focus:ring-blue-500'
        }),
        label="Notify customer when update starts"
    )
    
    class Meta:
        model = FirmwareUpdate
        fields = ['version', 'changelog', 'download_size']
        widgets = {
            'version': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition',
                'placeholder': 'e.g., 2.2.0',
                'pattern': r'^\d+\.\d+\.\d+$'
            }),
            'changelog': forms.Textarea(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition',
                'rows': 5,
                'placeholder': 'Enter update details...\n• Security patches\n• Performance improvements\n• Bug fixes'
            }),
            'download_size': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition',
                'placeholder': 'e.g., 42.5 MB'
            }),
        }
        help_texts = {
            'version': 'Format: X.Y.Z (e.g., 2.2.0)',
            'changelog': 'List all changes in this update',
            'download_size': 'File size with unit (e.g., 42.5 MB)',
        }
    
    def __init__(self, *args, **kwargs):
        self.router = kwargs.pop('router', None)
        super().__init__(*args, **kwargs)
        
        # Set minimum date for scheduling
        today = timezone.now().date()
        tomorrow = today + timedelta(days=1)
        
        if 'scheduled_date' in self.fields:
            self.fields['scheduled_date'].widget.attrs['min'] = tomorrow.isoformat()
            self.fields['scheduled_date'].initial = tomorrow
    
    def clean_version(self):
        """Validate version format"""
        version = self.cleaned_data.get('version')
        if version:
            # Validate version format (X.Y.Z)
            if not re.match(r'^\d+\.\d+\.\d+$', version):
                raise forms.ValidationError('Version must be in format X.Y.Z (e.g., 2.2.0)')
        return version
    
    def clean_download_size(self):
        """Validate download size format"""
        size = self.cleaned_data.get('download_size')
        if size:
            # Validate format like "42.5 MB" or "1.2 GB"
            if not re.match(r'^\d+(\.\d+)?\s*(KB|MB|GB)$', size.upper()):
                raise forms.ValidationError('Size must be in format like "42.5 MB" or "1.2 GB"')
        return size
    
    def clean(self):
        """Validate the complete form"""
        cleaned_data = super().clean()
        schedule_type = cleaned_data.get('schedule_type')
        
        if schedule_type == 'schedule':
            # Validate date is set
            if not cleaned_data.get('scheduled_date'):
                self.add_error('scheduled_date', 'Date is required for scheduled updates')
            
            # Validate time is set
            if not cleaned_data.get('scheduled_time'):
                self.add_error('scheduled_time', 'Time is required for scheduled updates')
            
            if cleaned_data.get('scheduled_time') == 'custom' and not cleaned_data.get('custom_time'):
                self.add_error('custom_time', 'Custom time is required when selected')
        
        elif schedule_type == 'custom':
            # Both date and custom time are required
            if not cleaned_data.get('scheduled_date'):
                self.add_error('scheduled_date', 'Date is required')
            if not cleaned_data.get('custom_time'):
                self.add_error('custom_time', 'Time is required')
        
        return cleaned_data
    
    def get_scheduled_datetime(self):
        """Calculate the scheduled datetime based on form data"""
        schedule_type = self.cleaned_data.get('schedule_type')
        
        if schedule_type == 'now':
            return timezone.now()
        
        elif schedule_type == 'schedule':
            date = self.cleaned_data.get('scheduled_date')
            time_choice = self.cleaned_data.get('scheduled_time')
            
            if time_choice == 'custom':
                custom_time = self.cleaned_data.get('custom_time')
                if date and custom_time:
                    return timezone.make_aware(
                        timezone.datetime.combine(date, custom_time)
                    )
            elif time_choice and date:
                hour = int(time_choice.split(':')[0])
                return timezone.make_aware(
                    timezone.datetime.combine(date, timezone.time(hour=hour, minute=0))
                )
        
        elif schedule_type == 'custom':
            date = self.cleaned_data.get('scheduled_date')
            custom_time = self.cleaned_data.get('custom_time')
            if date and custom_time:
                return timezone.make_aware(
                    timezone.datetime.combine(date, custom_time)
                )
        
        return None


class ParentalControlForm(forms.ModelForm):
    """Form for creating parental control schedules"""
    
    DAY_CHOICES = [
        ('mon', 'Monday'),
        ('tue', 'Tuesday'),
        ('wed', 'Wednesday'),
        ('thu', 'Thursday'),
        ('fri', 'Friday'),
        ('sat', 'Saturday'),
        ('sun', 'Sunday'),
    ]
    
    # Multiple device selection
    devices = forms.ModelMultipleChoiceField(
        queryset=None,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'space-y-2'}),
        required=True,
        label="Apply to Devices"
    )
    
    # Days of week as checkboxes
    days = forms.MultipleChoiceField(
        choices=DAY_CHOICES,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'grid grid-cols-4 gap-2'}),
        required=True,
        label="Days of Week"
    )
    
    # Time ranges
    start_time = forms.TimeField(
        widget=forms.TimeInput(attrs={
            'type': 'time',
            'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition',
        }),
        label="Start Time"
    )
    
    end_time = forms.TimeField(
        widget=forms.TimeInput(attrs={
            'type': 'time',
            'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition',
        }),
        label="End Time"
    )
    
    # Content filtering options
    block_social_media = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-checkbox h-5 w-5 text-blue-600 rounded focus:ring-blue-500'
        }),
        label="Block social media"
    )
    
    block_gaming = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-checkbox h-5 w-5 text-blue-600 rounded focus:ring-blue-500'
        }),
        label="Block online gaming"
    )
    
    block_streaming = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-checkbox h-5 w-5 text-blue-600 rounded focus:ring-blue-500'
        }),
        label="Block video streaming"
    )
    
    custom_sites = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition',
            'rows': 3,
            'placeholder': 'Enter websites to block (one per line)\ne.g., facebook.com\nyoutube.com\ninstagram.com'
        }),
        help_text="Enter one website per line (without http://)",
        label="Custom Websites to Block"
    )
    
    # Schedule type
    schedule_type = forms.ChoiceField(
        choices=[
            ('time', 'Time-based Schedule'),
            ('always', 'Always Block (Permanent)'),
            ('bedtime', 'Bedtime Schedule'),
            ('study', 'Study Time'),
        ],
        widget=forms.Select(attrs={
            'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition'
        }),
        initial='time',
        label="Schedule Type"
    )
    
    class Meta:
        model = ParentalControlSchedule
        fields = ['name', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition',
                'placeholder': 'e.g., Bedtime Schedule, Study Time, Weekend Rules'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-checkbox h-5 w-5 text-blue-600 rounded focus:ring-blue-500'
            }),
        }
        help_texts = {
            'name': 'Give this schedule a descriptive name',
        }
    
    def __init__(self, *args, **kwargs):
        self.router = kwargs.pop('router', None)
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        if self.router and hasattr(self.router, 'connected_devices'):
            # Set queryset for devices
            self.fields['devices'].queryset = self.router.connected_devices.filter(
                is_active=True, 
                blocked=False
            )
        
        # Set initial times based on schedule type
        if 'initial' not in kwargs:
            self.fields['start_time'].initial = timezone.time(21, 0)  # 9:00 PM
            self.fields['end_time'].initial = timezone.time(7, 0)    # 7:00 AM
            self.fields['days'].initial = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
    
    def clean(self):
        """Validate the complete form"""
        cleaned_data = super().clean()
        start_time = cleaned_data.get('start_time')
        end_time = cleaned_data.get('end_time')
        schedule_type = cleaned_data.get('schedule_type')
        
        # For time-based schedules, validate time range
        if schedule_type == 'time' and start_time and end_time:
            if start_time >= end_time:
                # Allow overnight schedules (e.g., 9 PM to 7 AM)
                # Only show error if it's not an overnight schedule
                if start_time.hour < 12 and end_time.hour > 12:
                    # This is likely an overnight schedule, which is valid
                    pass
                else:
                    self.add_error('end_time', 'End time must be after start time')
        
        # Validate custom websites
        custom_sites = cleaned_data.get('custom_sites', '')
        if custom_sites:
            sites = [site.strip() for site in custom_sites.split('\n') if site.strip()]
            for site in sites:
                if '://' in site:
                    self.add_error('custom_sites', f'Remove http:// or https:// from: {site}')
                elif ' ' in site:
                    self.add_error('custom_sites', f'No spaces allowed in URL: {site}')
        
        return cleaned_data
    
    def clean_days(self):
        """Ensure at least one day is selected"""
        days = self.cleaned_data.get('days')
        if not days:
            raise forms.ValidationError("Select at least one day")
        return days
    
    def clean_devices(self):
        """Ensure at least one device is selected"""
        devices = self.cleaned_data.get('devices')
        if not devices:
            raise forms.ValidationError("Select at least one device")
        return devices
    
    def save(self, commit=True):
        """Save the form with additional data"""
        instance = super().save(commit=False)
        
        if self.router:
            instance.router = self.router
        
        # Set days as JSON
        instance.days = self.cleaned_data.get('days', [])
        
        # Set times based on schedule type
        schedule_type = self.cleaned_data.get('schedule_type')
        
        if schedule_type == 'always':
            # Always block - set times to cover entire day
            instance.start_time = timezone.time(0, 0)
            instance.end_time = timezone.time(23, 59)
            instance.days = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
        
        elif schedule_type == 'bedtime':
            # Bedtime schedule: 9 PM to 7 AM
            instance.start_time = timezone.time(21, 0)
            instance.end_time = timezone.time(7, 0)
        
        elif schedule_type == 'study':
            # Study time: 4 PM to 6 PM
            instance.start_time = timezone.time(16, 0)
            instance.end_time = timezone.time(18, 0)
        
        else:
            # Use custom times
            instance.start_time = self.cleaned_data.get('start_time')
            instance.end_time = self.cleaned_data.get('end_time')
        
        if commit:
            instance.save()
            # Save many-to-many relationships
            self.save_m2m()
        
        return instance
    
    def get_content_filters(self):
        """Extract content filtering settings from form"""
        return {
            'block_social_media': self.cleaned_data.get('block_social_media', False),
            'block_gaming': self.cleaned_data.get('block_gaming', False),
            'block_streaming': self.cleaned_data.get('block_streaming', False),
            'custom_sites': [site.strip() for site in self.cleaned_data.get('custom_sites', '').split('\n') if site.strip()],
        }


class QuickParentalControlForm(forms.Form):
    """Quick form for basic parental controls"""
    
    ACTION_CHOICES = [
        ('pause', 'Pause Internet'),
        ('resume', 'Resume Internet'),
        ('block_social', 'Block Social Media'),
        ('block_games', 'Block Games'),
        ('bedtime', 'Enable Bedtime Mode'),
    ]
    
    action = forms.ChoiceField(
        choices=ACTION_CHOICES,
        widget=forms.Select(attrs={
            'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition'
        }),
        label="Action"
    )
    
    duration = forms.ChoiceField(
        choices=[
            ('1', '1 Hour'),
            ('3', '3 Hours'),
            ('6', '6 Hours'),
            ('24', '24 Hours'),
            ('permanent', 'Until I resume'),
        ],
        widget=forms.Select(attrs={
            'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition'
        }),
        required=False,
        label="Duration"
    )
    
    devices = forms.ModelMultipleChoiceField(
        queryset=None,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'space-y-2'}),
        required=True,
        label="Apply to Devices"
    )
    
    def __init__(self, *args, **kwargs):
        self.router = kwargs.pop('router', None)
        super().__init__(*args, **kwargs)
        
        if self.router and hasattr(self.router, 'connected_devices'):
            self.fields['devices'].queryset = self.router.connected_devices.filter(
                is_active=True, 
                blocked=False
            )
    
    def clean(self):
        cleaned_data = super().clean()
        action = cleaned_data.get('action')
        duration = cleaned_data.get('duration')
        
        # Duration is required for pause actions
        if action == 'pause' and not duration:
            self.add_error('duration', 'Duration is required when pausing internet')
        
        return cleaned_data


class FirmwareCheckForm(forms.Form):
    """Form for checking firmware updates"""
    
    check_type = forms.ChoiceField(
        choices=[
            ('auto', 'Check Automatically'),
            ('manual', 'Manual Check'),
            ('specific', 'Check Specific Version'),
        ],
        widget=forms.RadioSelect(attrs={'class': 'space-y-2'}),
        initial='auto',
        label="Check Type"
    )
    
    specific_version = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition',
            'placeholder': 'e.g., 2.2.0',
            'pattern': r'^\d+\.\d+\.\d+$'
        }),
        label="Specific Version"
    )
    
    include_beta = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-checkbox h-5 w-5 text-blue-600 rounded focus:ring-blue-500'
        }),
        label="Include beta releases"
    )
    
    notify_on_update = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-checkbox h-5 w-5 text-blue-600 rounded focus:ring-blue-500'
        }),
        label="Notify me when updates are available"
    )
    
    auto_download = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-checkbox h-5 w-5 text-blue-600 rounded focus:ring-blue-500'
        }),
        label="Auto-download updates"
    )
    
    def clean_specific_version(self):
        """Validate specific version format"""
        version = self.cleaned_data.get('specific_version')
        check_type = self.data.get('check_type')
        
        if check_type == 'specific' and not version:
            raise forms.ValidationError('Version is required for specific version check')
        
        if version and not re.match(r'^\d+\.\d+\.\d+$', version):
            raise forms.ValidationError('Version must be in format X.Y.Z (e.g., 2.2.0)')
        
        return version

# ISP-facing forms
class ISPAddRouterForm(forms.ModelForm):
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'w-full px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
            'placeholder': 'Confirm router password'
        }),
        required=True,
        label="Confirm Password"
    )
    
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'w-full px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
            'placeholder': 'Router admin password',
            'render_value': True
        }),
        min_length=6,
        help_text="Minimum 6 characters"
    )
    
    class Meta:
        model = RouterConfig
        fields = ['name', 'router_type', 'router_model', 'ip_address', 'username', 'password', 'web_port']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                'placeholder': 'e.g., Main Office Router'
            }),
            'router_type': forms.Select(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-blue-500'
            }),
            'router_model': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                'placeholder': 'e.g., HG8245H'
            }),
            'ip_address': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                'placeholder': 'e.g., 192.168.1.1'
            }),
            'username': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                'value': 'admin'
            }),
            'web_port': forms.NumberInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                'value': 80,
                'min': 1,
                'max': 65535
            }),
        }
        help_texts = {
            'ip_address': 'Router\'s management IP address',
            'web_port': 'Router\'s web interface port (1-65535)',
            'router_type': 'Select the router manufacturer',
        }
    
    def clean_ip_address(self):
        ip_address = self.cleaned_data.get('ip_address')
        if ip_address:
            try:
                validate_ipv46_address(ip_address)
            except forms.ValidationError:
                raise forms.ValidationError("Invalid IP address format")
        return ip_address
    
    def clean_web_port(self):
        web_port = self.cleaned_data.get('web_port')
        if web_port and (web_port < 1 or web_port > 65535):
            raise forms.ValidationError("Port must be between 1 and 65535")
        return web_port
    
    def clean_password(self):
        password = self.cleaned_data.get('password')
        if password and len(password) < 6:
            raise forms.ValidationError('Password must be at least 6 characters long')
        return password
    
    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        confirm_password = cleaned_data.get('confirm_password')
        
        if password and confirm_password and password != confirm_password:
            raise forms.ValidationError("Passwords don't match")
        
        return cleaned_data


class ISPPortForwardingForm(forms.ModelForm):
    external_port = forms.IntegerField(
        widget=forms.NumberInput(attrs={
            'class': 'w-full px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
            'min': 1024,
            'max': 65535,
            'value': 8080
        }),
        validators=[MinValueValidator(1024), MaxValueValidator(65535)],
        help_text="Port visible from internet (1024-65535)"
    )
    
    internal_port = forms.IntegerField(
        widget=forms.NumberInput(attrs={
            'class': 'w-full px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
            'min': 1,
            'max': 65535,
            'value': 80
        }),
        validators=[MinValueValidator(1), MaxValueValidator(65535)],
        help_text="Port on the internal device (1-65535)"
    )
    
    customer = forms.ModelChoiceField(
        queryset=CustomUser.objects.none(),
        widget=forms.Select(attrs={
            'class': 'w-full px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-blue-500'
        }),
        required=True,
        label="Customer",
        help_text="Select the customer who needs port forwarding"
    )
    
    class Meta:
        model = PortForwardingRule
        fields = ['customer', 'internal_ip', 'internal_port', 'external_port', 'protocol', 'description']
        widgets = {
            'internal_ip': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                'placeholder': 'e.g., 192.168.1.100'
            }),
            'protocol': forms.Select(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-blue-500'
            }),
            'description': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                'placeholder': 'e.g., Web Server Access'
            }),
        }
        help_texts = {
            'internal_ip': 'IP address of the device inside the network',
            'protocol': 'TCP, UDP, or both',
            'description': 'Brief description of what this port is for',
        }
    
    def __init__(self, *args, **kwargs):
        tenant = kwargs.pop('tenant', None)
        super().__init__(*args, **kwargs)
        
        if tenant:
            self.fields['customer'].queryset = CustomUser.objects.filter(
                tenant=tenant, 
                role='customer'
            ).order_by('username')
    
    def clean_internal_ip(self):
        internal_ip = self.cleaned_data.get('internal_ip')
        if internal_ip:
            try:
                validate_ipv46_address(internal_ip)
            except forms.ValidationError:
                raise forms.ValidationError("Invalid IP address format")
        return internal_ip
    
    def clean(self):
        cleaned_data = super().clean()
        internal_port = cleaned_data.get('internal_port')
        external_port = cleaned_data.get('external_port')
        
        # Check if ports are already in use
        if external_port and PortForwardingRule.objects.filter(
            external_port=external_port, 
            is_active=True
        ).exists():
            raise forms.ValidationError(
                f"External port {external_port} is already in use by another rule"
            )
        
        return cleaned_data


class ISPEditRouterForm(forms.ModelForm):
    new_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'w-full px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
            'placeholder': 'Leave blank to keep current password'
        }),
        required=False,
        min_length=6,
        label="New Password"
    )
    
    confirm_new_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'w-full px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
            'placeholder': 'Confirm new password'
        }),
        required=False,
        label="Confirm New Password"
    )
    
    class Meta:
        model = RouterConfig
        fields = ['name', 'router_type', 'router_model', 'ip_address', 'username', 'web_port']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-blue-500'
            }),
            'router_type': forms.Select(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-blue-500'
            }),
            'router_model': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-blue-500'
            }),
            'ip_address': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-blue-500'
            }),
            'username': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-blue-500'
            }),
            'web_port': forms.NumberInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                'min': 1,
                'max': 65535
            }),
        }
    
    def clean_ip_address(self):
        ip_address = self.cleaned_data.get('ip_address')
        if ip_address:
            try:
                validate_ipv46_address(ip_address)
            except forms.ValidationError:
                raise forms.ValidationError("Invalid IP address format")
        return ip_address
    
    def clean_web_port(self):
        web_port = self.cleaned_data.get('web_port')
        if web_port and (web_port < 1 or web_port > 65535):
            raise forms.ValidationError("Port must be between 1 and 65535")
        return web_port
    
    def clean_new_password(self):
        new_password = self.cleaned_data.get('new_password')
        if new_password and len(new_password) < 6:
            raise forms.ValidationError('New password must be at least 6 characters long')
        return new_password
    
    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get('new_password')
        confirm_new_password = cleaned_data.get('confirm_new_password')
        
        if new_password and confirm_new_password and new_password != confirm_new_password:
            raise forms.ValidationError("New passwords don't match")
        
        return cleaned_data


class ISPBulkActionForm(forms.Form):
    ACTION_CHOICES = [
        ('', '--- Select Action ---'),
        ('test_connections', 'Test Connections'),
        ('restart_routers', 'Restart Routers'),
        ('update_firmware', 'Update Firmware'),
        ('backup_configs', 'Backup Configurations'),
        ('check_status', 'Check Status'),
        ('apply_security', 'Apply Security Template'),
    ]
    
    action = forms.ChoiceField(
        choices=ACTION_CHOICES,
        widget=forms.Select(attrs={
            'class': 'w-full px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-blue-500'
        }),
        required=True
    )
    
    router_ids = forms.MultipleChoiceField(
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-checkbox h-5 w-5 text-blue-600 rounded focus:ring-blue-500'}),
        required=True,
        label="Select Routers"
    )
    
    security_template = forms.ChoiceField(
        choices=[
            ('', '--- Select Template ---'),
            ('basic', 'Basic Security (Recommended)'),
            ('strict', 'Strict Security (Maximum Protection)'),
            ('custom', 'Custom Settings'),
        ],
        widget=forms.Select(attrs={
            'class': 'w-full px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-blue-500'
        }),
        required=False,
        label="Security Template"
    )
    
    def __init__(self, *args, **kwargs):
        router_choices = kwargs.pop('router_choices', [])
        super().__init__(*args, **kwargs)
        self.fields['router_ids'].choices = router_choices


class DeviceBlockForm(forms.Form):
    block_duration = forms.ChoiceField(
        choices=[
            ('1', '1 Hour'),
            ('24', '24 Hours'),
            ('168', '1 Week'),
            ('720', '1 Month'),
            ('permanent', 'Permanent'),
        ],
        widget=forms.Select(attrs={
            'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500'
        }),
        initial='24',
        label="Block Duration"
    )
    
    reason = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
            'rows': 3,
            'placeholder': 'Optional reason for blocking this device...'
        }),
        required=False,
        max_length=500
    )


class RouterDiscoveryForm(forms.Form):
    ip_range = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'w-full px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
            'placeholder': 'e.g., 192.168.1.1-192.168.1.254 or 192.168.1.0/24'
        }),
        required=True,
        label="IP Range",
        help_text="Enter IP range to scan for routers"
    )
    
    scan_type = forms.ChoiceField(
        choices=[
            ('quick', 'Quick Scan (Common Ports)'),
            ('full', 'Full Scan (All Ports)'),
            ('specific', 'Specific Ports'),
        ],
        widget=forms.Select(attrs={
            'class': 'w-full px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-blue-500'
        }),
        initial='quick'
    )
    
    specific_ports = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'w-full px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
            'placeholder': 'e.g., 80,443,8080,8443'
        }),
        required=False,
        label="Specific Ports"
    )

class RouterAssignmentForm(forms.ModelForm):
    """Form for assigning router config to customer"""
    customer = forms.ModelChoiceField(
        queryset=CustomUser.objects.none(),
        label="Select Customer",
        required=True,
        widget=forms.Select(attrs={
            'class': 'form-select',
            'data-live-search': 'true',
            'data-size': '5'
        })
    )
    
    class Meta:
        model = RouterConfig
        fields = ['name', 'customer']
    
    def __init__(self, *args, **kwargs):
        tenant = kwargs.pop('tenant', None)
        super().__init__(*args, **kwargs)
        
        if tenant:
            # Only show customers without assigned routers
            customers_with_assigned = RouterConfig.objects.filter(
                tenant=tenant,
                assigned_to__isnull=False
            ).values_list('assigned_to_id', flat=True)
            
            self.fields['customer'].queryset = CustomUser.objects.filter(
                tenant=tenant,
                role='customer',
                is_active=True
            ).exclude(id__in=customers_with_assigned).order_by('username')
    
    def clean_customer(self):
        customer = self.cleaned_data.get('customer')
        if not customer:
            raise ValidationError("Customer is required")
        
        # Check if customer already has a router
        if Router.objects.filter(user=customer).exists():
            raise ValidationError(f"Customer {customer.username} already has a router")
        
        return customer


class QuickAssignmentForm(forms.Form):
    """Quick assignment form for bulk operations"""
    router_configs = forms.ModelMultipleChoiceField(
        queryset=RouterConfig.objects.none(),
        label="Select Routers",
        widget=forms.SelectMultiple(attrs={
            'class': 'form-select',
            'size': '5'
        })
    )
    
    def __init__(self, *args, **kwargs):
        tenant = kwargs.pop('tenant', None)
        super().__init__(*args, **kwargs)
        
        if tenant:
            self.fields['router_configs'].queryset = RouterConfig.objects.filter(
                tenant=tenant,
                is_available=True
            )


class RouterConfigForm(forms.ModelForm):
    """Form for creating/editing router configurations"""
    class Meta:
        model = RouterConfig
        fields = [
            'name', 'router_type', 'router_model', 'ip_address',
            'username', 'password', 'web_port', 'huawei_ont_id'
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., Main Office Router'
            }),
            'router_type': forms.Select(attrs={'class': 'form-select'}),
            'router_model': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., HG8245H, AC10, etc.'
            }),
            'ip_address': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '192.168.1.1'
            }),
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'password': forms.PasswordInput(attrs={
                'class': 'form-control',
                'render_value': True
            }),
            'web_port': forms.NumberInput(attrs={'class': 'form-control'}),
            'huawei_ont_id': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Optional for Huawei routers'
            }),
        }
    
    def clean_ip_address(self):
        ip_address = self.cleaned_data.get('ip_address')
        
        # Check if IP already exists for this tenant
        if self.instance and self.instance.pk:
            if RouterConfig.objects.filter(
                tenant=self.instance.tenant,
                ip_address=ip_address
            ).exclude(pk=self.instance.pk).exists():
                raise ValidationError("This IP address is already in use")
        return ip_address


class BulkAssignmentForm(forms.Form):
    customer_file = forms.FileField(
        required=True,
        label="Upload File",
        help_text="Upload CSV or Excel file with router assignments"
    )
    file_type = forms.ChoiceField(
        choices=[('csv', 'CSV File'), ('excel', 'Excel File')],
        initial='csv',
        widget=forms.RadioSelect
    )
    override_existing = forms.BooleanField(
        required=False,
        initial=False,
        label="Override existing assignments",
        help_text="If checked, will reassign routers even if customer already has one"
    )


class CustomerRouterSettingsForm(forms.ModelForm):
    """Form for customer router settings"""
    confirm_password = forms.CharField(
        label="Confirm Password",
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        required=False
    )
    
    class Meta:
        model = Router
        fields = [
            'ssid', 'password', 'confirm_password', 'security_type',
            'hide_ssid', 'band', 'channel_width',
            'firewall_enabled', 'remote_access', 'upnp_enabled'
        ]
        widgets = {
            'ssid': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'WiFi Network Name'
            }),
            'password': forms.PasswordInput(attrs={
                'class': 'form-control',
                'render_value': True,
                'placeholder': 'WiFi Password'
            }),
            'security_type': forms.Select(attrs={'class': 'form-select'}),
            'hide_ssid': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'band': forms.Select(attrs={'class': 'form-select'}),
            'channel_width': forms.Select(attrs={'class': 'form-select'}),
            'firewall_enabled': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'remote_access': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'upnp_enabled': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
    
    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        confirm_password = cleaned_data.get('confirm_password')
        
        if password and password != confirm_password:
            self.add_error('confirm_password', "Passwords do not match")
        
        return cleaned_data


class RouterFilterForm(forms.Form):
    """Filter form for router assignments"""
    STATUS_CHOICES = [
        ('all', 'All Status'),
        ('available', 'Available'),
        ('assigned', 'Assigned'),
        ('online', 'Online'),
        ('offline', 'Offline'),
    ]
    
    TYPE_CHOICES = [
        ('all', 'All Types'),
        ('huawei', 'Huawei'),
        ('tenda', 'Tenda'),
        ('mikrotik', 'MikroTik'),
        ('ubiquiti', 'Ubiquiti'),
        ('tplink', 'TP-Link'),
        ('other', 'Other'),
    ]
    
    status = forms.ChoiceField(
        choices=STATUS_CHOICES,
        required=False,
        initial='all',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    router_type = forms.ChoiceField(
        choices=TYPE_CHOICES,
        required=False,
        initial='all',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search by name, IP, or customer...'
        })
    )

class RouterAssignmentForm(forms.Form):
    customer = forms.ModelChoiceField(
        queryset=CustomUser.objects.none(),
        required=True,
        label="Select Customer",
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    notes = forms.CharField(
        required=False,
        label="Assignment Notes",
        widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Optional notes about this assignment...'})
    )
    
    def __init__(self, *args, **kwargs):
        tenant = kwargs.pop('tenant')
        super().__init__(*args, **kwargs)
        
        # Filter customers by tenant and role
        self.fields['customer'].queryset = CustomUser.objects.filter(
            tenant=tenant,
            role='customer',
            is_active=True
        ).order_by('username')