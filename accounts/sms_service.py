# accounts/sms_service.py
import requests
import json
from datetime import datetime
from django.conf import settings
from django.utils import timezone
from decimal import Decimal
import africastalking
import logging

from accounts.models import SMSProviderConfig

logger = logging.getLogger(__name__)

class SMSService:
    def __init__(self, provider_config):
        self.provider_config = provider_config
        self.tenant = provider_config.tenant
        
        # Initialize provider based on configuration
        if provider_config.provider_name == 'africastalking':
            self.initialize_africastalking()
        elif provider_config.provider_name == 'twilio':
            self.initialize_twilio()
        elif provider_config.provider_name == 'smsalert':
            self.initialize_smsalert()
        else:
            self.client = None
    
    def initialize_africastalking(self):
        """Initialize Africa's Talking SMS service"""
        try:
            africastalking.initialize(
                username=self.provider_config.api_key,  # Africa's Talking uses username as API key
                api_key=self.provider_config.api_secret
            )
            self.client = africastalking.SMS
        except Exception as e:
            logger.error(f"Failed to initialize Africa's Talking: {e}")
            raise
    
    def initialize_twilio(self):
        """Initialize Twilio SMS service"""
        try:
            from twilio.rest import Client
            self.client = Client(
                self.provider_config.api_key,  # Account SID
                self.provider_config.api_secret  # Auth Token
            )
        except ImportError:
            logger.error("Twilio package not installed. Install with: pip install twilio")
            raise
        except Exception as e:
            logger.error(f"Failed to initialize Twilio: {e}")
            raise
    
    def initialize_smsalert(self):
        """Initialize SMS Alert service"""
        # SMS Alert uses simple HTTP API
        self.client = None
    
    def send_single_sms(self, phone_number, message, sender_id=None):
        """Send single SMS to a phone number"""
        from .models import SMSLog
        
        # Format phone number
        phone_number = self.format_phone_number(phone_number)
        if not phone_number:
            return False, "Invalid phone number"
        
        # Check daily limit
        if not self.check_daily_limit():
            return False, "Daily SMS limit reached"
        
        # Use default sender if not specified
        sender = sender_id or self.provider_config.default_sender or self.provider_config.sender_id
        
        try:
            # Reset daily count if new day
            self.provider_config.reset_daily_count()
            
            # Send SMS based on provider
            if self.provider_config.provider_name == 'africastalking':
                response = self.send_via_africastalking(phone_number, message, sender)
            elif self.provider_config.provider_name == 'twilio':
                response = self.send_via_twilio(phone_number, message, sender)
            elif self.provider_config.provider_name == 'smsalert':
                response = self.send_via_smsalert(phone_number, message, sender)
            else:
                return False, "Unsupported SMS provider"
            
            # Update daily count
            self.provider_config.sms_sent_today += 1
            self.provider_config.save()
            
            return True, response
            
        except Exception as e:
            logger.error(f"Failed to send SMS to {phone_number}: {e}")
            return False, str(e)
    
    def send_via_africastalking(self, phone_number, message, sender):
        """Send SMS via Africa's Talking"""
        try:
            response = self.client.send(
                message=message,
                recipients=[phone_number],
                sender_id=sender
            )
            
            if response['SMSMessageData']['Recipients'][0]['statusCode'] == 101:
                return {
                    'success': True,
                    'message_id': response['SMSMessageData']['Recipients'][0]['messageId'],
                    'cost': Decimal(response['SMSMessageData']['Recipients'][0]['cost'].replace('KES ', ''))
                }
            else:
                raise Exception(f"API Error: {response}")
                
        except Exception as e:
            logger.error(f"Africa's Talking API error: {e}")
            raise
    
    def send_via_twilio(self, phone_number, message, sender):
        """Send SMS via Twilio"""
        try:
            message = self.client.messages.create(
                body=message,
                from_=sender,
                to=phone_number
            )
            
            return {
                'success': True,
                'message_id': message.sid,
                'cost': Decimal(str(message.price or '0'))
            }
            
        except Exception as e:
            logger.error(f"Twilio API error: {e}")
            raise
    
    def send_via_smsalert(self, phone_number, message, sender):
        """Send SMS via SMS Alert"""
        try:
            # SMS Alert API endpoint
            url = "https://www.smsalert.co.in/api/push.json"
            
            params = {
                'apikey': self.provider_config.api_key,
                'sender': sender,
                'mobileno': phone_number,
                'text': message
            }
            
            response = requests.get(url, params=params)
            data = response.json()
            
            if data.get('status') == 'success':
                return {
                    'success': True,
                    'message_id': data.get('batchid', ''),
                    'cost': self.provider_config.cost_per_sms
                }
            else:
                raise Exception(f"SMS Alert Error: {data.get('description', 'Unknown error')}")
                
        except Exception as e:
            logger.error(f"SMS Alert API error: {e}")
            raise
    
    def send_bulk_sms(self, phone_numbers, message, sender_id=None):
        """Send SMS to multiple phone numbers"""
        results = []
        successful = 0
        failed = 0
        
        for phone_number in phone_numbers:
            success, result = self.send_single_sms(phone_number, message, sender_id)
            results.append({
                'phone': phone_number,
                'success': success,
                'result': result
            })
            
            if success:
                successful += 1
            else:
                failed += 1
        
        return {
            'successful': successful,
            'failed': failed,
            'total': len(phone_numbers),
            'results': results
        }
    
    def format_phone_number(self, phone_number):
        """Format phone number to international format"""
        # Remove any non-digit characters
        phone = ''.join(filter(str.isdigit, str(phone_number)))
        
        # Handle Kenyan numbers (add country code if missing)
        if phone.startswith('0'):
            phone = '254' + phone[1:]  # Convert 07... to 2547...
        elif not phone.startswith('254'):
            phone = '254' + phone
        
        # Ensure proper length
        if len(phone) == 12:  # 254xxxxxxxxx
            return '+' + phone
        elif len(phone) == 9:  # xxxxxxxxx (without country code)
            return '+254' + phone
        
        return None
    
    def check_daily_limit(self):
        """Check if daily SMS limit has been reached"""
        self.provider_config.reset_daily_count()
        return self.provider_config.sms_sent_today < self.provider_config.max_sms_per_day
    
    def get_balance(self):
        """Get SMS balance/credit"""
        if self.provider_config.provider_name == 'africastalking':
            return self.get_africastalking_balance()
        elif self.provider_config.provider_name == 'twilio':
            return self.get_twilio_balance()
        
        return None
    
    def get_africastalking_balance(self):
        """Get Africa's Talking balance"""
        try:
            from africastalking.Application import Application
            app = Application(username=self.provider_config.api_key, api_key=self.provider_config.api_secret)
            response = app.fetch_application_data()
            return response['UserData']['balance']
        except Exception as e:
            logger.error(f"Failed to get Africa's Talking balance: {e}")
            return None
    
    def get_twilio_balance(self):
        """Get Twilio balance"""
        try:
            balance = self.client.balance.fetch()
            return balance.balance
        except Exception as e:
            logger.error(f"Failed to get Twilio balance: {e}")
            return None


