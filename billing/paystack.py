# billing/paystack.py
import requests
import json
from django.conf import settings
from django.urls import reverse
from django.utils.http import urlencode

class PaystackAPI:
    def __init__(self, secret_key=None):
        self.secret_key = 'sk_test_a38271e5a19686576e1d775df3f2d42b2027a242' #secret_key or getattr(settings, 'PAYSTACK_SECRET_KEY', '')
        self.public_key = 'pk_test_326928d62c0d19eaa90341289573887d07a5c96c' #getattr(settings, 'PAYSTACK_PUBLIC_KEY', '')
        self.base_url = 'https://api.paystack.co'
    
    def _get_headers(self):
        """Return headers for API requests"""
        return {
            'Authorization': f'Bearer {self.secret_key}',
            'Content-Type': 'application/json',
        }
    
    def _make_request(self, method, endpoint, data=None, params=None):
        """
        Generic method to make API requests to Paystack
        
        Args:
            method (str): HTTP method ('get', 'post', 'put', 'delete')
            endpoint (str): API endpoint
            data (dict, optional): Request payload
            params (dict, optional): Query parameters
            
        Returns:
            dict: API response
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        try:
            if method.lower() == 'get':
                response = requests.get(url, headers=self._get_headers(), params=params, timeout=30)
            elif method.lower() == 'post':
                response = requests.post(url, headers=self._get_headers(), json=data, timeout=30)
            elif method.lower() == 'put':
                response = requests.put(url, headers=self._get_headers(), json=data, timeout=30)
            elif method.lower() == 'delete':
                response = requests.delete(url, headers=self._get_headers(), timeout=30)
            else:
                return {
                    'status': False,
                    'message': f'Unsupported HTTP method: {method}'
                }
            
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.RequestException as e:
            error_response = {
                'status': False,
                'message': f'Paystack API error: {str(e)}',
                'data': None
            }
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_details = e.response.json()
                    error_response['message'] = error_details.get('message', str(e))
                except json.JSONDecodeError:
                    error_response['message'] = e.response.text or str(e)
            return error_response
    
    def verify_credentials(self):
        """Test if the API credentials are valid"""
        result = self._make_request('get', 'transaction')
        if 'status' in result:
            return {
                'status': result.get('status', False),
                'message': 'Credentials verified successfully' if result.get('status') else 'Invalid credentials'
            }
        return {
            'status': False,
            'message': 'Connection error'
        }
    
    def initialize_transaction(self, email, amount, reference, plan_name=None, metadata=None, callback_url=None):
        """
        Initialize a Paystack transaction
        
        Args:
            email (str): Customer's email address
            amount (float): Amount to charge in the currency's base unit (e.g., kobo for Naira)
            reference (str): Unique transaction reference
            plan_name (str, optional): Name of the plan being purchased
            metadata (dict, optional): Additional metadata
            callback_url (str, optional): URL to redirect to after payment
            
        Returns:
            dict: Paystack API response
        """
        # Prepare metadata
        transaction_metadata = metadata or {}
        if plan_name:
            transaction_metadata['custom_fields'] = [
                {
                    "display_name": "Plan",
                    "variable_name": "plan",
                    "value": plan_name
                }
            ]
        
        # Prepare payload
        payload = {
            'email': email,
            'amount': int(amount * 100),  # Convert to kobo
            'reference': reference,
            'metadata': transaction_metadata
        }
        
        # Add callback URL if provided
        if callback_url:
            payload["callback_url"] = callback_url
        
        return self._make_request('post', 'transaction/initialize', data=payload)
    
    def verify_transaction(self, reference):
        """
        Verify a Paystack transaction
        
        Args:
            reference (str): Transaction reference to verify
            
        Returns:
            dict: Paystack API response with transaction details
        """
        return self._make_request('get', f'transaction/verify/{reference}')
    
    def create_subaccount(self, business_name, bank_code, account_number, percentage_charge=7.5, settlement_bank=None):
        """
        Create a subaccount for revenue sharing
        
        Args:
            business_name (str): Name of the business/ISP
            bank_code (str): Bank code from Paystack's bank list
            account_number (str): Bank account number
            percentage_charge (float): Percentage charge for platform (default: 7.5%)
            settlement_bank (str, optional): Settlement bank code
            
        Returns:
            dict: Paystack API response with subaccount details
        """
        payload = {
            'business_name': business_name,
            'bank_code': bank_code,
            'account_number': account_number,
            'percentage_charge': percentage_charge,
        }
        
        if settlement_bank:
            payload['settlement_bank'] = settlement_bank
        
        return self._make_request('post', 'subaccount', data=payload)
    
    def update_subaccount(self, subaccount_code, business_name=None, percentage_charge=None):
        """
        Update an existing subaccount
        
        Args:
            subaccount_code (str): Subaccount code from Paystack
            business_name (str, optional): New business name
            percentage_charge (float, optional): New percentage charge
            
        Returns:
            dict: Paystack API response
        """
        payload = {}
        if business_name:
            payload['business_name'] = business_name
        if percentage_charge is not None:
            payload['percentage_charge'] = percentage_charge
        
        return self._make_request('put', f'subaccount/{subaccount_code}', data=payload)
    
    def create_plan(self, name, amount, interval, description=None):
        """
        Create a subscription plan
        
        Args:
            name (str): Plan name
            amount (float): Plan amount in the currency's base unit
            interval (str): Billing interval ('daily', 'weekly', 'monthly', 'quarterly', 'yearly')
            description (str, optional): Plan description
            
        Returns:
            dict: Paystack API response
        """
        payload = {
            'name': name,
            'amount': int(amount * 100),  # Convert to kobo
            'interval': interval
        }
        
        if description:
            payload['description'] = description
        
        return self._make_request('post', 'plan', data=payload)
    
    def list_plans(self, per_page=50, page=1):
        """
        List all plans
        
        Args:
            per_page (int): Number of records to return per page
            page (int): Page number to return
            
        Returns:
            dict: Paystack API response with plans list
        """
        params = {
            'perPage': per_page,
            'page': page
        }
        
        return self._make_request('get', 'plan', params=params)
    
    def create_subscription(self, customer_email, plan_code, authorization_code=None, start_date=None):
        """
        Create a subscription for a customer
        
        Args:
            customer_email (str): Customer's email address
            plan_code (str): Plan code from Paystack
            authorization_code (str, optional): Authorization code for recurring charges
            start_date (datetime, optional): When the subscription should start
            
        Returns:
            dict: Paystack API response
        """
        payload = {
            'customer': customer_email,
            'plan': plan_code
        }
        
        if authorization_code:
            payload['authorization'] = authorization_code
        
        if start_date:
            payload['start_date'] = start_date.isoformat()
        
        return self._make_request('post', 'subscription', data=payload)
    
    def disable_subscription(self, subscription_code, token):
        """
        Disable a subscription
        
        Args:
            subscription_code (str): Subscription code from Paystack
            token (str): Email token from the subscription
            
        Returns:
            dict: Paystack API response
        """
        payload = {
            'code': subscription_code,
            'token': token
        }
        
        return self._make_request('post', 'subscription/disable', data=payload)
    
    def list_transactions(self, per_page=50, page=1, customer_id=None, status=None):
        """
        List transactions
        
        Args:
            per_page (int): Number of records to return per page
            page (int): Page number to return
            customer_id (int, optional): Filter by customer ID
            status (str, optional): Filter by status ('success', 'failed', 'abandoned')
            
        Returns:
            dict: Paystack API response with transactions list
        """
        params = {
            'perPage': per_page,
            'page': page
        }
        
        if customer_id:
            params['customer'] = customer_id
        
        if status:
            params['status'] = status
        
        return self._make_request('get', 'transaction', params=params)
    
    def transaction_totals(self):
        """
        Get transaction totals
        
        Returns:
            dict: Paystack API response with transaction totals
        """
        return self._make_request('get', 'transaction/totals')
    
    def generate_payment_link(self, request, email, amount, reference, plan_name=None):
        """
        Generate a payment link that can be used in a redirect
        
        Args:
            request: Django request object
            email (str): Customer email
            amount (float): Amount to charge
            reference (str): Transaction reference
            plan_name (str, optional): Plan name
            
        Returns:
            str: Payment URL
        """
        # Build callback URL
        callback_url = request.build_absolute_uri(reverse('payment_callback'))
        
        # Initialize transaction
        response = self.initialize_transaction(
            email=email,
            amount=amount,
            reference=reference,
            plan_name=plan_name,
            callback_url=callback_url
        )
        
        if response.get('status') and response.get('data', {}).get('authorization_url'):
            return response['data']['authorization_url']
        else:
            # Fallback to manual URL construction if API fails
            base_url = 'https://paystack.com/pay'
            params = {
                'email': email,
                'amount': int(amount * 100),
                'reference': reference,
                'callback_url': callback_url
            }
            
            if plan_name:
                params['metadata'] = json.dumps({
                    'custom_fields': [{
                        'display_name': 'Plan',
                        'variable_name': 'plan',
                        'value': plan_name
                    }]
                })
            
            return f'{base_url}?{urlencode(params)}'
    
    def is_transaction_successful(self, reference):
        """
        Check if a transaction was successful
        
        Args:
            reference (str): Transaction reference
            
        Returns:
            bool: True if transaction was successful, False otherwise
        """
        verification = self.verify_transaction(reference)
        return (
            verification.get('status') and 
            verification.get('data', {}).get('status') == 'success'
        )
    
    def get_transaction_details(self, reference):
        """
        Get detailed transaction information
        
        Args:
            reference (str): Transaction reference
            
        Returns:
            dict: Transaction details or None if not found
        """
        verification = self.verify_transaction(reference)
        if verification.get('status'):
            return verification.get('data')
        return None

# Utility function to get Paystack instance
def get_paystack_instance():
    """Get an instance of the PaystackAPI class"""
    return PaystackAPI()