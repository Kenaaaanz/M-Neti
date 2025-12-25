# router_manager/services.py
import logging
import concurrent.futures
from datetime import timedelta
from django.utils import timezone
from django.db import transaction
from .router_drivers import RouterDriverFactory

logger = logging.getLogger(__name__)


class RouterManagerService:
    """On-demand service for managing router communications"""
    
    def __init__(self):
        from .models import Router, RouterConfig, ConnectedDevice, PortForwardingRule, RouterLog

        # Thread pool for async operations
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)
    
    def get_router_driver(self, router_config):
        """Get driver for router configuration"""
        try:
            return RouterDriverFactory.get_driver(router_config)
        except Exception as e:
            logger.error(f"Failed to get driver for {router_config}: {e}")
            return None
    
    def test_connection(self, router_config):
        """Test connection to router (on-demand)"""
        try:
            driver = self.get_router_driver(router_config)
            if not driver:
                return False, "No driver available"
            
            if driver.connect():
                status = driver.get_status()
                driver.disconnect()
                
                if status and status.get('is_online'):
                    # Update router status
                    router_config.is_online = True
                    router_config.last_checked = timezone.now()
                    router_config.save()
                    return True, "Connection successful"
            
            router_config.is_online = False
            router_config.save()
            return False, "Connection failed"
            
        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            return False, str(e)
    
    def get_router_status(self, router_config, force_check=False):
        """Get router status - cached or fresh (on-demand)"""
        # Use cached status if recent and not forced
        if not force_check and router_config.last_checked:
            time_since_check = timezone.now() - router_config.last_checked
            if time_since_check < timedelta(minutes=5):
                return {
                    'is_online': router_config.is_online,
                    'last_checked': router_config.last_checked,
                    'cached': True,
                    'message': 'Using cached status'
                }
        
        # Perform fresh check
        success, message = self.test_connection(router_config)
        
        return {
            'is_online': success,
            'last_checked': router_config.last_checked,
            'cached': False,
            'message': message
        }
    
    def sync_connected_devices(self, router_config):
        """Sync connected devices from router (on-demand)"""
        try:
            driver = self.get_router_driver(router_config)
            if not driver or not driver.connect():
                return False, "Failed to connect to router"
            
            # Get devices from router
            devices_data = driver.get_connected_devices()
            driver.disconnect()
            
            updated_count = 0
            with transaction.atomic():
                for device_data in devices_data:
                    mac_address = device_data.get('mac_address', '').upper()
                    if not mac_address:
                        continue
                    
                    # Create or update device
                    from .models import Router, RouterConfig, ConnectedDevice, PortForwardingRule, RouterLog

                    device, created = ConnectedDevice.objects.update_or_create(
                        router=router_config.router,
                        mac_address=mac_address,
                        defaults={
                            'name': device_data.get('hostname', ''),
                            'ip_address': device_data.get('ip_address', ''),
                            'device_type': self._detect_device_type(device_data),
                            'connection_type': device_data.get('interface', 'wireless_2.4'),
                            'signal_strength': device_data.get('signal_strength'),
                            'last_seen': timezone.now(),
                            'is_active': True,
                        }
                    )
                    
                    if not created:
                        # Update existing device
                        device.ip_address = device_data.get('ip_address', device.ip_address)
                        device.name = device_data.get('hostname', device.name)
                        device.last_seen = timezone.now()
                        device.is_active = True
                        device.save()
                    
                    updated_count += 1
                
                # Mark old devices as inactive
                active_macs = {d.get('mac_address', '').upper() for d in devices_data}
                ConnectedDevice.objects.filter(
                    router=router_config.router,
                    last_seen__lt=timezone.now() - timedelta(minutes=10)
                ).update(is_active=False)
            
            # Log the sync
            RouterLog.objects.create(
                router=router_config.router,
                log_type='connection',
                message=f'Synced {updated_count} devices from router'
            )
            
            return True, f"Successfully synced {updated_count} devices"
            
        except Exception as e:
            logger.error(f"Failed to sync devices: {e}")
            return False, str(e)
    
    def _detect_device_type(self, device_data):
        """Detect device type from data"""
        hostname = (device_data.get('hostname', '') or '').lower()
        
        if any(keyword in hostname for keyword in ['iphone', 'android', 'mobile', 'phone']):
            return 'phone'
        elif any(keyword in hostname for keyword in ['ipad', 'tablet']):
            return 'tablet'
        elif any(keyword in hostname for keyword in ['tv', 'smarttv', 'roku', 'firetv']):
            return 'tv'
        elif any(keyword in hostname for keyword in ['laptop', 'macbook', 'pc', 'desktop']):
            return 'computer'
        else:
            return 'other'
    
    def get_port_forwarding_rules(self, router_config):
        """Get port forwarding rules from router (on-demand)"""
        try:
            driver = self.get_router_driver(router_config)
            if not driver or not driver.connect():
                return False, "Failed to connect", []
            
            rules_data = driver.get_port_forwarding_rules()
            driver.disconnect()
            
            # Sync with database
            from .models import Router, RouterConfig, ConnectedDevice, PortForwardingRule, RouterLog

            with transaction.atomic():
                for rule_data in rules_data:
                    PortForwardingRule.objects.update_or_create(
                        router=router_config,
                        external_port=rule_data.get('external_port'),
                        internal_ip=rule_data.get('internal_ip'),
                        internal_port=rule_data.get('internal_port'),
                        protocol=rule_data.get('protocol', 'tcp').lower(),
                        defaults={
                            'is_active': rule_data.get('enabled', True),
                            'description': rule_data.get('name', ''),
                        }
                    )
            
            return True, "Rules synced successfully", rules_data
            
        except Exception as e:
            logger.error(f"Failed to get port forwarding rules: {e}")
            return False, str(e), []
    
    def update_wifi_settings(self, router_config, ssid, password, security_type='wpa2'):
        """Update WiFi settings on router (on-demand)"""
        try:
            driver = self.get_router_driver(router_config)
            if not driver or not driver.connect():
                return False, "Failed to connect"
            
            success = driver.change_wifi_settings(ssid, password, security_type)
            driver.disconnect()
            
            if success:
                from .models import Router, RouterConfig, ConnectedDevice, PortForwardingRule, RouterLog

                # Update local router model
                try:
                    router = Router.objects.get(router_config=router_config)
                    router.ssid = ssid
                    router.password = password
                    router.security_type = security_type
                    router.save()
                    
                    RouterLog.objects.create(
                        router=router,
                        log_type='config_change',
                        message=f'WiFi settings updated: SSID={ssid}'
                    )
                except Router.DoesNotExist:
                    pass
                
                return True, "WiFi settings updated successfully"
            else:
                return False, "Failed to update WiFi settings"
                
        except Exception as e:
            logger.error(f"Failed to update WiFi settings: {e}")
            return False, str(e)
    
    def create_port_forwarding_rule(self, router_config, customer, external_port, 
                                   internal_ip, internal_port, protocol='tcp', description=""):
        """Create port forwarding rule on router (on-demand)"""
        try:
            driver = self.get_router_driver(router_config)
            if not driver or not driver.connect():
                return False, "Failed to connect to router", None
            
            success = driver.create_port_forwarding(external_port, internal_ip, internal_port, protocol)
            driver.disconnect()
            
            if success:
                from .models import Router, RouterConfig, ConnectedDevice, PortForwardingRule, RouterLog

                # Create database record
                rule = PortForwardingRule.objects.create(
                    router=router_config,
                    customer=customer,
                    external_port=external_port,
                    internal_ip=internal_ip,
                    internal_port=internal_port,
                    protocol=protocol,
                    is_active=True,
                    description=description or f"Port {external_port} forwarding",
                )
                
                # Log the action
                from .models import Router, RouterConfig, ConnectedDevice, PortForwardingRule, RouterLog

                if hasattr(router_config, 'router'):
                    RouterLog.objects.create(
                        router=router_config.router,
                        log_type='config_change',
                        message=f'Port forwarding created: {external_port} -> {internal_ip}:{internal_port}'
                    )
                
                return True, "Port forwarding rule created successfully", rule
            
            return False, "Failed to create port forwarding on router", None
            
        except Exception as e:
            logger.error(f"Failed to create port forwarding: {e}")
            return False, str(e), None
    
    def delete_port_forwarding_rule(self, rule):
        """Delete port forwarding rule from router (on-demand)"""
        try:
            driver = self.get_router_driver(rule.router)
            if not driver or not driver.connect():
                return False, "Failed to connect to router"
            
            # Note: This assumes driver has delete_port_forwarding method
            # If not implemented, we'll just disable it locally
            success = True
            if hasattr(driver, 'delete_port_forwarding'):
                success = driver.delete_port_forwarding(rule.external_port, rule.protocol)
            
            driver.disconnect()
            
            if success:
                rule.is_active = False
                rule.save()
                
                # Log the action
                from .models import Router, RouterConfig, ConnectedDevice, PortForwardingRule, RouterLog

                if hasattr(rule.router, 'router'):
                    RouterLog.objects.create(
                        router=rule.router.router,
                        log_type='config_change',
                        message=f'Port forwarding removed: {rule.external_port}'
                    )
                
                return True, "Port forwarding rule removed"
            
            return False, "Failed to remove port forwarding rule"
            
        except Exception as e:
            logger.error(f"Failed to remove port forwarding: {e}")
            return False, str(e)
    
    def reboot_router(self, router_config):
        """Reboot router (on-demand)"""
        try:
            driver = self.get_router_driver(router_config)
            if not driver or not driver.connect():
                return False, "Failed to connect"
            
            success = driver.reboot()
            driver.disconnect()
            
            if success:
                router_config.is_online = False
                router_config.save()
                
                # Log the action
                from .models import Router, RouterConfig, ConnectedDevice, PortForwardingRule, RouterLog

                if hasattr(router_config, 'router'):
                    RouterLog.objects.create(
                        router=router_config.router,
                        log_type='reboot',
                        message='Router reboot initiated'
                    )
                
                return True, "Router reboot initiated"
            
            return False, "Failed to reboot router"
            
        except Exception as e:
            logger.error(f"Failed to reboot router: {e}")
            return False, str(e)
    
    # Async methods for better UX
    def async_test_connection(self, router_config):
        """Test connection asynchronously"""
        return self.executor.submit(self.test_connection, router_config)
    
    def async_sync_devices(self, router_config):
        """Sync devices asynchronously"""
        return self.executor.submit(self.sync_connected_devices, router_config)
    
    def async_create_port_forwarding(self, router_config, **kwargs):
        """Create port forwarding asynchronously"""
        return self.executor.submit(self.create_port_forwarding_rule, router_config, **kwargs)


