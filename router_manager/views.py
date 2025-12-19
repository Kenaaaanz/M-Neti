# router_manager/views.py
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from .models import Router, ConnectedDevice, RouterConfig, PortForwardingRule
from .services import port_service
from .forms import RouterForm, WiFiPasswordForm, AdvancedSettingsForm
from django.db.models import Avg
from accounts.models import Tenant, CustomUser


@login_required
def customer_router_setup(request):
    """Guide customer through router setup"""
    if request.method == 'POST':
        try:
            # Get customer's router
            router = RouterConfig.objects.get(tenant=request.user.tenant)
            
            # Set up port forwarding
            external_port = port_service.setup_customer_port_forwarding(
                customer=request.user,
                router=router
            )
            
            messages.success(request, f"Port forwarding configured! Your external port: {external_port}")
            return redirect('dashboard')
            
        except Exception as e:
            messages.error(request, f"Setup failed: {str(e)}")
    
    return render(request, 'router/setup_guide.html')


@login_required
def router_settings(request):
    try:
        router = Router.objects.get(user=request.user)
    except Router.DoesNotExist:
        router = None
    
    if request.method == 'POST':
        form = RouterForm(request.POST, instance=router)
        if form.is_valid():
            router = form.save(commit=False)
            router.user = request.user
            router.save()
            messages.success(request, 'Router settings updated successfully!')
            return redirect('router_settings')
    else:
        form = RouterForm(instance=router)
    
    # Get connected devices for the status card
    try:
        # Get the user's tenant
        user_tenant = request.user.tenant
        
        # FIX: Use the tenant instance, not the Tenant class
        devices = ConnectedDevice.objects.filter(router__user__tenant=user_tenant).order_by('-last_seen')
        online_devices = devices.filter(last_seen__gte=timezone.now() - timezone.timedelta(minutes=5))
    except Exception as e:
        # For debugging
        print(f"Error getting devices: {e}")
        devices = []
        online_devices = []
    
    context = {
        'form': form,
        'router': router,
        'devices_count': len(devices),
        'online_devices_count': len(online_devices),
        'tab': 'wifi-settings'
    }
    return render(request, 'router/settings.html', context)

@login_required
def change_wifi_password(request):
    try:
        router = Router.objects.get(user=request.user)
    except Router.DoesNotExist:
        messages.error(request, 'Please register your router first.')
        return redirect('router_settings')
    
    if request.method == 'POST':
        form = WiFiPasswordForm(request.POST, instance=router)
        if form.is_valid():
            form.save()
            # Here you would typically make an API call to the actual router
            # to change the WiFi password
            messages.success(request, 'WiFi password updated successfully!')
            return redirect('router_settings')
    else:
        form = WiFiPasswordForm(instance=router)
    
    context = {
        'form': form,
        'router': router,
        'tab': 'wifi-settings'
    }
    return render(request, 'router/password.html', context)

@login_required
def connected_devices(request):
    try:
        router = Router.objects.get(user=request.user)
        devices = ConnectedDevice.objects.filter(router=router).order_by('-last_seen')
        online_devices = devices.filter(last_seen__gte=timezone.now() - timezone.timedelta(minutes=5))
    except Router.DoesNotExist:
        devices = []
        online_devices = []
        messages.error(request, 'No router registered yet.')
    
    context = {
        'devices': devices,
        'online_devices': online_devices,
        'router': router,
        'tab': 'connected-devices'
    }
    return render(request, 'router/devices.html', context)

@login_required
def advanced_settings(request):
    try:
        router = Router.objects.get(user=request.user)
    except Router.DoesNotExist:
        messages.error(request, 'Please register your router first.')
        return redirect('router_settings')
    
    if request.method == 'POST':
        form = AdvancedSettingsForm(request.POST, instance=router)
        if form.is_valid():
            form.save()
            messages.success(request, 'Advanced settings updated successfully!')
            return redirect('advanced_settings')
    else:
        form = AdvancedSettingsForm(instance=router)
    
    context = {
        'form': form,
        'router': router,
        'tab': 'advanced'
    }
    return render(request, 'router/advanced.html', context)

@login_required
def security_settings(request):
    try:
        router = Router.objects.get(user=request.user)
    except Router.DoesNotExist:
        messages.error(request, 'Please register your router first.')
        return redirect('router_settings')
    
    if request.method == 'POST':
        # Handle security settings update
        firewall_enabled = request.POST.get('firewall_enabled') == 'on'
        remote_access = request.POST.get('remote_access') == 'on'
        upnp_enabled = request.POST.get('upnp_enabled') == 'on'
        
        router.firewall_enabled = firewall_enabled
        router.remote_access = remote_access
        router.upnp_enabled = upnp_enabled
        router.save()
        
        messages.success(request, 'Security settings updated successfully!')
        return redirect('security_settings')
    
    context = {
        'router': router,
        'tab': 'security'
    }
    return render(request, 'router/security.html', context)

