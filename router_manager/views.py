# router_manager/views.py
import random
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
import json
from django.utils import timezone
from .models import Router, ConnectedDevice, RouterConfig, PortForwardingRule, RouterLog, ParentalControlSchedule, FirmwareUpdate, GuestNetwork, Device
from .services import discover_routers_in_network, health_check, port_service, RouterManagerService, RouterMonitor, router_monitor
from .forms import FirmwareUpdateForm, ParentalControlForm, RouterForm, WiFiPasswordForm, AdvancedSettingsForm, GuestNetworkForm, ISPAddRouterForm, ISPPortForwardingForm, DeviceBlockForm
from accounts.models import Tenant, CustomUser
from datetime import timedelta
from accounts.decorators import isp_required


router_service = RouterManagerService()
router_monitor = RouterMonitor()

def staff_member_required(view_func=None, login_url='admin:login'):
    """
    Custom decorator for staff members
    """
    def test_func(user):
        return user.is_staff
    
    decorator = user_passes_test(test_func, login_url=login_url)
    
    if view_func:
        return decorator(view_func)
    return decorator

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_user_router(request):
    """Get the router for the current user"""
    try:
        # For customers - get their personal router
        if hasattr(request.user, 'router'):
            return request.user.router
        # For ISP staff - can access any router but need specific ID
        elif request.user.role in ['isp_admin', 'isp_staff']:
            router_id = request.GET.get('router_id') or request.POST.get('router_id')
            if router_id:
                return Router.objects.get(id=router_id)
    except (Router.DoesNotExist, AttributeError, ValueError):
        pass
    return None

def check_router_access(request, router):
    """Check if user has access to this router"""
    if not router:
        return False
    
    # ISP staff can access any router
    if request.user.role in ['isp_admin', 'isp_staff']:
        return True
    
    # Customers can only access their own router
    if hasattr(request.user, 'router'):
        return router.id == request.user.router.id
    
    return False

def get_isp_routers(request):
    """Get routers for ISP staff view"""
    if not hasattr(request.user, 'tenant'):
        return RouterConfig.objects.none()
    
    # ISP staff see RouterConfig (managed routers)
    return RouterConfig.objects.filter(tenant=request.user.tenant)

def get_customer_routers_for_isp(request):
    """Get customer routers for ISP staff view"""
    if not hasattr(request.user, 'tenant'):
        return Router.objects.none()
    
    # ISP staff can see customer routers in their tenant
    return Router.objects.filter(tenant=request.user.tenant)

# ============================================================================
# CUSTOMER VIEWS
# ============================================================================

@login_required
def customer_router_setup(request):
    """Guide customer through router setup"""
    if request.method == 'POST':
        try:
            # Get customer's router config (ISP managed)
            router_config = RouterConfig.objects.filter(tenant=request.user.tenant).first()
            
            if not router_config:
                messages.error(request, "No router configuration found for your account.")
                return redirect('dashboard')
            
            # Set up port forwarding
            external_port = port_service.setup_customer_port_forwarding(
                customer=request.user,
                router=router_config
            )
            
            messages.success(request, f"Port forwarding configured! Your external port: {external_port}")
            return redirect('dashboard')
            
        except Exception as e:
            messages.error(request, f"Setup failed: {str(e)}")
    
    return render(request, 'router/setup_guide.html')

@login_required
def router_settings(request):
    """Main router settings page - handles WiFi settings"""
    router = get_user_router(request)
    
    if not router:
        # Create a default router for the user if none exists
        router = Router.objects.create(
            user=request.user,
            tenant=request.user.tenant if hasattr(request.user, 'tenant') else None,
            mac_address="00:00:00:00:00:00",
            model="Generic Router",
            ssid=f"{request.user.username}_Network",
            password="changeme123"
        )
        messages.info(request, "A default router profile has been created for you.")
    
    if request.method == 'POST':
        form = RouterForm(request.POST, instance=router)
        if form.is_valid():
            form.save()
            
            # Log the change
            RouterLog.objects.create(
                router=router,
                log_type='config_change',
                message='WiFi settings updated'
            )
            
            messages.success(request, 'WiFi settings updated successfully!')
            return redirect('router_settings')
    else:
        form = RouterForm(instance=router)
    
    context = {
        'form': form,
        'router': router,
        'tab': 'wifi-settings'
    }
    return render(request, 'router/wifi_settings.html', context)

@login_required
def connected_devices(request):
    """Show connected devices with dynamic data"""
    router = get_user_router(request)
    
    if not router:
        devices = []
        online_devices = []
        messages.error(request, 'No router registered yet.')
    else:
        devices = ConnectedDevice.objects.filter(router=router).order_by('-last_seen')
        online_devices = [d for d in devices if d.is_online]
        
        # If no devices, create some sample data for demonstration
        if not devices.exists() and request.user.is_superuser:
            # Create sample devices
            sample_devices = [
                ('John\'s Laptop', '192.168.1.10', '00:1A:2B:3C:4D:5E', 'computer', True),
                ('Sarah\'s Phone', '192.168.1.11', '00:1A:2B:3C:4D:5F', 'phone', True),
                ('Living Room TV', '192.168.1.12', '00:1A:2B:3C:4D:60', 'tv', False),
                ('IoT Camera', '192.168.1.13', '00:1A:2B:3C:4D:61', 'iot', True),
            ]
            
            for name, ip, mac, dev_type, is_online in sample_devices:
                ConnectedDevice.objects.create(
                    router=router,
                    name=name,
                    ip_address=ip,
                    mac_address=mac,
                    device_type=dev_type,
                    connection_type=random.choice(['wired', 'wireless_2.4', 'wireless_5']),
                    signal_strength=random.randint(-80, -30) if dev_type != 'computer' else None,
                    data_usage=random.randint(1000000, 1000000000),
                    last_seen=timezone.now() if is_online else timezone.now() - timezone.timedelta(hours=2)
                )
            devices = ConnectedDevice.objects.filter(router=router)
            online_devices = [d for d in devices if d.is_online]
    
    context = {
        'devices': devices,
        'online_devices': online_devices,
        'router': router,
        'tab': 'connected-devices'
    }
    return render(request, 'router/connected_devices.html', context)