class PortManagementService:
    """On-demand service for managing customer port forwarding assignments"""
    
    def __init__(self):
        self.port_range_start = 10000
        self.port_range_end = 20000
    
    def assign_customer_port(self, customer, router_config):
        """Assign a unique external port for customer"""
        from .models import Router, RouterConfig, ConnectedDevice, PortForwardingRule, RouterLog

        # Get used ports
        used_ports = PortForwardingRule.objects.filter(
            router=router_config,
            is_active=True
        ).values_list('external_port', flat=True)
        
        # Find available port
        for port in range(self.port_range_start, self.port_range_end + 1):
            if port not in used_ports:
                return port
        
        raise Exception("No available ports in range")
    
    def get_available_ports(self, router_config, limit=10):
        from .models import Router, RouterConfig, ConnectedDevice, PortForwardingRule, RouterLog

        """Get list of available ports for assignment"""
        used_ports = PortForwardingRule.objects.filter(
            router=router_config,
            is_active=True
        ).values_list('external_port', flat=True)
        
        available_ports = []
        for port in range(self.port_range_start, self.port_range_end + 1):
            if port not in used_ports:
                available_ports.append(port)
                if len(available_ports) >= limit:
                    break
        
        return available_ports
    
    def get_customer_ip(self, customer, router_config):
        from .models import Router, RouterConfig, ConnectedDevice, PortForwardingRule, RouterLog

        """Get customer's IP address from connected devices (on-demand)"""
        try:
            # Look for device with customer's username in hostname
            device = ConnectedDevice.objects.filter(
                router=router_config.router,
                name__icontains=customer.username,
                is_active=True
            ).first()
            
            if device:
                return device.ip_address
            
            # Fallback to any active device
            device = ConnectedDevice.objects.filter(
                router=router_config.router,
                is_active=True
            ).first()
            
            if device:
                return device.ip_address
            
            # If no devices found, sync and try again
            router_manager = RouterManagerService()
            success, message = router_manager.sync_connected_devices(router_config)
            
            if success:
                # Try again after sync
                device = ConnectedDevice.objects.filter(
                    router=router_config.router,
                    is_active=True
                ).first()
                
                if device:
                    return device.ip_address
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to get customer IP: {e}")
            return None
    
    def setup_customer_port_forwarding(self, customer, router_config):
        """Set up port forwarding for a customer (on-demand)"""
        try:
            # Assign external port
            external_port = self.assign_customer_port(customer, router_config)
            
            # Get customer's device IP
            customer_ip = self.get_customer_ip(customer, router_config)
            
            if not customer_ip:
                return False, "Could not determine customer IP address", None
            
            # Create port forwarding rule
            router_manager = RouterManagerService()
            success, message, rule = router_manager.create_port_forwarding_rule(
                router_config=router_config,
                customer=customer,
                external_port=external_port,
                internal_ip=customer_ip,
                internal_port=80,  # Default web port
                protocol='tcp',
                description=f"Web access for {customer.username}"
            )
            
            if success:
                return True, f"Port {external_port} assigned successfully", rule
            else:
                return False, message, None
                
        except Exception as e:
            logger.error(f"Port forwarding setup error: {e}")
            return False, str(e), None


