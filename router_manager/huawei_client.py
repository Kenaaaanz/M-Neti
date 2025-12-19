import requests
from bs4 import BeautifulSoup
import re
import json
from urllib.parse import urljoin

class HuaweiClient:
    def __init__(self, router_config):
        self.router = router_config
        self.base_url = f"http://{router_config.ip_address}:{router_config.web_port}"
        self.session = requests.Session()
        self.logged_in = False
    
    def login(self):
        """Login to Huawei router"""
        try:
            # Get login page to get tokens
            login_page = self.session.get(f"{self.base_url}/")
            soup = BeautifulSoup(login_page.text, 'html.parser')
            
            # Find CSRF token (varies by model)
            csrf_token = self._extract_csrf_token(soup)
            
            # Login payload
            login_data = {
                'Username': self.router.username,
                'Password': self.router.password,
            }
            
            if csrf_token:
                login_data['csrf_token'] = csrf_token
            
            # Send login request
            login_response = self.session.post(
                f"{self.base_url}/api/user/login",
                json=login_data,
                headers={'Content-Type': 'application/json'}
            )
            
            if login_response.status_code == 200:
                self.logged_in = True
                return True
            else:
                # Try alternative login method
                return self._alternative_login()
                
        except Exception as e:
            print(f"Huawei login error: {e}")
            return False
    
    def _extract_csrf_token(self, soup):
        """Extract CSRF token from login page"""
        # Try multiple methods to find CSRF token
        token_selectors = [
            'input[name="csrf_token"]',
            'input[name="token"]',
            'meta[name="csrf-token"]',
            '#token'
        ]
        
        for selector in token_selectors:
            element = soup.select_one(selector)
            if element:
                return element.get('value') or element.get('content')
        return None
    
    def _alternative_login(self):
        """Alternative login method for older Huawei models"""
        try:
            login_data = f"<?xml version='1.0' encoding='UTF-8'?><request><Username>{self.router.username}</Username><Password>{self.router.password}</Password></request>"
            
            response = self.session.post(
                f"{self.base_url}/api/user/login",
                data=login_data,
                headers={'Content-Type': 'application/xml'}
            )
            
            self.logged_in = response.status_code == 200
            return self.logged_in
            
        except Exception as e:
            print(f"Alternative login error: {e}")
            return False
    
    def add_port_forwarding(self, external_port, internal_ip, internal_port, protocol='TCP', description=""):
        """Add port forwarding rule on Huawei router"""
        if not self.logged_in and not self.login():
            return False
        
        try:
            # Huawei uses different APIs based on model
            if self.router.router_model in ['hg8245h', 'hg8245q']:
                return self._add_port_forwarding_ont(external_port, internal_ip, internal_port, protocol, description)
            else:
                return self._add_port_forwarding_standard(external_port, internal_ip, internal_port, protocol, description)
                
        except Exception as e:
            print(f"Huawei port forwarding error: {e}")
            return False
    
    def _add_port_forwarding_standard(self, external_port, internal_ip, internal_port, protocol, description):
        """Standard port forwarding for most Huawei routers"""
        xml_payload = f"""<?xml version="1.0" encoding="UTF-8"?>
        <request>
            <PortMappingIndex></PortMappingIndex>
            <InternalClient>{internal_ip}</InternalClient>
            <PortMappingProtocol>{protocol}</PortMappingProtocol>
            <InternalPort>{internal_port}</InternalPort>
            <ExternalPort>{external_port}</ExternalPort>
            <PortMappingDescription>{description}</PortMappingDescription>
        </request>"""
        
        response = self.session.post(
            f"{self.base_url}/api/nat/portmapping",
            data=xml_payload,
            headers={'Content-Type': 'application/xml'}
        )
        
        return response.status_code == 200
    
    def _add_port_forwarding_ont(self, external_port, internal_ip, internal_port, protocol, description):
        """Port forwarding for ONT models"""
        xml_payload = f"""<?xml version="1.0" encoding="UTF-8"?>
        <request>
            <MappingIndex></MappingIndex>
            <InternalClient>{internal_ip}</InternalClient>
            <Protocol>{protocol}</Protocol>
            <InternalPort>{internal_port}</InternalPort>
            <ExternalPort>{external_port}</ExternalPort>
            <LeaseDuration>0</LeaseDuration>
            <Description>{description}</Description>
        </request>"""
        
        response = self.session.post(
            f"{self.base_url}/api/router/portforward",
            data=xml_payload,
            headers={'Content-Type': 'application/xml'}
        )
        
        return response.status_code == 200

    def remove_port_forwarding(self, external_port, protocol='TCP'):
        """Remove port forwarding rule"""
        if not self.logged_in and not self.login():
            return False
        
        try:
            # First get all port forwarding rules
            response = self.session.get(f"{self.base_url}/api/nat/portmapping")
            soup = BeautifulSoup(response.text, 'xml')
            
            # Find rule to remove
            rules = soup.find_all('PortMappingInstance')
            for rule in rules:
                rule_ext_port = rule.find('ExternalPort')
                rule_protocol = rule.find('PortMappingProtocol')
                
                if (rule_ext_port and rule_protocol and 
                    rule_ext_port.text == str(external_port) and 
                    rule_protocol.text.upper() == protocol.upper()):
                    
                    mapping_index = rule.find('PortMappingIndex').text
                    
                    # Remove the rule
                    xml_payload = f"""<?xml version="1.0" encoding="UTF-8"?>
                    <request>
                        <PortMappingIndex>{mapping_index}</PortMappingIndex>
                    </request>"""
                    
                    delete_response = self.session.post(
                        f"{self.base_url}/api/nat/portmapping",
                        data=xml_payload,
                        headers={'Content-Type': 'application/xml'}
                    )
                    
                    return delete_response.status_code == 200
            
            return False
            
        except Exception as e:
            print(f"Huawei remove port forwarding error: {e}")
            return False