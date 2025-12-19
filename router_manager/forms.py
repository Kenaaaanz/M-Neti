# router_manager/forms.py
from django import forms
from .models import Router, GuestNetwork, RouterConfig, PortForwardingRule
from accounts.models import CustomUser

# Customer-facing forms
class RouterForm(forms.ModelForm):
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': 'Confirm WiFi password'}),
        required=False
    )
    
    class Meta:
        model = Router
        fields = ['mac_address', 'model', 'ssid', 'password', 'security_type', 
                 'hide_ssid', 'band', 'channel_width', 'firewall_enabled', 
                 'remote_access', 'upnp_enabled']
        widgets = {
            'mac_address': forms.TextInput(attrs={'placeholder': 'AA:BB:CC:DD:EE:FF'}),
            'model': forms.TextInput(attrs={'placeholder': 'Router Model'}),
            'ssid': forms.TextInput(attrs={'placeholder': 'Network Name'}),
            'password': forms.PasswordInput(attrs={'placeholder': 'WiFi Password', 'render_value': True}),
            'security_type': forms.Select(attrs={'class': 'form-control'}),
            'band': forms.Select(attrs={'class': 'form-control'}),
            'channel_width': forms.Select(attrs={'class': 'form-control'}),
            'hide_ssid': forms.CheckboxInput(attrs={'class': 'toggle-switch'}),
            'firewall_enabled': forms.CheckboxInput(attrs={'class': 'toggle-switch'}),
            'remote_access': forms.CheckboxInput(attrs={'class': 'toggle-switch'}),
            'upnp_enabled': forms.CheckboxInput(attrs={'class': 'toggle-switch'}),
        }
    
    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        confirm_password = cleaned_data.get('confirm_password')
        
        if password and confirm_password and password != confirm_password:
            raise forms.ValidationError("Passwords don't match")
        
        return cleaned_data


class GuestNetworkForm(forms.ModelForm):
    class Meta:
        model = GuestNetwork
        fields = ['ssid', 'password', 'enabled', 'bandwidth_limit', 'access_duration']
        widgets = {
            'ssid': forms.TextInput(attrs={'placeholder': 'Guest Network Name'}),
            'password': forms.PasswordInput(attrs={'placeholder': 'Guest Password', 'render_value': True}),
            'enabled': forms.CheckboxInput(attrs={'class': 'toggle-switch'}),
            'bandwidth_limit': forms.NumberInput(attrs={'min': 1, 'max': 100}),
            'access_duration': forms.NumberInput(attrs={'min': 1, 'max': 168}),
        }


class AdvancedSettingsForm(forms.ModelForm):
    class Meta:
        model = Router
        fields = ['hide_ssid', 'channel_width', 'band']
        widgets = {
            'hide_ssid': forms.CheckboxInput(attrs={'class': 'toggle-switch'}),
        }


class WiFiPasswordForm(forms.ModelForm):
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': 'Confirm WiFi password'}),
        required=True
    )
    
    class Meta:
        model = Router
        fields = ['password']
        widgets = {
            'password': forms.PasswordInput(attrs={'placeholder': 'New WiFi Password'}),
        }
    
    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        confirm_password = cleaned_data.get('confirm_password')
        
        if password and confirm_password and password != confirm_password:
            raise forms.ValidationError("Passwords don't match")
        
        return cleaned_data


# ISP-facing forms
class ISPAddRouterForm(forms.ModelForm):
    """Form for ISP to add router configurations"""
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'w-full px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
            'placeholder': 'Confirm router password'
        }),
        required=True,
        label="Confirm Password"
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
            'password': forms.PasswordInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                'placeholder': 'Router admin password',
                'render_value': True
            }),
            'web_port': forms.NumberInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                'value': 80
            }),
        }
    
    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        confirm_password = cleaned_data.get('confirm_password')
        ip_address = cleaned_data.get('ip_address')
        web_port = cleaned_data.get('web_port')
        
        # Password validation
        if password and confirm_password and password != confirm_password:
            raise forms.ValidationError("Passwords don't match")
        
        # IP address validation
        if ip_address:
            import socket
            try:
                socket.inet_aton(ip_address)
            except socket.error:
                raise forms.ValidationError("Invalid IP address format")
        
        # Port validation
        if web_port and (web_port < 1 or web_port > 65535):
            raise forms.ValidationError("Port must be between 1 and 65535")
        
        return cleaned_data