@login_required
def security_settings(request):
    """Security settings with dynamic blocking"""
    router = get_user_router(request)
    
    if not router:
        messages.error(request, 'Please register your router first.')
        return redirect('router_settings')
    
    blocked_devices = ConnectedDevice.objects.filter(router=router, blocked=True)
    
    if request.method == 'POST':
        # Handle security settings update
        firewall_enabled = request.POST.get('firewall_enabled') == 'true'
        remote_access = request.POST.get('remote_access') == 'true'
        upnp_enabled = request.POST.get('upnp_enabled') == 'true'
        
        router.firewall_enabled = firewall_enabled
        router.remote_access = remote_access
        router.upnp_enabled = upnp_enabled
        router.save()
        
        # Log the change
        RouterLog.objects.create(
            router=router,
            log_type='config_change',
            message=f'Security settings updated: Firewall={firewall_enabled}, Remote Access={remote_access}, UPnP={upnp_enabled}'
        )
        
        messages.success(request, 'Security settings updated successfully!')
        return redirect('security_settings')
    
    context = {
        'router': router,
        'blocked_devices': blocked_devices,
        'tab': 'security'
    }
    return render(request, 'router/security_settings.html', context)

@login_required
def advanced_settings(request):
    """Advanced router settings"""
    router = get_user_router(request)
    
    if not router:
        messages.error(request, 'Please register your router first.')
        return redirect('router_settings')
    
    if request.method == 'POST':
        form = AdvancedSettingsForm(request.POST, instance=router)
        if form.is_valid():
            form.save()
            
            # Log the change
            RouterLog.objects.create(
                router=router,
                log_type='config_change',
                message='Advanced settings updated'
            )
            
            messages.success(request, 'Advanced settings updated successfully!')
            return redirect('advanced_settings')
    else:
        form = AdvancedSettingsForm(instance=router)
    
    # Get port forwarding rules for this router
    port_rules = PortForwardingRule.objects.filter(router=router)
    
    context = {
        'form': form,
        'router': router,
        'port_rules': port_rules,
        'tab': 'advanced'
    }
    return render(request, 'router/advanced_settings.html', context)

@login_required
def router_status(request):
    """Show router status with dynamic statistics"""
    router = get_user_router(request)
    
    if not router:
        messages.error(request, 'Please register your router first.')
        return redirect('router_settings')
    
    # Calculate statistics
    devices = ConnectedDevice.objects.filter(router=router)
    online_count = sum(1 for d in devices if d.is_online)
    total_data_usage = sum(d.data_usage for d in devices)
    
    # Convert bytes to GB
    total_data_gb = total_data_usage / (1024 ** 3)
    
    # Simulate network speed (in production, this would come from actual monitoring)
    download_speed = random.randint(50, 300)  # Mbps
    upload_speed = random.randint(10, 50)     # Mbps
    
    # Get recent logs
    recent_logs = RouterLog.objects.filter(router=router).order_by('-created_at')[:10]
    
    context = {
        'router': router,
        'online_count': online_count,
        'total_devices': devices.count(),
        'total_data_gb': round(total_data_gb, 2),
        'download_speed': download_speed,
        'upload_speed': upload_speed,
        'recent_logs': recent_logs,
        'tab': 'status'
    }
    return render(request, 'router/status.html', context)

@login_required
def reboot_router(request):
    """Simulate router reboot"""
    router = get_user_router(request)
    
    if not router:
        messages.error(request, 'No router registered yet.')
        return redirect('router_settings')
    
    # Simulate reboot process
    router.is_online = False
    router.save()
    
    # Log the reboot
    RouterLog.objects.create(
        router=router,
        log_type='reboot',
        message='Router reboot initiated by user'
    )
    
    messages.success(request, 'Router reboot initiated! It may take a few minutes to come back online.')
    
    # Simulate coming back online after delay
    import threading
    def bring_online():
        import time
        time.sleep(5)
        router.is_online = True
        router.save()
        RouterLog.objects.create(
            router=router,
            log_type='reboot',
            message='Router is now back online'
        )
    
    thread = threading.Thread(target=bring_online)
    thread.daemon = True
    thread.start()
    
    return redirect('router_settings')

@login_required
def block_device(request, device_id):
    """Block a specific device"""
    try:
        device = get_object_or_404(ConnectedDevice, id=device_id)
        # Check access
        if not check_router_access(request, device.router):
            messages.error(request, 'Access denied to this device.')
            return redirect('connected_devices')
        
        device.blocked = True
        device.save()
        
        # Log the action
        RouterLog.objects.create(
            router=device.router,
            log_type='security_event',
            message=f'Device {device.name or device.ip_address} blocked by user'
        )
        
        messages.success(request, f'{device.name or device.ip_address} has been blocked.')
    except ConnectedDevice.DoesNotExist:
        messages.error(request, 'Device not found.')
    
    return redirect('connected_devices')

