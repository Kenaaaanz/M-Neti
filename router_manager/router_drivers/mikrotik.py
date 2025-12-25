# router_manager/router_drivers/mikrotik.py
from librouteros import connect
from librouteros.exceptions import TrapError, ConnectionError
import logging
from router_manager.router_drivers import RouterDriverBase

logger = logging.getLogger(__name__)

class MikroTikDriver(RouterDriverBase):
    """MikroTik router driver using RouterOS API"""
    
    def __init__(self, router_config):
        super().__init__(router_config)
        self.api = None
        
    def connect(self):
        """Connect to MikroTik RouterOS API"""
        try:
            self.api = connect(
                username=self.config.username,
                password=self.config.password,
                host=self.config.ip_address,
                port=self.config.web_port or 8728,  # Default API port
                timeout=10
            )
            self.logger.info(f"Connected to MikroTik router {self.config.ip_address}")
            return True
        except (ConnectionError, TrapError) as e:
            self.logger.error(f"Connection failed: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from API"""
        if self.api:
            self.api.close()
    
    def get_status(self):
        """Get router status"""
        try:
            # Get system info
            sys_info = self.api('/system/routerboard/getall')[0]
            
            # Get system resources
            resources = self.api('/system/resource/getall')[0]
            
            # Get identity
            identity = self.api('/system/identity/getall')[0]
            
            return {
                'is_online': True,
                'model': sys_info.get('model', 'Unknown'),
                'serial': sys_info.get('serial-number', 'Unknown'),
                'firmware': resources.get('version', 'Unknown'),
                'board_name': sys_info.get('board-name', 'Unknown'),
                'uptime': resources.get('uptime', '0'),
                'cpu_load': resources.get('cpu-load', '0'),
                'memory_usage': resources.get('used-memory', '0'),
                'identity': identity.get('name', 'Unknown'),
            }
        except Exception as e:
            self.logger.error(f"Failed to get status: {e}")
            return {'is_online': False, 'error': str(e)}
    
    def get_connected_devices(self):
        """Get connected devices via DHCP leases and wireless registrations"""
        devices = []
        
        try:
            # Get DHCP leases
            leases = self.api('/ip/dhcp-server/lease/print')
            for lease in leases:
                if lease.get('active-address'):
                    device = {
                        'mac_address': lease.get('mac-address', ''),
                        'ip_address': lease.get('active-address', ''),
                        'hostname': lease.get('host-name', ''),
                        'status': 'dhcp',
                        'expires': lease.get('expires-after', ''),
                    }
                    devices.append(device)
            
            # Get wireless registrations
            wireless_clients = self.api('/interface/wireless/registration-table/print')
            for client in wireless_clients:
                device = {
                    'mac_address': client.get('mac-address', ''),
                    'ip_address': client.get('last-ip', ''),
                    'hostname': client.get('last-ip', ''),  # MikroTik doesn't store hostname here
                    'interface': client.get('interface', ''),
                    'signal_strength': client.get('signal-strength', ''),
                    'tx_rate': client.get('tx-rate', ''),
                    'rx_rate': client.get('rx-rate', ''),
                    'status': 'wireless',
                }
                devices.append(device)
            
            return devices
            
        except Exception as e:
            self.logger.error(f"Failed to get devices: {e}")
            return []
    
    def change_wifi_settings(self, ssid, password, security_type='wpa2'):
        """Change WiFi settings on MikroTik"""
        try:
            # Find wireless interface
            interfaces = self.api('/interface/wireless/print')
            if not interfaces:
                raise Exception("No wireless interfaces found")
            
            wireless_interface = interfaces[0]['name']
            
            # Map security types to MikroTik settings
            security_map = {
                'wpa2': 'wpa2-psk',
                'wpa3': 'wpa3',
                'wpa': 'wpa-psk',
                'none': 'none',
            }
            
            security_profile = security_map.get(security_type, 'wpa2-psk')
            
            # Update SSID
            self.api('/interface/wireless/set', {
                '.id': wireless_interface,
                'ssid': ssid,
            })
            
            # Update security profile
            self.api('/interface/wireless/security-profiles/set', {
                '.id': 'default',
                'mode': 'dynamic-keys',
                'authentication-types': security_profile,
                'unicast-ciphers': 'aes-ccm',
                'group-ciphers': 'aes-ccm',
                'wpa-pre-shared-key': password if security_type != 'none' else '',
                'wpa2-pre-shared-key': password if security_type in ['wpa2', 'wpa3'] else '',
            })
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to change WiFi settings: {e}")
            return False
    
    def reboot(self):
        """Reboot MikroTik router"""
        try:
            self.api('/system/reboot')
            return True
        except Exception as e:
            self.logger.error(f"Failed to reboot: {e}")
            return False
    
    def create_port_forwarding(self, external_port, internal_ip, internal_port, protocol='tcp'):
        """Create port forwarding rule on MikroTik"""
        try:
            rule_name = f"cloudconnect-{external_port}-{protocol}"
            
            # Create NAT rule
            self.api('/ip/firewall/nat/add', {
                'chain': 'dstnat',
                'dst-port': str(external_port),
                'protocol': protocol,
                'in-interface': 'ether1',  # Default WAN interface
                'action': 'dst-nat',
                'to-addresses': internal_ip,
                'to-ports': str(internal_port),
                'comment': rule_name,
            })
            
            # Create firewall accept rule
            self.api('/ip/firewall/filter/add', {
                'chain': 'forward',
                'dst-address': internal_ip,
                'dst-port': str(internal_port),
                'protocol': protocol,
                'action': 'accept',
                'comment': rule_name,
            })
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to create port forwarding: {e}")
            return False
    
    def get_port_forwarding_rules(self):
        """Get all port forwarding rules"""
        try:
            rules = []
            
            # Get NAT rules
            nat_rules = self.api('/ip/firewall/nat/print')
            for rule in nat_rules:
                if rule.get('action') == 'dst-nat' and rule.get('comment', '').startswith('cloudconnect'):
                    rule_data = {
                        'id': rule.get('.id'),
                        'name': rule.get('comment', ''),
                        'external_port': rule.get('dst-port', ''),
                        'internal_port': rule.get('to-ports', ''),
                        'internal_ip': rule.get('to-addresses', ''),
                        'protocol': rule.get('protocol', 'tcp'),
                        'enabled': not rule.get('disabled', False),
                    }
                    rules.append(rule_data)
            
            return rules
            
        except Exception as e:
            self.logger.error(f"Failed to get port forwarding rules: {e}")
            return []