# billing/api_integrations.py
from django.http import HttpResponseForbidden
import requests
import json
from decimal import Decimal
from django.utils import timezone as tz
from django.conf import settings
import logging
from typing import Dict, Optional, Any

logger = logging.getLogger(__name__)

class BaseAPIProvider:
    """Base class for all API providers"""
    
    def __init__(self, api_endpoint: str, api_key: str = None, api_secret: str = None):
        self.api_endpoint = api_endpoint
        self.api_key = api_key
        self.api_secret = api_secret
        self.timeout = 30
        
    def get_headers(self) -> Dict:
        """Get headers for API request"""
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'm_netiISP/1.0'
        }
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'
        return headers
    
    def make_request(self, method: str, endpoint: str, data: Dict = None) -> Optional[Dict]:
        """Make API request with error handling"""
        url = f"{self.api_endpoint.rstrip('/')}/{endpoint.lstrip('/')}"
        
        try:
            response = requests.request(
                method=method,
                url=url,
                json=data,
                headers=self.get_headers(),
                timeout=self.timeout,
                verify=True  # SSL verification
            )
            
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.Timeout:
            logger.error(f"API timeout for {url}")
            raise Exception("API request timeout")
        except requests.exceptions.ConnectionError:
            logger.error(f"Connection error for {url}")
            raise Exception("Cannot connect to API")
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error {e.response.status_code} for {url}")
            raise Exception(f"API returned error: {e.response.status_code}")
        except Exception as e:
            logger.error(f"API request error: {e}")
            raise Exception(f"API error: {str(e)}")
    
    def test_connection(self) -> bool:
        """Test API connection"""
        try:
            response = self.make_request('GET', 'health' if 'health' in self.api_endpoint else '')
            return True
        except:
            return False

class TelecomProviderAPI(BaseAPIProvider):
    """Telecom provider API integration (e.g., Safaricom, Airtel)"""
    
    def get_data_balance(self) -> Decimal:
        """Get available data balance from telecom provider"""
        try:
            # Example response structure for telecom APIs
            data = self.make_request('POST', 'api/v1/data/balance', {
                'timestamp': tz.now().isoformat(),
                'request_id': f"bal_{tz.now().strftime('%Y%m%d%H%M%S')}"
            })
            
            # Parse response (adjust based on actual API)
            if data.get('status') == 'success':
                balance_gb = Decimal(str(data['data']['available_data_gb']))
                return balance_gb
            else:
                raise Exception(data.get('message', 'Unknown API error'))
                
        except Exception as e:
            logger.error(f"Failed to get telecom data balance: {e}")
            raise
    
    def purchase_data(self, amount_gb: Decimal, reference: str) -> Dict:
        """Purchase data from telecom provider"""
        try:
            data = self.make_request('POST', 'api/v1/data/purchase', {
                'amount_gb': float(amount_gb),
                'reference': reference,
                'timestamp': tz.now().isoformat()
            })
            
            if data.get('status') == 'success':
                return {
                    'success': True,
                    'transaction_id': data['data']['transaction_id'],
                    'amount_gb': Decimal(str(data['data']['amount_gb'])),
                    'cost': Decimal(str(data['data']['cost'])),
                    'expiry_date': data['data'].get('expiry_date')
                }
            else:
                return {
                    'success': False,
                    'error': data.get('message', 'Purchase failed')
                }
                
        except Exception as e:
            logger.error(f"Failed to purchase data: {e}")
            return {'success': False, 'error': str(e)}
    
    def get_purchase_history(self, days: int = 30) -> list:
        """Get purchase history"""
        try:
            data = self.make_request('GET', f'api/v1/data/history?days={days}')
            
            if data.get('status') == 'success':
                return data['data']['transactions']
            return []
        except Exception as e:
            logger.error(f"Failed to get history: {e}")
            return []

class ISPManagementSystemAPI(BaseAPIProvider):
    """Integration with ISP's own management system"""
    
    def get_customer_data_usage(self, date_from: str, date_to: str) -> Dict:
        """Get aggregated data usage from ISP's system"""
        try:
            data = self.make_request('POST', 'api/data/usage', {
                'date_from': date_from,
                'date_to': date_to,
                'aggregate_by': 'total'
            })
            
            if data.get('success'):
                return {
                    'total_usage_gb': Decimal(str(data['data']['total_usage_gb'])),
                    'customer_count': data['data']['customer_count'],
                    'average_usage_gb': Decimal(str(data['data']['average_usage_gb']))
                }
            return {}
            
        except Exception as e:
            logger.error(f"Failed to get usage data: {e}")
            return {}
    
    def sync_customer_list(self) -> list:
        """Sync customer list from ISP system"""
        try:
            data = self.make_request('GET', 'api/customers/active')
            
            if data.get('success'):
                return data['data']['customers']
            return []
            
        except Exception as e:
            logger.error(f"Failed to sync customers: {e}")
            return []

class ThirdPartyDataProviderAPI(BaseAPIProvider):
    """Third-party data marketplace APIs"""
    
    def get_available_packages(self) -> list:
        """Get available data packages"""
        try:
            data = self.make_request('GET', 'api/packages')
            
            if data.get('success'):
                packages = []
                for pkg in data['data']['packages']:
                    packages.append({
                        'id': pkg['id'],
                        'name': pkg['name'],
                        'data_gb': Decimal(str(pkg['data_gb'])),
                        'price': Decimal(str(pkg['price'])),
                        'validity_days': pkg['validity_days'],
                        'description': pkg.get('description', '')
                    })
                return packages
            return []
            
        except Exception as e:
            logger.error(f"Failed to get packages: {e}")
            return []
    
    def purchase_package(self, package_id: str, quantity: int = 1) -> Dict:
        """Purchase data package"""
        try:
            data = self.make_request('POST', 'api/purchase', {
                'package_id': package_id,
                'quantity': quantity,
                'reference': f"TP_{tz.now().strftime('%Y%m%d%H%M%S')}"
            })
            
            if data.get('success'):
                return {
                    'success': True,
                    'transaction_id': data['data']['transaction_id'],
                    'voucher_codes': data['data'].get('voucher_codes', []),
                    'total_data_gb': Decimal(str(data['data']['total_data_gb']))
                }
            return {'success': False, 'error': data.get('message', 'Purchase failed')}
            
        except Exception as e:
            logger.error(f"Failed to purchase package: {e}")
            return {'success': False, 'error': str(e)}

class APIIntegrationManager:
    """Manager for all API integrations"""
    
    PROVIDERS = {
        'safaricom': TelecomProviderAPI,
        'airtel': TelecomProviderAPI,
        'mtn': TelecomProviderAPI,
        'isp_system': ISPManagementSystemAPI,
        'data_vendor': ThirdPartyDataProviderAPI,
    }
    
    @classmethod
    def get_provider(cls, provider_type: str, **kwargs):
        """Get API provider instance"""
        provider_class = cls.PROVIDERS.get(provider_type)
        if not provider_class:
            raise ValueError(f"Unknown provider type: {provider_type}")
        
        return provider_class(**kwargs)
    
    @classmethod
    def test_all_connections(cls, connections: list) -> Dict:
        """Test multiple API connections"""
        results = {}
        for conn in connections:
            try:
                provider = cls.get_provider(
                    conn['provider_type'],
                    api_endpoint=conn['api_endpoint'],
                    api_key=conn.get('api_key'),
                    api_secret=conn.get('api_secret')
                )
                results[conn['name']] = provider.test_connection()
            except Exception as e:
                results[conn['name']] = False
                logger.error(f"Connection test failed for {conn['name']}: {e}")
        
        return results