@login_required
def unblock_device(request, device_id):
    """Unblock a specific device"""
    try:
        device = get_object_or_404(ConnectedDevice, id=device_id)
        # Check access
        if not check_router_access(request, device.router):
            messages.error(request, 'Access denied to this device.')
            return redirect('security_settings')
        
        device.blocked = False
        device.save()
        
        # Log the action
        RouterLog.objects.create(
            router=device.router,
            log_type='security_event',
            message=f'Device {device.name or device.ip_address} unblocked by user'
        )
        
        messages.success(request, f'{device.name or device.ip_address} has been unblocked.')
    except ConnectedDevice.DoesNotExist:
        messages.error(request, 'Device not found.')
    
    return redirect('security_settings')

@login_required
def guest_network(request):
    """Guest network management"""
    router = get_user_router(request)
    
    if not router:
        messages.error(request, 'Please register your router first.')
        return redirect('router_settings')
    
    guest_network, created = GuestNetwork.objects.get_or_create(router=router)
    
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
def parental_controls(request):
    """Parental controls with scheduling and device management"""
    router = get_user_router(request)
    
    if not router:
        messages.error(request, 'Please register your router first.')
        return redirect('router_settings')
    
    devices = ConnectedDevice.objects.filter(router=router, blocked=False).order_by('-last_seen')
    
    # Get parental control schedules
    schedules = ParentalControlSchedule.objects.filter(router=router).order_by('-is_active', '-created_at')
    
    # Get active blocked devices
    blocked_devices = ConnectedDevice.objects.filter(router=router, blocked=True)
    
    if request.method == 'POST':
        # Handle blocking device
        if 'block_device' in request.POST:
            device_id = request.POST.get('device_id')
            block_duration = request.POST.get('block_duration', '24')  # Default 24 hours
            reason = request.POST.get('reason', '')
            
            try:
                device = ConnectedDevice.objects.get(id=device_id, router=router)
                device.blocked = True
                device.blocked_until = timezone.now() + timedelta(hours=int(block_duration)) if block_duration != 'permanent' else None
                device.block_reason = reason
                device.save()
                
                RouterLog.objects.create(
                    router=router,
                    log_type='security_event',
                    message=f'Device {device.name or device.ip_address} blocked via parental controls. Reason: {reason}'
                )
                
                messages.success(request, f'{device.name or device.ip_address} has been blocked.')
                return redirect('parental_controls')
            except ConnectedDevice.DoesNotExist:
                messages.error(request, 'Device not found.')
        
        # Handle creating schedule
        elif 'create_schedule' in request.POST:
            form = ParentalControlForm(request.POST)
            if form.is_valid():
                schedule = form.save(commit=False)
                schedule.router = router
                schedule.save()
                
                # Add devices to schedule
                device_ids = request.POST.getlist('devices')
                schedule.devices.add(*device_ids)
                
                messages.success(request, 'Parental control schedule created successfully!')
                return redirect('parental_controls')
        
        # Handle enabling/disabling schedule
        elif 'toggle_schedule' in request.POST:
            schedule_id = request.POST.get('schedule_id')
            schedule = get_object_or_404(ParentalControlSchedule, id=schedule_id, router=router)
            schedule.is_active = not schedule.is_active
            schedule.save()
            
            status = "enabled" if schedule.is_active else "disabled"
            messages.success(request, f'Schedule "{schedule.name}" has been {status}.')
            return redirect('parental_controls')
    
    context = {
        'router': router,
        'devices': devices,
        'blocked_devices': blocked_devices,
        'schedules': schedules,
        'tab': 'parental-controls'
    }
    return render(request, 'router/parental_controls.html', context)

@login_required
def unblock_device_parental(request, device_id):
    """Unblock a device from parental controls"""
    try:
        device = get_object_or_404(ConnectedDevice, id=device_id)
        # Check access
        if not check_router_access(request, device.router):
            messages.error(request, 'Access denied to this device.')
            return redirect('parental_controls')
        
        device.blocked = False
        device.blocked_until = None
        device.block_reason = ''
        device.save()
        
        RouterLog.objects.create(
            router=device.router,
            log_type='security_event',
            message=f'Device {device.name or device.ip_address} unblocked from parental controls'
        )
        
        messages.success(request, f'{device.name or device.ip_address} has been unblocked.')
    except ConnectedDevice.DoesNotExist:
        messages.error(request, 'Device not found.')
    
    return redirect('parental_controls')

@login_required
def delete_schedule(request, schedule_id):
    """Delete a parental control schedule"""
    try:
        schedule = get_object_or_404(ParentalControlSchedule, id=schedule_id)
        # Check access
        if not check_router_access(request, schedule.router):
            messages.error(request, 'Access denied to this schedule.')
            return redirect('parental_controls')
        
        schedule.delete()
        
        messages.success(request, 'Schedule deleted successfully!')
    except ParentalControlSchedule.DoesNotExist:
        messages.error(request, 'Schedule not found.')
    
    return redirect('parental_controls')

@login_required
def toggle_content_filter(request):
    """Toggle content filtering categories"""
    router = get_user_router(request)
    
    if not router:
        return JsonResponse({'success': False, 'error': 'Router not found'}, status=404)
    
    category = request.POST.get('category')
    enabled = request.POST.get('enabled') == 'true'
    
    # Update router's content filtering settings
    # In a real implementation, you would have fields for each category
    # For now, we'll simulate it
    
    RouterLog.objects.create(
        router=router,
        log_type='config_change',
        message=f'Content filtering for {category} {"enabled" if enabled else "disabled"}'
    )
    
    return JsonResponse({'success': True, 'message': f'{category} filtering updated'})

