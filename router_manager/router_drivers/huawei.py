# router_manager/router_drivers/huawei.py
import requests
from requests.auth import HTTPDigestAuth
import xml.etree.ElementTree as ET
import logging
from router_manager.router_drivers import RouterDriverBase
import time

logger = logging.getLogger(__name__)

class HuaweiDriver(RouterDriverBase):
    """Huawei router driver (supports HG8245H, HG8245Q, etc.)"""
    
    def __init__(self, router_config):
        super().__init__(router_config)
        self.base_url = f"http://{self.config.ip_address}:{self.config.web_port}"
        self.session = requests.Session()
        
    def connect(self):
        """Connect to Huawei router using digest auth"""
        try:
            # Huawei uses digest authentication
            self.session.auth = HTTPDigestAuth(self.config.username, self.config.password)
            
            # Test connection
            test_url = f"{self.base_url}/api/system/deviceinfo"
            response = self.session.get(test_url, timeout=10)
            
            if response.status_code == 200:
                self.logger.info(f"Connected to Huawei router {self.config.ip_address}")
                return True
            else:
                self.logger.error(f"Connection failed: {response.status_code}")
                return False
                
        except Exception as e:
            self.logger.error(f"Connection error: {e}")
            return False
    
    def disconnect(self):
        """Close session"""
        if self.session:
            self.session.close()
    
    def get_status(self):
        """Get router status"""
        try:
            url = f"{self.base_url}/api/monitoring/status"
            response = self.session.get(url)
            
            if response.status_code == 200:
                root = ET.fromstring(response.content)
                status_data = {}
                
                for child in root:
                    status_data[child.tag] = child.text
                
                return {
                    'is_online': True,
                    'model': status_data.get('ModelName', 'Unknown'),
                    'serial': status_data.get('SerialNumber', 'Unknown'),
                    'hardware_version': status_data.get('HardwareVersion', 'Unknown'),
                    'software_version': status_data.get('SoftwareVersion', 'Unknown'),
                    'uptime': status_data.get('UpTime', '0'),
                    'wan_status': status_data.get('WANAccessType', 'Unknown'),
                }
            return None
        except Exception as e:
            self.logger.error(f"Failed to get status: {e}")
            return {'is_online': False, 'error': str(e)}
    
    def get_connected_devices(self):
        """Get connected devices via DHCP client list"""
        try:
            url = f"{self.base_url}/api/wlan/host-list"
            response = self.session.get(url)
            
            if response.status_code == 200:
                root = ET.fromstring(response.content)
                devices = []
                
                for host in root.findall('.//Host'):
                    device = {
                        'mac_address': host.find('MACAddress').text if host.find('MACAddress') else '',
                        'ip_address': host.find('IPAddress').text if host.find('IPAddress') else '',
                        'hostname': host.find('HostName').text if host.find('HostName') else '',
                        'interface': host.find('InterfaceType').text if host.find('InterfaceType') else '',
                        'lease_time': host.find('LeaseTime').text if host.find('LeaseTime') else '',
                    }
                    devices.append(device)
                
                return devices
            return []
        except Exception as e:
            self.logger.error(f"Failed to get devices: {e}")
            return []
    
    def change_wifi_settings(self, ssid, password, security_type='wpa2'):
        """Change WiFi settings on Huawei router"""
        try:
            # First get current settings to get the WLAN ID
            url = f"{self.base_url}/api/wlan/network"
            response = self.session.get(url)
            
            if response.status_code != 200:
                raise Exception("Failed to get current WiFi settings")
            
            root = ET.fromstring(response.content)
            wlan_id = root.find('.//WLANID')
            
            if not wlan_id:
                raise Exception("WLAN ID not found")
            
            # Prepare XML for WiFi settings update
            security_map = {
                'wpa2': 'WPA2-PSK',
                'wpa3': 'WPA3-PSK',
                'wpa': 'WPA-PSK',
                'wep': 'WEP',
                'none': 'None',
            }
            
            security = security_map.get(security_type, 'WPA2-PSK')
            
            xml_data = f"""<?xml version="1.0" encoding="UTF-8"?>
            <request>
                <WLANConfiguration>
                    <WLANID>{wlan_id.text}</WLANID>
                    <WLANSSID>{ssid}</WLANSSID>
                    <WLANAuthMode>{security}</WLANAuthMode>
                    <WLANEncryptType>AES</WLANEncryptType>
                    <WLANKey>{password}</WLANKey>
                    <BeaconType>11i</BeaconType>
                    <WLANEnable>1</WLANEnable>
                </WLANConfiguration>
            </request>"""
            
            # Send update
            update_url = f"{self.base_url}/api/wlan/network"
            headers = {'Content-Type': 'application/xml'}
            response = self.session.post(update_url, data=xml_data, headers=headers)
            
            if response.status_code == 200:
                # Check if operation succeeded
                resp_root = ET.fromstring(response.content)
                if resp_root.find('.//response') is not None:
                    return True
            
            return False
            
        except Exception as e:
            self.logger.error(f"Failed to change WiFi settings: {e}")
            return False
    
    def reboot(self):
        """Reboot Huawei router"""
        try:
            xml_data = """<?xml version="1.0" encoding="UTF-8"?>
            <request>
                <Control>1</Control>
            </request>"""
            
            url = f"{self.base_url}/api/device/control"
            headers = {'Content-Type': 'application/xml'}
            response = self.session.post(url, data=xml_data, headers=headers)
            
            return response.status_code == 200
        except Exception as e:
            self.logger.error(f"Failed to reboot: {e}")
            return False
    
    def create_port_forwarding(self, external_port, internal_ip, internal_port, protocol='tcp'):
        """Create port forwarding rule on Huawei router"""
        try:
            # Generate a unique rule name
            rule_name = f"CloudConnect_{external_port}_{protocol}"
            
            xml_data = f"""<?xml version="1.0" encoding="UTF-8"?>
            <request>
                <PortMapping>
                    <Enable>1</Enable>
                    <Name>{rule_name}</Name>
                    <ExternalPort>{external_port}</ExternalPort>
                    <InternalPort>{internal_port}</InternalPort>
                    <InternalClient>{internal_ip}</InternalClient>
                    <Protocol>{protocol.upper()}</Protocol>
                    <Status>1</Status>
                </PortMapping>
            </request>"""
            
            url = f"{self.base_url}/api/security/port-mapping"
            headers = {'Content-Type': 'application/xml'}
            response = self.session.post(url, data=xml_data, headers=headers)
            
            return response.status_code == 200
            
        except Exception as e:
            self.logger.error(f"Failed to create port forwarding: {e}")
            return False
    
    def get_port_forwarding_rules(self):
        """Get all port forwarding rules"""
        try:
            url = f"{self.base_url}/api/security/port-mapping"
            response = self.session.get(url)
            
            if response.status_code == 200:
                root = ET.fromstring(response.content)
                rules = []
                
                for rule in root.findall('.//PortMapping'):
                    rule_data = {
                        'id': rule.find('Index').text if rule.find('Index') else '',
                        'name': rule.find('Name').text if rule.find('Name') else '',
                        'external_port': rule.find('ExternalPort').text if rule.find('ExternalPort') else '',
                        'internal_port': rule.find('InternalPort').text if rule.find('InternalPort') else '',
                        'internal_ip': rule.find('InternalClient').text if rule.find('InternalClient') else '',
                        'protocol': rule.find('Protocol').text if rule.find('Protocol') else '',
                        'enabled': rule.find('Enable').text == '1' if rule.find('Enable') else False,
                    }
                    rules.append(rule_data)
                
                return rules
            return []
        except Exception as e:
            self.logger.error(f"Failed to get port forwarding rules: {e}")
            return []