def send_bulk_sms_to_customers(campaign):
    """Send bulk SMS campaign"""
    from .models import SMSLog
    
    try:
        # Update campaign status
        campaign.status = 'sending'
        campaign.sent_at = timezone.now()
        campaign.save()
        
        # Get SMS provider
        provider_config = SMSProviderConfig.objects.filter(
            tenant=campaign.tenant,
            is_active=True
        ).first()
        
        if not provider_config:
            campaign.status = 'failed'
            campaign.save()
            return False, "No active SMS provider configured"
        
        # Initialize SMS service
        sms_service = SMSService(provider_config)
        
        # Get message content
        if campaign.template:
            message = campaign.template.content
        else:
            message = campaign.custom_message
        
        successful = 0
        failed = 0
        
        # Send to each recipient
        for customer in campaign.recipients.all():
            if customer.phone:
                try:
                    # Replace variables in message
                    personalized_message = replace_message_variables(message, customer)
                    
                    # Send SMS
                    success, result = sms_service.send_single_sms(
                        customer.phone, 
                        personalized_message
                    )
                    
                    # Create SMS log
                    SMSLog.objects.create(
                        tenant=campaign.tenant,
                        bulk_sms=campaign,
                        customer=customer,
                        message=personalized_message,
                        status='sent' if success else 'failed',
                        status_message=result if not success else '',
                        cost=result.get('cost', 0) if success else 0,
                        provider_reference=result.get('message_id', '') if success else '',
                        sent_at=timezone.now() if success else None
                    )
                    
                    if success:
                        successful += 1
                    else:
                        failed += 1
                        
                except Exception as e:
                    logger.error(f"Failed to send SMS to {customer.username}: {e}")
                    failed += 1
            else:
                failed += 1
        
        # Update campaign stats
        campaign.sent_count = successful
        campaign.failed_count = failed
        campaign.status = 'completed' if successful > 0 or failed == 0 else 'failed'
        campaign.save()
        
        return True, f"Sent {successful} SMS, {failed} failed"
        
    except Exception as e:
        logger.error(f"Failed to send bulk SMS campaign: {e}")
        campaign.status = 'failed'
        campaign.save()
        return False, str(e)


def replace_message_variables(message, customer):
    """Replace variables in message with customer data"""
    replacements = {
        '{name}': customer.get_full_name() or customer.username,
        '{username}': customer.username,
        '{account}': customer.company_account_number or '',
        '{balance}': str(customer.account_balance),
        '{plan}': customer.subscription_plan or 'No Plan',
        '{due_date}': customer.next_payment_date.strftime('%d/%m/%Y') if customer.next_payment_date else 'N/A',
        '{phone}': customer.phone or '',
        '{email}': customer.email,
    }
    
    for key, value in replacements.items():
        message = message.replace(key, str(value))
    
    return message


def get_sms_statistics(tenant):
    """Get SMS statistics for tenant"""
    from .models import SMSLog, BulkSMS
    
    today = timezone.now().date()
    
    # Today's stats
    today_sms = SMSLog.objects.filter(
        tenant=tenant,
        sent_at__date=today
    )
    
    # Total stats
    total_sms = SMSLog.objects.filter(tenant=tenant)
    total_campaigns = BulkSMS.objects.filter(tenant=tenant)
    
    # Cost calculation
    total_cost = sum([log.cost for log in total_sms if log.cost])
    today_cost = sum([log.cost for log in today_sms if log.cost])
    
    return {
        'today_count': today_sms.count(),
        'today_successful': today_sms.filter(status='sent').count(),
        'today_failed': today_sms.filter(status='failed').count(),
        'today_cost': float(today_cost),
        
        'total_count': total_sms.count(),
        'total_successful': total_sms.filter(status='sent').count(),
        'total_failed': total_sms.filter(status='failed').count(),
        'total_cost': float(total_cost),
        
        'total_campaigns': total_campaigns.count(),
        'active_campaigns': total_campaigns.filter(status__in=['draft', 'scheduled', 'sending']).count(),
    }