@login_required
def pause_all_devices(request):
    """Pause internet access for all devices"""
    router = get_user_router(request)
    
    if not router:
        return JsonResponse({'success': False, 'error': 'Router not found'}, status=404)
    
    # In a real implementation, you would make API calls to the router
    # For now, we'll simulate by updating device status
    
    RouterLog.objects.create(
        router=router,
        log_type='parental_control',
        message='All devices paused via parental controls'
    )
    
    return JsonResponse({
        'success': True, 
        'message': 'All devices paused. Internet access will resume in 1 hour.',
        'resume_time': (timezone.now() + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
    })

@login_required
def firmware_update(request):
    """Firmware update page with version checking"""
    router = get_user_router(request)
    
    if not router:
        messages.error(request, 'Please register your router first.')
        return redirect('router_settings')
    
    # Get current firmware info (simulated)
    current_version = "2.1.8"
    current_date = "2024-03-15"
    
    # Check for available updates (simulated)
    update_available = random.choice([True, False])  # Random for demo
    latest_version = "2.2.0" if update_available else current_version
    
    # Get firmware update history (simulated)
    update_history = [
        {'version': '2.1.8', 'date': '2024-03-15', 'type': 'minor'},
        {'version': '2.1.7', 'date': '2024-02-01', 'type': 'security'},
        {'version': '2.1.6', 'date': '2023-12-15', 'type': 'feature'},
    ]
    
    # Get scheduled updates
    scheduled_updates = FirmwareUpdate.objects.filter(router=router, status='scheduled')
    
    if request.method == 'POST':
        # Handle firmware update
        if 'install_update' in request.POST:
            # Simulate firmware update process
            router.is_online = False
            router.save()
            
            FirmwareUpdate.objects.create(
                router=router,
                version=latest_version,
                status='in_progress',
                scheduled_for=timezone.now()
            )
            
            RouterLog.objects.create(
                router=router,
                log_type='firmware_update',
                message=f'Firmware update to {latest_version} initiated'
            )
            
            messages.success(request, 'Firmware update initiated. Your router will restart and may be offline for a few minutes.')
            return redirect('firmware_update')
        
        # Handle scheduling update
        elif 'schedule_update' in request.POST:
            form = FirmwareUpdateForm(request.POST)
            if form.is_valid():
                scheduled_update = form.save(commit=False)
                scheduled_update.router = router
                scheduled_update.version = latest_version
                scheduled_update.status = 'scheduled'
                scheduled_update.save()
                
                messages.success(request, f'Firmware update scheduled for {scheduled_update.scheduled_for}')
                return redirect('firmware_update')
    
    context = {
        'router': router,
        'current_version': current_version,
        'current_date': current_date,
        'update_available': update_available,
        'latest_version': latest_version,
        'update_history': update_history,
        'scheduled_updates': scheduled_updates,
        'tab': 'firmware',
        'today': timezone.now().date(),
        'tomorrow': (timezone.now() + timedelta(days=1)).date(),
    }
    return render(request, 'router/firmware.html', context)

@login_required
def check_for_updates(request):
    """API endpoint to check for firmware updates"""
    router = get_user_router(request)
    
    if not router:
        return JsonResponse({'success': False, 'error': 'Router not found'}, status=404)
    
    # Simulate checking for updates
    update_available = random.choice([True, False])
    latest_version = "2.2.0" if update_available else "2.1.8"
    
    return JsonResponse({
        'success': True,
        'update_available': update_available,
        'current_version': "2.1.8",
        'latest_version': latest_version,
        'release_date': "2024-04-10" if update_available else None,
        'size': "42.5 MB" if update_available else None,
        'changelog': [
            "Security patches for critical vulnerabilities",
            "Improved Wi-Fi performance and stability",
            "Fixed memory leak issue",
            "Enhanced parental controls features"
        ] if update_available else []
    })

@login_required
def get_update_status(request):
    """API endpoint to get firmware update status"""
    router = get_user_router(request)
    
    if not router:
        return JsonResponse({'success': False, 'error': 'Router not found'}, status=404)
    
    # Check for active updates
    active_update = FirmwareUpdate.objects.filter(
        router=router,
        status__in=['in_progress', 'scheduled']
    ).first()
    
    if active_update:
        status = {
            'in_progress': {
                'status': 'in_progress',
                'message': 'Update in progress...',
                'progress': random.randint(10, 90),
                'estimated_time': '2 minutes remaining'
            },
            'scheduled': {
                'status': 'scheduled',
                'message': f'Update scheduled for {active_update.scheduled_for}',
                'scheduled_for': active_update.scheduled_for.isoformat()
            }
        }.get(active_update.status, {})
    else:
        status = {'status': 'idle', 'message': 'No active updates'}
    
    return JsonResponse({'success': True, 'update': status})

@login_required
def cancel_scheduled_update(request, update_id):
    """Cancel a scheduled firmware update"""
    try:
        scheduled_update = get_object_or_404(FirmwareUpdate, id=update_id)
        # Check access
        if not check_router_access(request, scheduled_update.router):
            messages.error(request, 'Access denied to this update.')
            return redirect('firmware_update')
        
        scheduled_update.delete()
        
        messages.success(request, 'Scheduled firmware update cancelled.')
    except FirmwareUpdate.DoesNotExist:
        messages.error(request, 'Scheduled update not found.')
    
    return redirect('firmware_update')

# ============================================================================
# ISP VIEWS
# ============================================================================

@login_required
@isp_required
def isp_router_management(request):
    """ISP router management dashboard"""
    router_configs = get_isp_routers(request)
    customer_routers = get_customer_routers_for_isp(request)
    
    context = {
        'router_configs': router_configs,
        'customer_routers': customer_routers,
        'total_routers': router_configs.count(),
        'online_routers': router_configs.filter(is_online=True).count(),
        'total_customers': customer_routers.count(),
    }
    return render(request, 'router/isp/routers.html', context)

@login_required
@isp_required
def isp_add_router(request):
    """ISP add new router"""
    if request.method == 'POST':
        form = ISPAddRouterForm(request.POST)
        if form.is_valid():
            router = form.save(commit=False)
            router.tenant = request.user.tenant
            router.save()
            messages.success(request, 'Router added successfully!')
            return redirect('isp_routers')
    else:
        form = ISPAddRouterForm()
    
    context = {'form': form}
    return render(request, 'router/isp/add_router.html', context)

@login_required
@isp_required
def isp_edit_router(request, router_id):
    """ISP edit router"""
    router = get_object_or_404(RouterConfig, id=router_id, tenant=request.user.tenant)
    
    if request.method == 'POST':
        form = ISPAddRouterForm(request.POST, instance=router)
        if form.is_valid():
            form.save()
            messages.success(request, 'Router updated successfully!')
            return redirect('isp_routers')
    else:
        form = ISPAddRouterForm(instance=router)
    
    context = {'form': form, 'router': router}
    return render(request, 'router/isp/edit_router.html', context)

@login_required
@isp_required
def isp_delete_router(request, router_id):
    """ISP delete router"""
    router = get_object_or_404(RouterConfig, id=router_id, tenant=request.user.tenant)
    router.delete()
    messages.success(request, 'Router deleted successfully!')
    return redirect('isp_routers')

@login_required
@isp_required
def isp_port_forwarding(request):
    """ISP port forwarding management"""
    # Get port rules for customer routers in this tenant
    port_rules = PortForwardingRule.objects.filter(
        router__tenant=request.user.tenant
    )
    
    if request.method == 'POST':
        form = ISPPortForwardingForm(request.POST, tenant=request.user.tenant)
        if form.is_valid():
            port_rule = form.save(commit=False)
            # In real implementation, you would set the router based on customer
            # For now, get the first router
            router = Router.objects.filter(tenant=request.user.tenant).first()
            if router:
                port_rule.router = router
                port_rule.save()
                messages.success(request, 'Port forwarding rule created successfully!')
                return redirect('isp_port_forwarding')
            else:
                messages.error(request, 'No customer router configured for this tenant.')
    else:
        form = ISPPortForwardingForm(tenant=request.user.tenant)
    
    context = {
        'form': form,
        'port_rules': port_rules,
    }
    return render(request, 'router/isp/port_forwarding.html', context)

@login_required
@isp_required
def isp_create_port_forwarding(request):
    """Create port forwarding rule"""
    if request.method == 'POST':
        form = ISPPortForwardingForm(request.POST, tenant=request.user.tenant)
        if form.is_valid():
            port_rule = form.save(commit=False)
            router_config = form.cleaned_data['router_config']
            customer = form.cleaned_data['customer']
            
            # Find the customer's router
            customer_router = Router.objects.filter(user=customer).first()
            if not customer_router:
                messages.error(request, 'Customer does not have a router configured.')
                return redirect('isp_create_port_forwarding')
            
            # Create port forwarding on actual router
            success, message, rule = router_service.create_port_forwarding_rule(
                router_config=router_config,
                customer=customer,
                external_port=port_rule.external_port,
                internal_ip=port_rule.internal_ip,
                internal_port=port_rule.internal_port,
                protocol=port_rule.protocol,
                description=port_rule.description
            )
            
            if success:
                port_rule.router = customer_router
                port_rule.save()
                messages.success(request, 'Port forwarding rule created successfully!')
                return redirect('isp_port_forwarding')
            else:
                messages.error(request, f'Failed to create rule: {message}')
    else:
        router_id = request.GET.get('router_id')
        if router_id:
            try:
                router_config = RouterConfig.objects.get(id=router_id, tenant=request.user.tenant)
                initial = {'router_config': router_config}
            except RouterConfig.DoesNotExist:
                initial = {}
        else:
            initial = {}
        
        form = ISPPortForwardingForm(tenant=request.user.tenant, initial=initial)
    
    context = {'form': form}
    return render(request, 'router/isp/add_port_forwarding.html', context)

@login_required
@isp_required
def isp_delete_port_forwarding(request, rule_id):
    """Delete port forwarding rule"""
    try:
        rule = get_object_or_404(PortForwardingRule, id=rule_id)
        # Check if router belongs to this tenant
        if not rule.router.tenant == request.user.tenant:
            messages.error(request, 'Access denied to this rule.')
            return redirect('isp_port_forwarding')
        
        # Delete from router first
        success, message = router_service.delete_port_forwarding_rule(rule)
        
        if success:
            rule.delete()
            messages.success(request, 'Port forwarding rule deleted successfully!')
        else:
            messages.error(request, f'Failed to delete rule from router: {message}')
        
        return redirect('isp_port_forwarding')
        
    except PortForwardingRule.DoesNotExist:
        messages.error(request, 'Port forwarding rule not found.')
        return redirect('isp_port_forwarding')
    except Exception as e:
        messages.error(request, f'Error: {str(e)}')
        return redirect('isp_port_forwarding')

@require_POST
@login_required
@isp_required
def isp_toggle_port_rule(request):
    """Toggle port forwarding rule status"""
    try:
        rule_id = request.POST.get('rule_id')
        rule = get_object_or_404(PortForwardingRule, id=rule_id)
        
        # Check if router belongs to this tenant
        if not rule.router.tenant == request.user.tenant:
            return JsonResponse({'error': 'Unauthorized'}, status=403)
        
        # Toggle status
        rule.is_active = not rule.is_active
        rule.save()
        
        # Update on router if active
        if rule.is_active:
            # Get the RouterConfig for this customer's router
            router_config = RouterConfig.objects.filter(
                tenant=request.user.tenant
            ).first()
            
            if router_config:
                driver = router_service.get_router_driver(router_config)
                if driver and driver.connect():
                    driver.create_port_forwarding(
                        rule.external_port,
                        rule.internal_ip,
                        rule.internal_port,
                        rule.protocol
                    )
                    driver.disconnect()
        
        return JsonResponse({
            'success': True,
            'is_active': rule.is_active,
            'message': f'Rule {"enabled" if rule.is_active else "disabled"} successfully'
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@require_POST
@login_required
@isp_required
def isp_delete_port_forwarding_ajax(request):
    """Delete port forwarding rule via AJAX"""
    try:
        rule_id = request.POST.get('rule_id')
        rule = get_object_or_404(PortForwardingRule, id=rule_id)
        
        # Check if router belongs to this tenant
        if not rule.router.tenant == request.user.tenant:
            return JsonResponse({'error': 'Unauthorized'}, status=403)
        
        # Delete from router first
        success, message = router_service.delete_port_forwarding_rule(rule)
        
        if success:
            rule.delete()
            return JsonResponse({
                'success': True,
                'message': 'Port forwarding rule deleted successfully'
            })
        else:
            return JsonResponse({
                'success': False,
                'message': f'Failed to delete rule from router: {message}'
            })
        
    except PortForwardingRule.DoesNotExist:
        return JsonResponse({'error': 'Port forwarding rule not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@isp_required
def isp_test_router_connection(request, router_id):
    """Test connection to router"""
    try:
        router_config = get_object_or_404(RouterConfig, id=router_id, tenant=request.user.tenant)
        success, message = router_service.test_connection(router_config)
        
        return JsonResponse({
            'success': success,
            'message': message,
            'router_id': router_id,
            'is_online': router_config.is_online
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@isp_required
def isp_sync_router(request, router_id):
    """Sync router status and devices"""
    try:
        router_config = get_object_or_404(RouterConfig, id=router_id, tenant=request.user.tenant)
        success, message = router_service.sync_connected_devices(router_config)
        
        if success:
            messages.success(request, f"Router {router_config.name} synced successfully")
        else:
            messages.error(request, f"Failed to sync router {router_config.name}: {message}")
        
        return redirect('isp_routers')
        
    except Exception as e:
        messages.error(request, f"Error: {str(e)}")
        return redirect('isp_routers')

@login_required
@isp_required
def isp_bulk_sync(request):
    """Bulk sync all routers"""
    try:
        router_configs = RouterConfig.objects.filter(tenant=request.user.tenant)
        success_count = 0
        total_count = router_configs.count()
        
        for config in router_configs:
            success, message = router_service.sync_connected_devices(config)
            if success:
                success_count += 1
        
        messages.success(request, f"Synced {success_count}/{total_count} routers")
        return redirect('isp_routers')
        
    except Exception as e:
        messages.error(request, f"Error: {str(e)}")
        return redirect('isp_routers')

@login_required
@isp_required
def isp_update_router_wifi(request, router_id):
    """Update WiFi settings on router"""
    try:
        router_config = get_object_or_404(RouterConfig, id=router_id, tenant=request.user.tenant)
        
        if request.method == 'POST':
            ssid = request.POST.get('ssid')
            password = request.POST.get('password')
            security_type = request.POST.get('security_type', 'wpa2')
            
            if not ssid or not password:
                messages.error(request, "SSID and password are required")
                return redirect('isp_routers')
            
            success, message = router_service.update_wifi_settings(
                router_config, ssid, password, security_type
            )
            
            if success:
                messages.success(request, message)
            else:
                messages.error(request, message)
            
            return redirect('isp_routers')
        
        # GET request - show form
        context = {
            'router_config': router_config,
            'tab': 'router-settings'
        }
        return render(request, 'router/isp/update_wifi.html', context)
        
    except Exception as e:
        messages.error(request, f"Error: {str(e)}")
        return redirect('isp_routers')

@login_required
@isp_required
def isp_remote_reboot(request, router_id):
    """Remotely reboot router"""
    try:
        router_config = get_object_or_404(RouterConfig, id=router_id, tenant=request.user.tenant)
        success, message = router_service.reboot_router(router_config)
        
        if success:
            messages.success(request, message)
        else:
            messages.error(request, message)
        
        return redirect('isp_routers')
        
    except Exception as e:
        messages.error(request, f"Error: {str(e)}")
        return redirect('isp_routers')

# ============================================================================
# ISP ROUTER SETUP SPECIFIC VIEWS
# ============================================================================

@login_required
@isp_required
def isp_router_setup_huawei(request):
    """ISP: Huawei Router Setup"""
    if request.method == 'POST':
        form = ISPAddRouterForm(request.POST)
        if form.is_valid():
            router = form.save(commit=False)
            router.tenant = request.user.tenant
            router.router_type = 'huawei'
            
            # Get additional Huawei-specific fields
            huawei_ont_id = request.POST.get('huawei_ont_id', '')
            if huawei_ont_id:
                router.huawei_ont_id = huawei_ont_id
            
            # Set default web port if not provided
            if not router.web_port:
                router.web_port = 80
            
            router.save()
            
            # Test connection immediately
            try:
                success, message = router_service.test_connection(router)
                if success:
                    messages.success(request, f'Huawei router configuration added and connection test successful!')
                else:
                    messages.warning(request, f'Huawei router configuration added but connection failed: {message}')
            except Exception as e:
                messages.success(request, f'Huawei router configuration added! Note: {str(e)}')
            
            return redirect('isp_routers')
        else:
            # Add router_type to form data if validation fails
            form.data = form.data.copy()
            form.data['router_type'] = 'huawei'
    else:
        # Pre-fill form with Huawei defaults
        initial_data = {
            'router_type': 'huawei',
            'username': 'admin',
            'web_port': 80,
        }
        form = ISPAddRouterForm(initial=initial_data)
    
    context = {
        'form': form,
        'router_type': 'Huawei',
        'help_text': 'Configure Huawei ONT devices with XML API and VLAN settings.',
        'specific_fields': [
            {'name': 'huawei_ont_id', 'label': 'ONT ID', 'required': True, 'help': 'Huawei ONT device ID (e.g., HWTC12345678)'},
            {'name': 'router_model', 'label': 'Huawei Model', 'required': True, 'help': 'e.g., HG8245H, HG8145V5, HS8546V5'},
        ],
        'driver_capabilities': [
            'XML API communication',
            'DHCP client list retrieval',
            'WLAN configuration',
            'Port forwarding via security API',
            'System reboot control',
        ]
    }
    return render(request, 'router/isp/router_setup_specific.html', context)

@login_required
@isp_required
def isp_router_setup_mikrotik(request):
    """ISP: MikroTik Router Setup with RouterOS-specific options"""
    if request.method == 'POST':
        form = ISPAddRouterForm(request.POST)
        if form.is_valid():
            router = form.save(commit=False)
            router.tenant = request.user.tenant
            router.router_type = 'mikrotik'
            
            # For MikroTik, override web port to API port
            router.web_port = 8728  # MikroTik API port
            
            router.save()
            
            # Test connection immediately
            try:
                success, message = router_service.test_connection(router)
                if success:
                    messages.success(request, f'MikroTik router configuration added and connection test successful!')
                else:
                    messages.warning(request, f'MikroTik router configuration added but connection failed: {message}')
            except Exception as e:
                messages.success(request, f'MikroTik router configuration added! Note: {str(e)}')
            
            return redirect('isp_routers')
        else:
            # Add router_type to form data if validation fails
            form.data = form.data.copy()
            form.data['router_type'] = 'mikrotik'
    else:
        # Pre-fill form with MikroTik defaults
        initial_data = {
            'router_type': 'mikrotik',
            'username': 'admin',
            'web_port': 8728,
        }
        form = ISPAddRouterForm(initial=initial_data)
    
    context = {
        'form': form,
        'router_type': 'MikroTik',
        'help_text': 'Configure MikroTik routers with RouterOS API using librouteros.',
        'specific_fields': [
            {'name': 'router_model', 'label': 'MikroTik Model', 'required': True, 'help': 'e.g., RB750Gr3, hAP ac², CCR1009'},
        ],
        'driver_capabilities': [
            'RouterOS API via librouteros',
            'DHCP leases and wireless client monitoring',
            'Firewall/NAT configuration',
            'Wireless interface management',
            'System resource monitoring',
        ]
    }
    return render(request, 'router/isp/router_setup_specific.html', context)

@login_required
@isp_required
def isp_router_setup_tenda(request):
    """ISP: Tenda Router Setup with Tenda-specific options"""
    if request.method == 'POST':
        form = ISPAddRouterForm(request.POST)
        if form.is_valid():
            router = form.save(commit=False)
            router.tenant = request.user.tenant
            router.router_type = 'tenda'
            
            # Set default web port if not provided
            if not router.web_port:
                router.web_port = 80
            
            router.save()
            
            # Test connection immediately
            try:
                success, message = router_service.test_connection(router)
                if success:
                    messages.success(request, f'Tenda router configuration added and connection test successful!')
                else:
                    messages.warning(request, f'Tenda router configuration added but connection failed: {message}')
            except Exception as e:
                messages.success(request, f'Tenda router configuration added! Note: {str(e)}')
            
            return redirect('isp_routers')
        else:
            # Add router_type to form data if validation fails
            form.data = form.data.copy()
            form.data['router_type'] = 'tenda'
    else:
        # Pre-fill form with Tenda defaults
        initial_data = {
            'router_type': 'tenda',
            'username': 'admin',
            'web_port': 80,
        }
        form = ISPAddRouterForm(initial=initial_data)
    
    context = {
        'form': form,
        'router_type': 'Tenda',
        'help_text': 'Configure Tenda routers with web interface and form-based authentication.',
        'specific_fields': [
            {'name': 'router_model', 'label': 'Tenda Model', 'required': True, 'help': 'e.g., AC10, AC18, F3, F6, FH456'},
        ],
        'driver_capabilities': [
            'Form-based authentication with MD5 hashing',
            'Client information retrieval',
            'WiFi configuration',
            'Port forwarding rules',
            'System reboot',
        ]
    }
    return render(request, 'router/isp/router_setup_specific.html', context)

@login_required
@isp_required
def isp_router_setup_tplink(request):
    """ISP: TP-Link Router Setup"""
    if request.method == 'POST':
        form = ISPAddRouterForm(request.POST)
        if form.is_valid():
            router = form.save(commit=False)
            router.tenant = request.user.tenant
            router.router_type = 'tplink'
            
            # Set default web port if not provided
            if not router.web_port:
                router.web_port = 80
            
            router.save()
            messages.success(request, 'TP-Link router configuration added successfully!')
            return redirect('isp_routers')
        else:
            # Add router_type to form data if validation fails
            form.data = form.data.copy()
            form.data['router_type'] = 'tplink'
    else:
        # Pre-fill form with TP-Link defaults
        initial_data = {
            'router_type': 'tplink',
            'username': 'admin',
            'web_port': 80,
        }
        form = ISPAddRouterForm(initial=initial_data)
    
    context = {
        'form': form,
        'router_type': 'TP-Link',
        'help_text': 'Configure TP-Link routers with Archer series and Tether app support.',
        'specific_fields': [
            {'name': 'router_model', 'label': 'TP-Link Model', 'help': 'e.g., Archer C7, Archer AX50'},
        ],
        'driver_capabilities': [
            'Coming soon - Basic web interface support',
            'WiFi configuration',
            'Device monitoring',
        ],
        'coming_soon': True
    }
    return render(request, 'router/isp/router_setup_specific.html', context)

@login_required
@isp_required
def isp_router_setup_ubiquiti(request):
    """ISP: Ubiquiti Router Setup"""
    if request.method == 'POST':
        form = ISPAddRouterForm(request.POST)
        if form.is_valid():
            router = form.save(commit=False)
            router.tenant = request.user.tenant
            router.router_type = 'ubiquiti'
            
            # Set default web port if not provided
            if not router.web_port:
                router.web_port = 443  # Ubiquiti usually uses HTTPS
            
            router.save()
            messages.success(request, 'Ubiquiti router configuration added successfully!')
            return redirect('isp_routers')
        else:
            # Add router_type to form data if validation fails
            form.data = form.data.copy()
            form.data['router_type'] = 'ubiquiti'
    else:
        # Pre-fill form with Ubiquiti defaults
        initial_data = {
            'router_type': 'ubiquiti',
            'username': 'admin',
            'web_port': 443,
        }
        form = ISPAddRouterForm(initial=initial_data)
    
    context = {
        'form': form,
        'router_type': 'Ubiquiti',
        'help_text': 'Configure Ubiquiti routers with UniFi Controller and EdgeMAX platforms.',
        'specific_fields': [
            {'name': 'router_model', 'label': 'Ubiquiti Model', 'help': 'e.g., UniFi Dream Machine, EdgeRouter 4'},
        ],
        'driver_capabilities': [
            'Coming soon - UniFi/EdgeMAX API support',
            'Centralized management',
            'Advanced networking features',
        ],
        'coming_soon': True
    }
    return render(request, 'router/isp/router_setup_specific.html', context)

@login_required
@isp_required
def isp_router_setup_other(request):
    """ISP: Other Router Setup"""
    if request.method == 'POST':
        form = ISPAddRouterForm(request.POST)
        if form.is_valid():
            router = form.save(commit=False)
            router.tenant = request.user.tenant
            router.router_type = 'other'
            
            # Set default web port if not provided
            if not router.web_port:
                router.web_port = 80
            
            router.save()
            
            # Test connection immediately
            try:
                success, message = router_service.test_connection(router)
                if success:
                    messages.success(request, f'Router configuration added and connection test successful!')
                else:
                    messages.warning(request, f'Router configuration added but connection failed: {message}')
            except Exception as e:
                messages.success(request, f'Router configuration added! Note: {str(e)}')
            
            return redirect('isp_routers')
        else:
            # Add router_type to form data if validation fails
            form.data = form.data.copy()
            form.data['router_type'] = 'other'
    else:
        # Pre-fill form with defaults
        initial_data = {
            'router_type': 'other',
            'username': 'admin',
            'web_port': 80,
        }
        form = ISPAddRouterForm(initial=initial_data)
    
    context = {
        'form': form,
        'router_type': 'Other',
        'help_text': 'Configure other router brands with generic settings.',
        'specific_fields': [
            {'name': 'router_model', 'label': 'Router Model', 'help': 'Enter router model name'},
        ],
        'driver_capabilities': [
            'Generic web interface support',
            'Basic configuration management',
            'Manual setup required',
        ]
    }
    return render(request, 'router/isp/router_setup_specific.html', context)

# ============================================================================
# ADMIN VIEWS
# ============================================================================

@staff_member_required
def admin_router_status(request):
    """Admin view for router manager status"""
    status = {
        'monitor_running': router_monitor.is_running,
        'sync_interval': router_monitor.sync_interval,
        'health': health_check(),
    }
    
    return JsonResponse(status)

@staff_member_required
def admin_router_control(request):
    """Admin control panel for router manager"""
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'start':
            if not router_monitor.is_running:
                router_monitor.start()
                return JsonResponse({'success': True, 'message': 'Router monitor started'})
            else:
                return JsonResponse({'success': False, 'message': 'Monitor already running'})
        
        elif action == 'stop':
            if router_monitor.is_running:
                router_monitor.stop()
                return JsonResponse({'success': True, 'message': 'Router monitor stopped'})
            else:
                return JsonResponse({'success': False, 'message': 'Monitor not running'})
        
        elif action == 'sync':
            router_configs = RouterConfig.objects.all()
            success_count = 0
            
            for config in router_configs:
                success, message = router_service.sync_connected_devices(config)
                if success:
                    success_count += 1
            
            return JsonResponse({
                'success': True,
                'message': f'Synced {success_count}/{len(router_configs)} routers'
            })
    
    return JsonResponse({'error': 'Invalid action'}, status=400)

@staff_member_required
def admin_discover_routers(request):
    """Admin view to discover routers in network"""
    network = request.GET.get('network', '192.168.1.0/24')
    routers = discover_routers_in_network(network)
    
    return JsonResponse({
        'network': network,
        'routers_found': len(routers),
        'routers': routers
    })