# router_manager/router_drivers/__init__.py
import importlib
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

class RouterDriverBase:
    """Base class for all router drivers"""
    
    def __init__(self, router_config):
        self.config = router_config
        self.session = None
        self.logger = logging.getLogger(f'{__name__}.{self.__class__.__name__}')
    
    def connect(self):
        """Establish connection to router"""
        raise NotImplementedError
    
    def disconnect(self):
        """Close connection to router"""
        raise NotImplementedError
    
    def get_status(self):
        """Get router status"""
        raise NotImplementedError
    
    def get_connected_devices(self):
        """Get list of connected devices"""
        raise NotImplementedError
    
    def change_wifi_settings(self, ssid, password, security_type='wpa2'):
        """Change WiFi settings"""
        raise NotImplementedError
    
    def reboot(self):
        """Reboot router"""
        raise NotImplementedError
    
    def create_port_forwarding(self, external_port, internal_ip, internal_port, protocol='tcp'):
        """Create port forwarding rule"""
        raise NotImplementedError
    
    def delete_port_forwarding(self, rule_id):
        """Delete port forwarding rule"""
        raise NotImplementedError
    
    def get_port_forwarding_rules(self):
        """Get all port forwarding rules"""
        raise NotImplementedError

class RouterDriverFactory:
    """Factory to create appropriate router driver"""
    
    @staticmethod
    def get_driver(router_config):
        """Get driver instance for router type"""
        router_type = router_config.router_type.lower()
        
        driver_classes = {
            'huawei': 'router_manager.router_drivers.huawei.HuaweiDriver',
            'mikrotik': 'router_manager.router_drivers.mikrotik.MikroTikDriver',
            'tenda': 'router_manager.router_drivers.tenda.TendaDriver',
            'ubiquiti': 'router_manager.router_drivers.ubiquiti.UbiquitiDriver',
            'tplink': 'router_manager.router_drivers.tplink.TPLinkDriver',
        }
        
        if router_type not in driver_classes:
            raise ValueError(f"No driver available for router type: {router_type}")
        
        module_path, class_name = driver_classes[router_type].rsplit('.', 1)
        
        try:
            module = importlib.import_module(module_path)
            driver_class = getattr(module, class_name)
            return driver_class(router_config)
        except (ImportError, AttributeError) as e:
            logger.error(f"Failed to load driver {router_type}: {e}")
            raise