@login_required
def router_status(request):
    """Show customer's router status"""
    try:
        router = RouterConfig.objects.get(tenant=request.user.tenant)
        port_rules = PortForwardingRule.objects.filter(
            customer=request.user,
            is_active=True
        )
        
        context = {
            'router': router,
            'port_rules': port_rules
        }
        
        return render(request, 'router/status.html', context)
        
    except RouterConfig.DoesNotExist:
        messages.warning(request, "No router configured for your account")
        return redirect('dashboard')
    
@login_required
def reboot_router(request):
    try:
        router = Router.objects.get(user=request.user)
        # Simulate reboot process
        # In a real implementation, you would call the router's API here
        router.is_online = False
        router.save()
        
        # Simulate reboot delay
        import time
        time.sleep(2)
        
        router.is_online = True
        router.save()
        
        messages.success(request, 'Router rebooted successfully! It may take a few minutes to come back online.')
    except Router.DoesNotExist:
        messages.error(request, 'No router registered yet.')
    
    return redirect('router_settings')

@login_required
def block_device(request, device_id):
    try:
        device = ConnectedDevice.objects.get(id=device_id, router__user=request.user)
        device.blocked = True
        device.save()
        messages.success(request, f'{device.name or device.ip_address} has been blocked.')
    except ConnectedDevice.DoesNotExist:
        messages.error(request, 'Device not found.')
    
    return redirect('connected_devices')

@login_required
def unblock_device(request, device_id):
    try:
        device = ConnectedDevice.objects.get(id=device_id, router__user=request.user)
        device.blocked = False
        device.save()
        messages.success(request, f'{device.name or device.ip_address} has been unblocked.')
    except ConnectedDevice.DoesNotExist:
        messages.error(request, 'Device not found.')
    
    return redirect('connected_devices')

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db.models import Avg, Sum
from .models import Router, ConnectedDevice, RouterLog, GuestNetwork
from .forms import RouterForm, GuestNetworkForm

@login_required
def guest_network(request):
    try:
        router = Router.objects.get(user=request.user)
        guest_network, created = GuestNetwork.objects.get_or_create(router=router)
    except Router.DoesNotExist:
        messages.error(request, 'Please register your router first.')
        return redirect('router_settings')
    
    if request.method == 'POST':
        form = GuestNetworkForm(request.POST, instance=guest_network)
        if form.is_valid():
            form.save()
            RouterLog.objects.create(
                router=router,
                log_type='config_change',
                message='Guest network settings updated'
            )
            messages.success(request, 'Guest network settings updated successfully!')
            return redirect('guest_network')
    else:
        form = GuestNetworkForm(instance=guest_network)
    
    context = {
        'form': form,
        'router': router,
        'guest_network': guest_network,
        'tab': 'guest-network'
    }
    return render(request, 'router/guest_network.html', context)

@login_required
def firmware_update(request):
    try:
        router = Router.objects.get(user=request.user)
    except Router.DoesNotExist:
        messages.error(request, 'Please register your router first.')
        return redirect('router_settings')
    
    if request.method == 'POST':
        # Simulate firmware update process
        router.is_online = False
        router.save()
        
        RouterLog.objects.create(
            router=router,
            log_type='firmware_update',
            message='Firmware update initiated'
        )
        
        # In a real implementation, you would call the router's API here
        messages.success(request, 'Firmware update initiated. Your router will restart and may be offline for a few minutes.')
        return redirect('router_status')
    
    context = {
        'router': router,
        'tab': 'firmware'
    }
    return render(request, 'router/firmware.html', context)

@login_required
def parental_controls(request):
    try:
        router = Router.objects.get(user=request.user)
        devices = ConnectedDevice.objects.filter(router=router, blocked=False)
    except Router.DoesNotExist:
        messages.error(request, 'Please register your router first.')
        return redirect('router_settings')
    
    if request.method == 'POST':
        # Handle parental controls settings
        device_id = request.POST.get('device_id')
        schedule_enabled = request.POST.get('schedule_enabled') == 'on'
        
        if device_id:
            device = get_object_or_404(ConnectedDevice, id=device_id, router=router)
            device.blocked = True
            device.save()
            
            RouterLog.objects.create(
                router=router,
                log_type='security_event',
                message=f'Device {device.name or device.ip_address} blocked via parental controls'
            )
            
            messages.success(request, f'{device.name or device.ip_address} has been blocked.')
            return redirect('parental_controls')
    
    context = {
        'router': router,
        'devices': devices,
        'tab': 'parental-controls'
    }
    return render(request, 'router/parental_controls.html', context)