# Singleton instances
router_manager = RouterManagerService()
port_service = PortManagementService()


# Utility functions (removed background monitoring)
def get_router_client(router_config):
    """Compatibility function for existing code"""
    return router_manager.get_router_driver(router_config)


def discover_routers_in_network(network_range):
    """Discover routers in a network range (on-demand)"""
    import socket
    import ipaddress
    
    discovered_routers = []
    
    try:
        network = ipaddress.ip_network(network_range)
        
        # Common router ports to check
        ports = [80, 443, 8080, 8443, 22, 23]
        
        for ip in network.hosts():
            ip_str = str(ip)
            
            # Skip the network and broadcast addresses
            if ip_str.endswith('.0') or ip_str.endswith('.255'):
                continue
            
            for port in ports:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(1)  # 1 second timeout
                    result = sock.connect_ex((ip_str, port))
                    sock.close()
                    
                    if result == 0:
                        # Port is open, likely a router
                        discovered_routers.append({
                            'ip_address': ip_str,
                            'port': port,
                            'status': 'reachable'
                        })
                        break  # Found a port, move to next IP
                        
                except:
                    continue
    
    except Exception as e:
        logger.error(f"Router discovery failed: {e}")
    
    return discovered_routers


def health_check():
    """Check health of router services (on-demand)"""
    from .models import RouterConfig, PortForwardingRule
    
    health_status = {
        'active_router_configs': RouterConfig.objects.count(),
        'online_routers': RouterConfig.objects.filter(is_online=True).count(),
        'total_port_rules': PortForwardingRule.objects.filter(is_active=True).count(),
        'service_status': 'active',
    }
    
    # Test connection to a sample router if any exist
    try:
        sample_router = RouterConfig.objects.first()
        if sample_router:
            success, message = router_manager.test_connection(sample_router)
            health_status['sample_connection_test'] = {
                'success': success,
                'message': message,
                'router': sample_router.name
            }
    except Exception as e:
        health_status['sample_connection_test'] = {
            'success': False,
            'error': str(e)
        }
    
    return health_status