class ISPPortForwardingForm(forms.ModelForm):
    """Form for ISP to create port forwarding rules"""
    customer = forms.ModelChoiceField(
        queryset=CustomUser.objects.none(),  # Will be set in view
        widget=forms.Select(attrs={
            'class': 'w-full px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-blue-500'
        }),
        required=True,
        label="Customer"
    )
    
    class Meta:
        model = PortForwardingRule
        fields = ['customer', 'internal_ip', 'internal_port', 'protocol', 'description']
        widgets = {
            'internal_ip': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                'placeholder': 'e.g., 192.168.1.100'
            }),
            'internal_port': forms.NumberInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                'value': 80
            }),
            'protocol': forms.Select(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-blue-500'
            }),
            'description': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                'placeholder': 'e.g., Web Server Access'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        tenant = kwargs.pop('tenant', None)
        super().__init__(*args, **kwargs)
        
        if tenant:
            self.fields['customer'].queryset = CustomUser.objects.filter(
                tenant=tenant, 
                role='customer'
            ).order_by('username')
    
    def clean(self):
        cleaned_data = super().clean()
        internal_ip = cleaned_data.get('internal_ip')
        internal_port = cleaned_data.get('internal_port')
        
        # IP address validation
        if internal_ip:
            import socket
            try:
                socket.inet_aton(internal_ip)
            except socket.error:
                raise forms.ValidationError("Invalid internal IP address format")
        
        # Port validation
        if internal_port and (internal_port < 1 or internal_port > 65535):
            raise forms.ValidationError("Internal port must be between 1 and 65535")
        
        return cleaned_data


class ISPEditRouterForm(forms.ModelForm):
    """Form for ISP to edit existing router configurations"""
    class Meta:
        model = RouterConfig
        fields = ['name', 'router_type', 'router_model', 'ip_address', 'username', 'password', 'web_port']
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
            'password': forms.PasswordInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-blue-500',
                'render_value': True
            }),
            'web_port': forms.NumberInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-blue-500'
            }),
        }
    
    def clean(self):
        cleaned_data = super().clean()
        ip_address = cleaned_data.get('ip_address')
        web_port = cleaned_data.get('web_port')
        
        # IP address validation
        if ip_address:
            import socket
            try:
                socket.inet_aton(ip_address)
            except socket.error:
                raise forms.ValidationError("Invalid IP address format")
        
        # Port validation
        if web_port and (web_port < 1 or web_port > 65535):
            raise forms.ValidationError("Port must be between 1 and 65535")
        
        return cleaned_data


class ISPBulkActionForm(forms.Form):
    """Form for ISP bulk actions on routers"""
    ACTION_CHOICES = [
        ('test_connections', 'Test Connections'),
        ('restart_routers', 'Restart Routers'),
        ('update_firmware', 'Update Firmware'),
        ('backup_configs', 'Backup Configurations'),
    ]
    
    action = forms.ChoiceField(
        choices=ACTION_CHOICES,
        widget=forms.Select(attrs={
            'class': 'w-full px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-blue-500'
        })
    )
    
    router_ids = forms.MultipleChoiceField(
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'bulk-checkbox'}),
        required=False
    )
    
    def __init__(self, *args, **kwargs):
        router_choices = kwargs.pop('router_choices', [])
        super().__init__(*args, **kwargs)
        self.fields['router_ids'].choices = router_choices