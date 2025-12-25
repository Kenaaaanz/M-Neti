# router_manager/router_drivers/tenda.py
import requests
import json
import hashlib
import logging
from router_manager.router_drivers import RouterDriverBase

logger = logging.getLogger(__name__)

class TendaDriver(RouterDriverBase):
    """Tenda router driver (supports AC10, AC18, F3, F6, etc.)"""
    
    def __init__(self, router_config):
        super().__init__(router_config)
        self.base_url = f"http://{self.config.ip_address}:{self.config.web_port}"
        self.session = requests.Session()
        self.token = None
        self.stok = None
        
    def connect(self):
        """Connect to Tenda router (login and get token)"""
        try:
            # Tenda routers usually use form-based login
            login_url = f"{self.base_url}/login/Auth"
            
            # Hash the password (some Tenda models use MD5)
            password_hash = hashlib.md5(self.config.password.encode()).hexdigest()
            
            login_data = {
                'username': self.config.username,
                'password': password_hash,
            }
            
            response = self.session.post(login_url, data=login_data, timeout=10)
            
            if response.status_code == 200:
                # Try to extract token from response
                try:
                    result = response.json()
                    if 'stok' in result:
                        self.stok = result['stok']
                        self.logger.info(f"Connected to Tenda router {self.config.ip_address}")
                        return True
                except:
                    # Some models don't use JSON, check for successful redirect
                    if response.url != login_url:
                        self.logger.info(f"Connected to Tenda router {self.config.ip_address}")
                        return True
            
            return False
            
        except Exception as e:
            self.logger.error(f"Connection error: {e}")
            return False
    
    def disconnect(self):
        """Logout and close session"""
        try:
            if self.stok:
                logout_url = f"{self.base_url}/logout?stok={self.stok}"
                self.session.get(logout_url)
        except:
            pass
        finally:
            if self.session:
                self.session.close()
    
    def _make_request(self, endpoint, data=None):
        """Make authenticated request to Tenda router"""
        try:
            url = f"{self.base_url}/{endpoint}"
            if self.stok:
                url += f"?stok={self.stok}"
            
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'Referer': f"{self.base_url}/main.html"
            }
            
            if data:
                response = self.session.post(url, data=data, headers=headers, timeout=10)
            else:
                response = self.session.get(url, headers=headers, timeout=10)
            
            return response
        except Exception as e:
            self.logger.error(f"Request failed: {e}")
            return None
    
    def get_status(self):
        """Get router status"""
        try:
            response = self._make_request("goform/getStatus")
            if response and response.status_code == 200:
                data = response.json()
                
                return {
                    'is_online': True,
                    'model': data.get('product_type', 'Unknown'),
                    'hardware_version': data.get('hardware_version', 'Unknown'),
                    'firmware_version': data.get('firmware_version', 'Unknown'),
                    'wan_ip': data.get('wan_ip', ''),
                    'lan_ip': self.config.ip_address,
                    'uptime': data.get('up_time', '0'),
                    'connected_devices': data.get('station_count', 0),
                }
            return {'is_online': False}
        except Exception as e:
            self.logger.error(f"Failed to get status: {e}")
            return {'is_online': False, 'error': str(e)}
    
    def get_connected_devices(self):
        """Get connected devices"""
        try:
            # Try different endpoints for different Tenda models
            endpoints = [
                "goform/getClientInfo",
                "goform/getWifiClientInfo",
                "goform/getDHCPClientList"
            ]
            
            for endpoint in endpoints:
                response = self._make_request(endpoint)
                if response and response.status_code == 200:
                    try:
                        data = response.json()
                        devices = []
                        
                        # Parse based on response structure
                        if 'client_info' in data:
                            for device in data['client_info']:
                                devices.append({
                                    'mac_address': device.get('mac', ''),
                                    'ip_address': device.get('ip', ''),
                                    'hostname': device.get('hostname', ''),
                                    'interface': 'wireless' if device.get('wireless') else 'wired',
                                })
                        elif isinstance(data, list):
                            for device in data:
                                devices.append({
                                    'mac_address': device.get('mac', ''),
                                    'ip_address': device.get('ip', ''),
                                    'hostname': device.get('name', ''),
                                })
                        
                        if devices:
                            return devices
                    except:
                        continue
            
            return []
            
        except Exception as e:
            self.logger.error(f"Failed to get devices: {e}")
            return []
    
    def change_wifi_settings(self, ssid, password, security_type='wpa2'):
        """Change WiFi settings on Tenda router"""
        try:
            # First get current wireless settings
            response = self._make_request("goform/getWifiInfo")
            if not response or response.status_code != 200:
                return False
            
            wifi_info = response.json()
            
            # Map security types to Tenda values
            security_map = {
                'wpa2': 'WPA2-PSK',
                'wpa': 'WPA-PSK',
                'wep': 'WEP',
                'none': 'NONE',
            }
            
            security = security_map.get(security_type, 'WPA2-PSK')
            encryption = 'AES' if security_type in ['wpa2', 'wpa3'] else 'TKIP'
            
            # Prepare update data
            update_data = {
                'ssid': ssid,
                'security': security,
                'wep_key': '',
                'wpa_enc': encryption,
                'wpa_key': password if security != 'NONE' else '',
                'channel': wifi_info.get('channel', 'auto'),
                'bandwidth': wifi_info.get('bandwidth', '20MHz'),
                'wireless_mode': wifi_info.get('wireless_mode', '11bgn mixed'),
            }
            
            # Send update
            response = self._make_request("goform/setWifiInfo", update_data)
            
            if response and response.status_code == 200:
                result = response.json()
                return result.get('result', 0) == 0
            
            return False
            
        except Exception as e:
            self.logger.error(f"Failed to change WiFi settings: {e}")
            return False
    
    def reboot(self):
        """Reboot Tenda router"""
        try:
            response = self._make_request("goform/sysReboot", {'action': 'reboot'})
            return response and response.status_code == 200
        except Exception as e:
            self.logger.error(f"Failed to reboot: {e}")
            return False
    
    def create_port_forwarding(self, external_port, internal_ip, internal_port, protocol='tcp'):
        """Create port forwarding rule on Tenda router"""
        try:
            # Get current port forwarding rules
            response = self._make_request("goform/getPortForwardList")
            if not response or response.status_code != 200:
                return False
            
            current_rules = response.json().get('port_forward_list', [])
            
            # Create new rule
            rule_id = len(current_rules) + 1
            new_rule = {
                'id': str(rule_id),
                'enable': '1',
                'name': f'CloudConnect_{external_port}',
                'protocol': protocol.upper(),
                'external_port': str(external_port),
                'internal_port': str(internal_port),
                'internal_ip': internal_ip,
            }
            
            current_rules.append(new_rule)
            
            # Update rules
            update_data = {
                'port_forward_list': json.dumps(current_rules)
            }
            
            response = self._make_request("goform/setPortForward", update_data)
            
            if response and response.status_code == 200:
                result = response.json()
                return result.get('result', 0) == 0
            
            return False
            
        except Exception as e:
            self.logger.error(f"Failed to create port forwarding: {e}")
            return False