class RouterMonitor:
    """Background monitoring service for routers"""
    
    def __init__(self):
        from .models import RouterConfig
        
        self.is_running = False
        self.monitoring_thread = None
        self.sync_interval = 300  # 5 minutes default
        self._stop_event = None
    
    def start(self, interval=None):
        """Start background monitoring"""
        import threading
        import time
        
        if self.is_running:
            logger.warning("RouterMonitor is already running")
            return
        
        if interval:
            self.sync_interval = interval
        
        self.is_running = True
        self._stop_event = threading.Event()
        
        self.monitoring_thread = threading.Thread(
            target=self._monitoring_loop,
            daemon=True,
            name="RouterMonitor"
        )
        self.monitoring_thread.start()
        
        logger.info(f"RouterMonitor started with {self.sync_interval} second interval")
    
    def stop(self):
        """Stop background monitoring"""
        if not self.is_running:
            return
        
        self.is_running = False
        if self._stop_event:
            self._stop_event.set()
        
        if self.monitoring_thread:
            self.monitoring_thread.join(timeout=5)
        
        logger.info("RouterMonitor stopped")
    
    def _monitoring_loop(self):
        """Main monitoring loop"""
        import time
        
        logger.info("RouterMonitor loop started")
        
        while self.is_running and not self._stop_event.is_set():
            try:
                self._perform_monitoring_cycle()
            except Exception as e:
                logger.error(f"Error in monitoring cycle: {e}")
            
            # Sleep until next cycle or stop event
            self._stop_event.wait(self.sync_interval)
    
    def _perform_monitoring_cycle(self):
        """Perform one monitoring cycle"""
        from .models import RouterConfig
        from django.utils import timezone
        
        # Get all active router configs
        router_configs = RouterConfig.objects.filter(is_online=True)
        
        logger.debug(f"Monitoring {router_configs.count()} routers")
        
        # Use existing RouterManagerService for operations
        router_service = RouterManagerService()
        
        for config in router_configs:
            try:
                # Test connection
                success, message = router_service.test_connection(config)
                
                if success:
                    # Sync devices if online
                    router_service.sync_connected_devices(config)
                else:
                    logger.warning(f"Router {config.name} is offline: {message}")
                    
            except Exception as e:
                logger.error(f"Error monitoring router {config.name}: {e}")
                continue
    
    def get_status(self):
        """Get monitor status"""
        return {
            'is_running': self.is_running,
            'sync_interval': self.sync_interval,
            'thread_alive': self.monitoring_thread.is_alive() if self.monitoring_thread else False
        }
    
    def set_sync_interval(self, interval):
        """Update sync interval"""
        if interval < 30:
            raise ValueError("Interval must be at least 30 seconds")
        
        old_interval = self.sync_interval
        self.sync_interval = interval
        
        logger.info(f"Sync interval changed from {old_interval} to {interval} seconds")
        
        # Restart monitoring with new interval if running
        if self.is_running:
            self.stop()
            self.start(interval)
    
    def force_sync(self):
        """Force immediate synchronization"""
        if not self.is_running:
            logger.warning("Monitor not running, starting one-time sync")
        
        self._perform_monitoring_cycle()
        
        logger.info("Forced sync completed")


# Add RouterMonitor to the exports and create an instance

# Singleton instances (add to existing ones)
router_manager = RouterManagerService()
port_service = PortManagementService()
router_monitor = RouterMonitor()  