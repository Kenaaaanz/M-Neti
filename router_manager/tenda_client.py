import requests
from bs4 import BeautifulSoup
import hashlib
import re

class TendaClient:
    def __init__(self, router_config):
        self.router = router_config
        self.base_url = f"http://{router_config.ip_address}:{router_config.web_port}"
        self.session = requests.Session()
        self.logged_in = False
    
    def login(self):
        """Login to Tenda router"""
        try:
            # Get login page
            login_page = self.session.get(f"{self.base_url}/login.html")
            soup = BeautifulSoup(login_page.text, 'html.parser')
            
            # Tenda often uses password hashing
            password_hash = self._hash_password(self.router.password)
            
            # Login data structure varies by model
            login_data = {
                'username': self.router.username,
                'password': password_hash,
            }
            
            # Send login request
            login_response = self.session.post(
                f"{self.base_url}/login/Auth",
                data=login_data,
                headers={'Content-Type': 'application/x-www-form-urlencoded'}
            )
            
            self.logged_in = login_response.status_code == 200
            return self.logged_in
            
        except Exception as e:
            print(f"Tenda login error: {e}")
            return False
    
    def _hash_password(self, password):
        """Hash password for Tenda routers"""
        # Tenda uses various hashing methods
        try:
            # Method 1: Simple MD5 (common in Tenda)
            return hashlib.md5(password.encode()).hexdigest().upper()
        except:
            return password
    
    def add_port_forwarding(self, external_port, internal_ip, internal_port, protocol='tcp', description=""):
        """Add port forwarding rule on Tenda router"""
        if not self.logged_in and not self.login():
            return False
        
        try:
            # Tenda port forwarding API
            if protocol.lower() == 'both':
                # Add both TCP and UDP
                success_tcp = self._add_single_port_forwarding(external_port, internal_ip, internal_port, 'tcp', description)
                success_udp = self._add_single_port_forwarding(external_port, internal_ip, internal_port, 'udp', description)
                return success_tcp and success_udp
            else:
                return self._add_single_port_forwarding(external_port, internal_ip, internal_port, protocol, description)
                
        except Exception as e:
            print(f"Tenda port forwarding error: {e}")
            return False
    
    def _add_single_port_forwarding(self, external_port, internal_ip, internal_port, protocol, description):
        """Add single protocol port forwarding"""
        # Get current rules first
        rules_response = self.session.get(f"{self.base_url}/goform/virtualSer")
        current_rules = self._parse_virtual_ser_response(rules_response.text)
        
        # Find next available rule index
        next_index = len(current_rules) + 1
        
        # Prepare rule data
        rule_data = {
            'virtualSer': 'add',
            'vPort': external_port,
            'vProto': '1' if protocol.lower() == 'tcp' else '2',  # 1=TCP, 2=UDP
            'vIp': internal_ip,
            'vPortIn': internal_port,
            'vEnable': '1',
            'vDesc': description,
            'vIndex': next_index
        }
        
        # Add the rule
        add_response = self.session.post(
            f"{self.base_url}/goform/setVirtualSer",
            data=rule_data,
            headers={'Content-Type': 'application/x-www-form-urlencoded'}
        )
        
        return add_response.status_code == 200
    
    def _parse_virtual_ser_response(self, html_content):
        """Parse virtual server rules from HTML response"""
        rules = []
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Find rule tables (varies by Tenda model)
        rule_tables = soup.find_all('table', class_=re.compile('rule|list'))
        
        for table in rule_tables:
            rows = table.find_all('tr')[1:]  # Skip header row
            for row in rows:
                cols = row.find_all('td')
                if len(cols) >= 5:
                    rule = {
                        'index': cols[0].text.strip(),
                        'external_port': cols[1].text.strip(),
                        'protocol': cols[2].text.strip(),
                        'internal_ip': cols[3].text.strip(),
                        'internal_port': cols[4].text.strip(),
                        'status': cols[5].text.strip() if len(cols) > 5 else ''
                    }
                    rules.append(rule)
        
        return rules
    
    def remove_port_forwarding(self, external_port, protocol='tcp'):
        """Remove port forwarding rule"""
        if not self.logged_in and not self.login():
            return False
        
        try:
            # Get current rules
            rules_response = self.session.get(f"{self.base_url}/goform/virtualSer")
            current_rules = self._parse_virtual_ser_response(rules_response.text)
            
            # Find rule to remove
            for rule in current_rules:
                if (rule['external_port'] == str(external_port) and 
                    rule['protocol'].lower() == protocol.lower()):
                    
                    # Remove the rule
                    remove_data = {
                        'virtualSer': 'del',
                        'vIndex': rule['index']
                    }
                    
                    remove_response = self.session.post(
                        f"{self.base_url}/goform/setVirtualSer",
                        data=remove_data,
                        headers={'Content-Type': 'application/x-www-form-urlencoded'}
                    )
                    
                    return remove_response.status_code == 200
            
            return False
            
        except Exception as e:
            print(f"Tenda remove port forwarding error: {e}")
            return False