# billing/models.py
from django.db import models
from django.conf import settings
from django.utils import timezone as tz
from datetime import timedelta
from accounts.models import Tenant, CustomUser
import uuid
from decimal import Decimal
from django.db.models import Sum
import logging

#from billing.services import SubscriptionService

logger = logging.getLogger(__name__)

# ==================== PAYSTACK CONFIGURATION MODEL ====================

class PaystackConfiguration(models.Model):
    account_name = models.CharField(max_length=255, help_text="Name of the Paystack account")
    bank_code = models.CharField(max_length=10, blank=True, null=True, help_text="Bank code from Paystack")
    account_number = models.CharField(max_length=20, blank=True, null=True, help_text="Bank account number")
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='paystack_configs')
    public_key = models.CharField(max_length=255, default='pk_test_326928d62c0d19eaa90341289573887d07a5c96c')
    secret_key = models.CharField(max_length=255, default='sk_test_a38271e5a19686576e1d775df3f2d42b2027a242')
    subaccount_code = models.CharField(max_length=255, blank=True, null=True)
    transaction_charge = models.DecimalField(max_digits=5, decimal_places=2, default=1.5)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=tz.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'paystack_configurations'
        unique_together = ['tenant', 'is_active']
        verbose_name = "Paystack Configuration"
        verbose_name_plural = "Paystack Configurations"

    def __str__(self):
        return f"Paystack Config - {self.account_name} - {self.tenant.name}"

# ==================== COMMISSION MODELS ====================
class PlatformCommission(models.Model):
    """Platform commission rates for different services"""
    SERVICE_TYPES = [
        ('bulk_data', 'Bulk Data Sales'),
        ('subscription', 'Subscription Sales'),
        ('topup', 'Data Top-ups'),
        ('payment_processing', 'Payment Processing'),
        ('all', 'All Services'),
    ]
    
    service_type = models.CharField(max_length=50, choices=SERVICE_TYPES, default='bulk_data')
    rate = models.DecimalField(max_digits=5, decimal_places=2, default=7.5, 
                              help_text="Commission percentage (e.g., 7.5 for 7.5%)")
    is_active = models.BooleanField(default=True)
    applies_to_all = models.BooleanField(default=True, 
                                        help_text="Applies to all ISPs if True")
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, null=True, blank=True,
                              help_text="Specific ISP if applies_to_all is False")
    
    # Commission calculation method
    calculation_method = models.CharField(max_length=20, choices=[
        ('percentage', 'Percentage of Total'),
        ('fixed', 'Fixed Amount'),
        ('tiered', 'Tiered Percentage'),
    ], default='percentage')
    
    # For fixed amount commissions
    fixed_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # For tiered commissions
    min_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0, 
                                    help_text="Minimum amount for this tier")
    max_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True,
                                    help_text="Maximum amount for this tier")
    
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(default=tz.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'platform_commissions'
        unique_together = ['service_type', 'tenant']
        verbose_name = "Platform Commission"
        verbose_name_plural = "Platform Commissions"
    
    def __str__(self):
        if self.applies_to_all:
            return f"{self.get_service_type_display()} - {self.rate}% (All ISPs)"
        return f"{self.get_service_type_display()} - {self.rate}% ({self.tenant.name})"
    
    def calculate_commission(self, amount):
        """Calculate commission based on amount and settings"""
        if self.calculation_method == 'percentage':
            return (amount * self.rate / 100)
        elif self.calculation_method == 'fixed':
            return self.fixed_amount
        elif self.calculation_method == 'tiered':
            # For tiered, you might have multiple commission records
            return (amount * self.rate / 100)
        return Decimal('0')

class CommissionTransaction(models.Model):
    """Track commission transactions"""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('calculated', 'Calculated'),
        ('paid', 'Paid to Platform'),
        ('due', 'Due to ISP'),
        ('withheld', 'Withheld'),
        ('refunded', 'Refunded'),
    ]

    COMMISSION_TYPES = [
        ('subscription', 'Subscription'),
        ('bulk_data', 'Bulk Data'),
        ('bandwidth', 'Bandwidth'),
        ('topup', 'Top-up'),
        ('one_time', 'One-time Payment'),
        ('bulk_purchase', 'Bulk Purchase'),
    ]
    
    commission_type = models.CharField(
        max_length=20,
        choices=COMMISSION_TYPES,
        default='subscription'
    )
    
    # FIX: Make payment optional and add related name
    payment = models.ForeignKey('Payment', on_delete=models.SET_NULL, null=True, blank=True, 
                                related_name='commission_transactions')
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='commission_transactions')
    commission = models.ForeignKey(PlatformCommission, on_delete=models.PROTECT, null=True, blank=True)
    
    # Amounts
    transaction_amount = models.DecimalField(max_digits=10, decimal_places=2)
    commission_amount = models.DecimalField(max_digits=10, decimal_places=2)
    net_amount = models.DecimalField(max_digits=10, decimal_places=2, 
                                    help_text="Amount to be settled to ISP", null=True, blank=True)
    
    # For bulk data purchases
    bulk_purchase = models.ForeignKey('ISPBulkPurchase', on_delete=models.SET_NULL, 
                                     null=True, blank=True, related_name='commissions')
    # Add bandwidth purchase field
    bandwidth_purchase = models.ForeignKey('ISPBandwidthPurchase', on_delete=models.SET_NULL,
                                         null=True, blank=True, related_name='commissions')
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    is_platform_share = models.BooleanField(default=True, 
                                           help_text="True if platform takes commission, False if ISP gets commission")
    
    # Settlement info
    settlement_date = models.DateTimeField(null=True, blank=True)
    settlement_reference = models.CharField(max_length=100, blank=True)
    
    # Metadata
    description = models.TextField(blank=True)
    calculated_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=tz.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    # FIX: Make vendor commission fields optional
    vendor_commission = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, null=True, blank=True)
    vendor_commission_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0.00, null=True, blank=True)
    metadata = models.JSONField(blank=True, null=True)
    
    class Meta:
        db_table = 'commission_transactions'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Commission: {self.commission_amount} on {self.transaction_amount}"
    
    def save(self, *args, **kwargs):
        # Calculate net amount if not provided
        if not self.net_amount and self.transaction_amount is not None and self.commission_amount is not None:
            self.net_amount = self.transaction_amount - self.commission_amount
        super().save(*args, **kwargs)

class CommissionSettlement(models.Model):
    """Settlement of commission amounts to ISPs"""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='settlements')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    commission_transactions = models.ManyToManyField(CommissionTransaction, related_name='settlements')
    
    # Settlement method
    settlement_method = models.CharField(max_length=20, choices=[
        ('paystack', 'PayStack Transfer'),
        ('bank_transfer', 'Bank Transfer'),
        ('wallet', 'Platform Wallet'),
        ('credit', 'Platform Credit'),
    ], default='wallet')
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    settlement_date = models.DateTimeField(null=True, blank=True)
    reference = models.CharField(max_length=100, blank=True)
    
    # Metadata
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(default=tz.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'commission_settlements'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Settlement {self.reference} - {self.tenant.name} - KSh {self.amount}"

# ==================== BULK DATA MODELS ====================
class DataVendor(models.Model):
    """Telecom/data vendors that provide bulk data"""
    name = models.CharField(max_length=100)
    company_name = models.CharField(max_length=200)
    contact_email = models.EmailField()
    contact_phone = models.CharField(max_length=20)
    website = models.URLField(blank=True)
    
    # Bank details for payments
    bank_name = models.CharField(max_length=100)
    account_number = models.CharField(max_length=50)
    account_name = models.CharField(max_length=100)
    
    # Commission/agreement terms
    commission_rate = models.DecimalField(max_digits=5, decimal_places=2, default=5.0)
    agreement_start = models.DateField(default=tz.now)
    agreement_end = models.DateField(null=True, blank=True)
    
    # Status
    is_approved = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    rating = models.DecimalField(max_digits=3, decimal_places=2, default=0.0)
    
    created_at = models.DateTimeField(default=tz.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'data_vendors'
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} ({self.company_name})"

class BulkDataPackage(models.Model):
    """Bulk internet data packages available for purchase"""
    SOURCE_TYPES = [
        ('platform', 'Platform Inventory'),
        ('vendor_direct', 'Vendor Direct Sale'),
        ('vendor_marketplace', 'Vendor Marketplace'),
        ('isp_upload', 'ISP Uploaded Invoice'),
    ]
    
    PACKAGE_TYPES = [
        ('standard', 'Standard Package'),
        ('premium', 'Premium Package'),
        ('unlimited', 'Unlimited Package'),
        ('custom', 'Custom Package'),
    ]
    
    name = models.CharField(max_length=100)
    package_type = models.CharField(max_length=20, choices=PACKAGE_TYPES, default='standard')
    data_amount = models.DecimalField(max_digits=10, decimal_places=2, help_text="Data amount in GB")
    price = models.DecimalField(max_digits=10, decimal_places=2)
    validity_days = models.IntegerField(default=30, help_text="Package validity in days")
    description = models.TextField(blank=True)
    
    # Source information
    source_type = models.CharField(max_length=20, choices=SOURCE_TYPES, default='platform')
    vendor = models.ForeignKey(DataVendor, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Pricing
    base_cost = models.DecimalField(max_digits=10, decimal_places=2, help_text="Cost to platform/vendor", default=0)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, help_text="Price to ISP")
    platform_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Commission settings
    commission_included = models.BooleanField(default=True, 
                                            help_text="Whether commission is included in price")
    commission_rate = models.DecimalField(max_digits=5, decimal_places=2, default=7.5,
                                         help_text="Commission percentage for this package")
    
    # For platform inventory
    platform_margin = models.DecimalField(max_digits=5, decimal_places=2, default=15.0)
    platform_stock = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # For vendor marketplace
    is_visible = models.BooleanField(default=True)
    
    # Metadata
    is_active = models.BooleanField(default=True)
    tenant = models.ForeignKey(Tenant, on_delete=models.SET_NULL, null=True, blank=True, 
                               help_text="If null, available to all ISPs")
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(default=tz.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'bulk_data_packages'
        ordering = ['selling_price']
    
    def __str__(self):
        return f"{self.name} - {self.data_amount}GB"
    
    @property
    def platform_profit(self):
        """Calculate platform profit based on source type"""
        if self.source_type == 'platform':
            return self.selling_price - self.base_cost
        elif self.source_type in ['vendor_direct', 'vendor_marketplace']:
            return self.selling_price * self.commission_rate / 100
        elif self.source_type == 'isp_upload':
            return self.platform_fee
        return Decimal('0')
    
    @property
    def commission_amount(self):
        """Calculate commission amount"""
        return self.selling_price * self.commission_rate / 100

class ISPBulkPurchase(models.Model):
    """ISP's purchase of bulk data package"""
    STATUS_CHOICES = [
        ('pending', 'Pending Payment'),
        ('paid', 'Paid'),
        ('processing', 'Processing Distribution'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='bulk_purchases')
    package = models.ForeignKey(BulkDataPackage, on_delete=models.PROTECT)
    quantity = models.IntegerField(default=1, help_text="Number of packages purchased")
    total_data = models.DecimalField(max_digits=15, decimal_places=2, help_text="Total data in GB")
    total_price = models.DecimalField(max_digits=15, decimal_places=2)
    
    # Link to existing Payment model
    payment = models.ForeignKey('Payment', on_delete=models.SET_NULL, null=True, blank=True, 
                                related_name='bulk_purchases')
    payment_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Commission tracking
    platform_commission = models.DecimalField(max_digits=10, decimal_places=2, default=0,
                                            help_text="Platform commission amount")
    isp_net_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0,
                                       help_text="Amount ISP receives after commission")
    commission_calculated = models.BooleanField(default=False)
    
    # Distribution settings
    auto_distribute = models.BooleanField(default=True)
    distribute_to = models.CharField(max_length=20, choices=[
        ('all', 'All Active Customers'),
        ('prepaid', 'Prepaid Customers Only'),
        ('postpaid', 'Postpaid Customers Only'),
        ('custom', 'Selected Plans Only'),
    ], default='all')
    
    # Selected plans (if custom distribution) - can be added back later if needed
    # selected_plans = models.ManyToManyField('isp_management.Plan', blank=True)
    
    # Timeline
    purchased_at = models.DateTimeField(default=tz.now)
    distribution_started_at = models.DateTimeField(null=True, blank=True)
    distribution_completed_at = models.DateTimeField(null=True, blank=True)
    wallet_deposited = models.BooleanField(default=False, verbose_name="Deposited to Wallet")
    wallet_deposited_at = models.DateTimeField(null=True, blank=True)
    
    # Metadata
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True)
    
    class Meta:
        db_table = 'isp_bulk_purchases'
        ordering = ['-purchased_at']
    
    def __str__(self):
        return f"{self.tenant.name} - {self.package.name} x{self.quantity}"
    
    def save(self, *args, **kwargs):
        if not self.total_data:
            self.total_data = self.package.data_amount * self.quantity
        if not self.total_price:
            self.total_price = self.package.selling_price * self.quantity
        
        # Calculate commission if not already calculated
        if not self.commission_calculated and self.total_price > 0:
            self.calculate_commission()
            
        super().save(*args, **kwargs)
    
    def calculate_commission(self):
        """Calculate platform commission for this purchase"""
        # Get commission rate (package-specific or default)
        commission_rate = self.package.commission_rate
        
        # Calculate commission amount
        self.platform_commission = (self.total_price * commission_rate / Decimal('100'))
        self.isp_net_amount = self.total_price - self.platform_commission
        self.commission_calculated = True

class DataDistributionLog(models.Model):
    """Log of data distribution to customers"""
    bulk_purchase = models.ForeignKey(ISPBulkPurchase, on_delete=models.CASCADE, related_name='distribution_logs', null=True, blank=True)
    customer = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='data_distributions')
    user = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, related_name='distributed_data')
    data_amount = models.DecimalField(max_digits=10, decimal_places=2, help_text="Data allocated in GB")
    previous_balance = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    new_balance = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    distribution_date = models.DateTimeField(default=tz.now)
    status = models.CharField(max_length=20, choices=[
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('pending', 'Pending'),
    ], default='success')
    notes = models.TextField(blank=True)
    
    class Meta:
        db_table = 'data_distribution_logs'
        ordering = ['-distribution_date']
    
    def __str__(self):
        return f"{self.customer.username} - {self.data_amount}GB"


class DataWallet(models.Model):
    """A simple data wallet owned by an ISP (tenant) holding GB balance from bulk purchases."""
    tenant = models.OneToOneField('accounts.Tenant', on_delete=models.CASCADE, related_name='data_wallet')
    balance_gb = models.DecimalField(max_digits=15, decimal_places=2, default=0.00, help_text='Balance in GB')
    balance_bandwidth_mbps = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    updated_by = models.ForeignKey('accounts.CustomUser', on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(default=tz.now)
    updated_at = models.DateTimeField(auto_now=True)

    # External sources configuration
    allow_external_deposits = models.BooleanField(default=True)  # NEW
    max_external_deposit_per_day = models.DecimalField(max_digits=10, decimal_places=2, default=10000)  # NEW
    require_approval = models.BooleanField(default=False)  # NEW

    class Meta:
        db_table = 'data_wallets'

    def __str__(self):
        return f"{self.tenant.name} Wallet - {self.balance_gb} GB"

    def deposit(self, amount_gb, user=None, description="", reference=""):
        """Deposit data into wallet and create transaction record"""
        from decimal import Decimal
        amt = Decimal(str(amount_gb))
        if amt <= 0:
            return False
        
        previous_balance = self.balance_gb
        self.balance_gb = self.balance_gb + amt
        self.updated_by = user
        self.save()
        
        # Create transaction record
        WalletTransaction.objects.create(
            wallet=self,
            transaction_type='deposit',
            amount_gb=amt,
            amount_mbps=Decimal('0.00'),  # Explicitly set
            previous_balance=previous_balance,
            new_balance=self.balance_gb,
            reference=reference or f"DEP-{tz.now().strftime('%Y%m%d%H%M%S')}",
            description=description,
            created_by=user
        )
        return True

    def deposit_bandwidth(self, amount_mbps, user, description="", reference=""):
        """Deposit bandwidth to wallet"""
        from decimal import Decimal
        try:
            amt = Decimal(str(amount_mbps))
            if amt <= 0:
                return False
            
            previous_bandwidth = self.balance_bandwidth_mbps
            self.balance_bandwidth_mbps += amt
            self.updated_by = user
            self.save()
            
            # Create transaction record with ALL required fields
            WalletTransaction.objects.create(
                wallet=self,
                transaction_type='deposit',
                amount_gb=Decimal('0.00'),  # Data amount is 0 for bandwidth deposit
                amount_mbps=amt,
                previous_balance=Decimal('0.00'),  # Data balance (set to 0 or current)
                new_balance=Decimal('0.00'),  # Data balance (set to 0 or current)
                description=f"Bandwidth deposit: {description}",
                reference=reference or f"BW-DEP-{tz.now().strftime('%Y%m%d%H%M%S')}",
                created_by=user
            )
            return True
        except Exception as e:
            logger.error(f"Bandwidth deposit error: {e}")
            return False
    
    def withdraw(self, amount_gb, user=None, description="", reference=""):
        """Withdraw data from wallet and create transaction record"""
        from decimal import Decimal
        amt = Decimal(str(amount_gb))
        if amt <= 0:
            return False
        if self.balance_gb < amt:
            return False
        
        previous_balance = self.balance_gb
        self.balance_gb = self.balance_gb - amt
        self.updated_by = user
        self.save()
        
        # Create transaction record
        WalletTransaction.objects.create(
            wallet=self,
            transaction_type='withdrawal',
            amount_gb=amt,
            amount_mbps=Decimal('0.00'),  # Explicitly set
            previous_balance=previous_balance,
            new_balance=self.balance_gb,
            reference=reference or f"WITH-{tz.now().strftime('%Y%m%d%H%M%S')}",
            description=description,
            created_by=user
        )
        return True
    
    def allocate(self, amount_gb, user=None, description="", reference=""):
        """Alias for withdraw (for allocation to customers)"""
        # Call withdraw with allocation transaction type
        from decimal import Decimal
        amt = Decimal(str(amount_gb))
        if amt <= 0:
            return False
        if self.balance_gb < amt:
            return False
        
        previous_balance = self.balance_gb
        self.balance_gb = self.balance_gb - amt
        self.updated_by = user
        self.save()
        
        # Create transaction record with 'allocation' type
        WalletTransaction.objects.create(
            wallet=self,
            transaction_type='allocation',
            amount_gb=amt,
            amount_mbps=Decimal('0.00'),  # Explicitly set
            previous_balance=previous_balance,
            new_balance=self.balance_gb,
            reference=reference or f"ALLOC-{tz.now().strftime('%Y%m%d%H%M%S')}",
            description=description,
            created_by=user
        )
        return True
    
    def allocate_bandwidth(self, amount_mbps, user, description="", reference=""):
        """Allocate bandwidth from wallet"""
        from decimal import Decimal
        try:
            amt = Decimal(str(amount_mbps))
            
            # Check if enough bandwidth
            if self.balance_bandwidth_mbps < amt:
                logger.error(f"Insufficient bandwidth balance: {self.balance_bandwidth_mbps} < {amt}")
                return False
            
            # Get previous balance BEFORE updating
            previous_balance = self.balance_gb  # Data balance
            previous_bandwidth = self.balance_bandwidth_mbps
            
            # Update wallet balance
            self.balance_bandwidth_mbps -= amt
            self.updated_by = user
            self.save()
            
            # Create transaction record with ALL required fields
            WalletTransaction.objects.create(
                wallet=self,
                transaction_type='allocation',
                amount_gb=Decimal('0.00'),  # Data amount is 0 for bandwidth allocation
                amount_mbps=amt,
                previous_balance=previous_balance,  # Use data balance (previous_balance field)
                new_balance=self.balance_gb,  # Use current data balance (new_balance field)
                description=f"Bandwidth allocation: {description} (Previous BW: {previous_bandwidth} Mbps, New BW: {self.balance_bandwidth_mbps} Mbps)",
                reference=reference or f"BW-ALLOC-{tz.now().strftime('%Y%m%d%H%M%S')}",
                created_by=user
            )
            logger.info(f"Successfully allocated {amt} Mbps bandwidth from wallet {self.id}")
            return True
        except Exception as e:
            logger.error(f"Bandwidth allocation error: {e}", exc_info=True)
            return False
   
    
    def deposit_external(self, amount_gb, user=None, source_type='manual_entry', 
                         external_source=None, external_reference=None,
                         description="", invoice_number=None, invoice_file=None):
        """Deposit data from external sources"""
        from decimal import Decimal
        
        if not self.allow_external_deposits:
            raise ValueError("External deposits are not allowed for this wallet")
        
        amt = Decimal(str(amount_gb))
        if amt <= 0:
            return False
        
        # Check daily limit
        today = tz.now().date()
        today_deposits = WalletTransaction.objects.filter(
            wallet=self,
            source_type='external_upload',
            created_at__date=today
        ).aggregate(total=Sum('amount_gb'))['total'] or Decimal('0')
        
        if (today_deposits + amt) > self.max_external_deposit_per_day:
            raise ValueError(f"Daily external deposit limit exceeded. Limit: {self.max_external_deposit_per_day} GB")
        
        # For approval-required wallets
        if self.require_approval:
            # Create pending transaction
            transaction = WalletTransaction.objects.create(
                wallet=self,
                transaction_type='external_deposit',
                amount_gb=amt,
                previous_balance=self.balance_gb,
                new_balance=self.balance_gb + amt,
                source_type=source_type,
                external_source=external_source,
                external_reference=external_reference,
                description=f"[PENDING APPROVAL] {description}",
                created_by=user,
                status='pending_approval'  # You'd need to add this field
            )
            return {'status': 'pending_approval', 'transaction_id': transaction.id}
        
        # Immediate deposit
        previous_balance = self.balance_gb
        self.balance_gb = self.balance_gb + amt
        self.updated_by = user
        self.save()
        
        # Create transaction record
        WalletTransaction.objects.create(
            wallet=self,
            transaction_type='external_deposit',
            amount_gb=amt,
            previous_balance=previous_balance,
            new_balance=self.balance_gb,
            source_type=source_type,
            external_source=external_source,
            external_reference=external_reference,
            invoice_number=invoice_number,
            description=description,
            created_by=user
        )
        
        return {'status': 'success', 'new_balance': self.balance_gb}
    
    # Add this method for manual adjustments (admin use)
    def adjust_balance(self, amount_gb, user=None, reason="", reference=""):
        """Manual balance adjustment (positive or negative)"""
        from decimal import Decimal
        
        amt = Decimal(str(amount_gb))
        if amt == 0:
            return False
        
        previous_balance = self.balance_gb
        self.balance_gb = self.balance_gb + amt
        self.updated_by = user
        self.save()
        
        transaction_type = 'deposit' if amt > 0 else 'withdrawal'
        
        WalletTransaction.objects.create(
            wallet=self,
            transaction_type=transaction_type,
            amount_gb=abs(amt),
            previous_balance=previous_balance,
            new_balance=self.balance_gb,
            source_type='manual_entry',
            description=f"Manual adjustment: {reason}",
            reference=reference,
            created_by=user
        )
        
        return True
    
class WalletTransaction(models.Model):
    """Track all transactions (deposits/withdrawals) for a data wallet."""
    TRANSACTION_TYPES = (
        ('deposit', 'Deposit'),
        ('withdrawal', 'Withdrawal'),
        ('allocation', 'Allocation to Customer'),
        ('refund', 'Refund'),
        ('external_deposit', 'External Deposit'),
        ('manual_adjustment', 'Manual Adjustment'),
    )

    SOURCE_TYPES = (
        ('vendor_purchase', 'Vendor Purchase'),
        ('platform_purchase', 'Platform Purchase'),
        ('external_upload', 'External Data Upload'),
        ('invoice_upload', 'Invoice Upload'),
        ('api_deposit', 'API Deposit'),
        ('manual_entry', 'Manual Entry'),
    )
    
    wallet = models.ForeignKey(DataWallet, on_delete=models.CASCADE, related_name='transactions')
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    
    # Data amounts (GB)
    amount_gb = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    previous_balance = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)  # Changed to default
    new_balance = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)  # Changed to default
    
    # Bandwidth amounts (Mbps) - ADD THESE FIELDS
    amount_mbps = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Bandwidth (Mbps)")
    #previous_bandwidth_balance = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, null=True, blank=True)
    # new_bandwidth_balance = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, null=True, blank=True)
    
    source_type = models.CharField(max_length=20, choices=SOURCE_TYPES, default='vendor_purchase')
    reference = models.CharField(max_length=100, blank=True, null=True)
    description = models.TextField(blank=True)

    # For external sources
    external_source = models.CharField(max_length=200, blank=True, null=True)
    external_reference = models.CharField(max_length=200, blank=True, null=True)
    invoice_number = models.CharField(max_length=100, blank=True, null=True)
    invoice_date = models.DateField(null=True, blank=True)
    invoice_file = models.FileField(upload_to='data_invoices/', null=True, blank=True)

    created_by = models.ForeignKey('accounts.CustomUser', on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(default=tz.now)
    
    class Meta:
        db_table = 'wallet_transactions'
        ordering = ['-created_at']
    
    def __str__(self):
        if self.amount_mbps > 0:
            return f"{self.wallet.tenant.name} - {self.transaction_type} - {self.amount_mbps} Mbps"
        return f"{self.wallet.tenant.name} - {self.transaction_type} - {self.amount_gb} GB"
    
    def save(self, *args, **kwargs):
        # Ensure we always have values for required fields
        if self.amount_gb is None:
            self.amount_gb = Decimal('0.00')
        if self.amount_mbps is None:
            self.amount_mbps = Decimal('0.00')
        if self.previous_balance is None:
            self.previous_balance = Decimal('0.00')
        if self.new_balance is None:
            self.new_balance = Decimal('0.00')
        super().save(*args, **kwargs)
    

class ExternalDataSource(models.Model):
    """Track external data sources for ISPs"""
    SOURCE_TYPES = [
        ('isp_server', 'ISP Own Server'),
        ('external_api', 'External API'),
        ('csv_upload', 'CSV Upload'),
        ('manual_entry', 'Manual Entry'),
        ('invoice', 'Invoice/Bill Upload'),
    ]
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='external_data_sources')
    name = models.CharField(max_length=200)
    source_type = models.CharField(max_length=20, choices=SOURCE_TYPES)
    description = models.TextField(blank=True)
    
    # For API sources
    api_endpoint = models.URLField(blank=True, null=True)
    api_key = models.TextField(blank=True, null=True)
    api_secret = models.TextField(blank=True, null=True)
    
    # For file-based sources
    file_format = models.CharField(max_length=50, blank=True, null=True)
    
    # Configuration
    is_active = models.BooleanField(default=True)
    auto_sync = models.BooleanField(default=False)
    sync_frequency = models.CharField(max_length=20, choices=[
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
        ('manual', 'Manual Only'),
    ], default='manual')
    
    # Last sync info
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_sync_status = models.CharField(max_length=20, choices=[
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('pending', 'Pending'),
    ], null=True, blank=True)
    
    # Statistics
    total_deposits = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    last_deposit_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    last_deposit_date = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(default=tz.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'external_data_sources'
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} ({self.get_source_type_display()})"


class DatabaseConnectionConfig(models.Model):
    """Database connection configuration for ISP servers"""
    DB_TYPES = [
        ('postgresql', 'PostgreSQL'),
        ('mysql', 'MySQL'),
        ('sqlserver', 'SQL Server'),
        ('oracle', 'Oracle'),
        ('sqlite', 'SQLite'),
    ]
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='database_connections')
    name = models.CharField(max_length=200)
    db_type = models.CharField(max_length=20, choices=DB_TYPES, default='postgresql')
    
    # Connection details
    host = models.CharField(max_length=200)
    port = models.IntegerField(default=5432)
    database = models.CharField(max_length=100)
    username = models.CharField(max_length=100)
    
    # Encrypted password
    encrypted_password = models.BinaryField()
    
    # Sync configuration
    sync_customers = models.BooleanField(default=True)
    sync_data_balance = models.BooleanField(default=True)
    sync_transactions = models.BooleanField(default=False)
    sync_frequency = models.CharField(max_length=20, choices=[
        ('hourly', 'Hourly'),
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('manual', 'Manual Only'),
    ], default='daily')
    
    # Status
    is_active = models.BooleanField(default=True)
    last_tested_at = models.DateTimeField(null=True, blank=True)
    last_tested_status = models.CharField(max_length=20, choices=[
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('pending', 'Pending'),
    ], null=True, blank=True)
    
    # Sync statistics
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_sync_status = models.CharField(max_length=20, choices=[
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('partial', 'Partial'),
    ], null=True, blank=True)
    last_sync_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_synced = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    # Metadata
    created_at = models.DateTimeField(default=tz.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'database_connection_configs'
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} ({self.db_type}://{self.host}/{self.database})"

class APIIntegrationConfig(models.Model):
    """API integration configuration"""
    PROVIDER_TYPES = [
        ('safaricom', 'Safaricom Data API'),
        ('airtel', 'Airtel Data API'),
        ('mtn', 'MTN Data API'),
        ('isp_system', 'ISP Management System'),
        ('data_vendor', 'Third-party Data Vendor'),
        ('custom', 'Custom API'),
    ]
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='api_integrations')
    name = models.CharField(max_length=200)
    provider_type = models.CharField(max_length=20, choices=PROVIDER_TYPES)
    
    # API configuration
    api_endpoint = models.URLField()
    api_key = models.CharField(max_length=500, blank=True, null=True)
    api_secret = models.CharField(max_length=500, blank=True, null=True)
    
    # Request configuration
    request_timeout = models.IntegerField(default=30, help_text="Timeout in seconds")
    retry_attempts = models.IntegerField(default=3)
    
    # Sync configuration
    auto_sync = models.BooleanField(default=False)
    sync_frequency = models.CharField(max_length=20, choices=[
        ('hourly', 'Hourly'),
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
        ('manual', 'Manual Only'),
    ], default='manual')
    
    # Status
    is_active = models.BooleanField(default=True)
    last_tested_at = models.DateTimeField(null=True, blank=True)
    last_tested_status = models.CharField(max_length=20, choices=[
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('pending', 'Pending'),
    ], null=True, blank=True)
    
    # Sync statistics
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_sync_status = models.CharField(max_length=20, choices=[
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('partial', 'Partial'),
    ], null=True, blank=True)
    last_sync_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_synced = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    # Metadata
    created_at = models.DateTimeField(default=tz.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'api_integration_configs'
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} ({self.get_provider_type_display()})"
    
class DataImportLog(models.Model):
    """Log of data imports from external sources"""
    IMPORT_TYPES = [
        ('csv', 'CSV File'),
        ('excel', 'Excel File'),
        ('json', 'JSON File'),
        ('xml', 'XML File'),
        ('api', 'API Import'),
        ('manual', 'Manual Entry'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('partial', 'Partial Success'),
    ]
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='data_imports')
    import_type = models.CharField(max_length=20, choices=IMPORT_TYPES)
    filename = models.CharField(max_length=255, blank=True, null=True)
    row_number = models.IntegerField(null=True, blank=True)
    
    # Import data
    amount_gb = models.DecimalField(max_digits=15, decimal_places=2)
    reference = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    
    # Customer info (if applicable)
    customer_id = models.CharField(max_length=100, blank=True, null=True)
    customer_name = models.CharField(max_length=200, blank=True, null=True)
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    error_message = models.TextField(blank=True, null=True)
    
    # Timeline
    imported_at = models.DateTimeField(default=tz.now)
    processed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(default=tz.now)
    
    class Meta:
        db_table = 'data_import_logs'
        ordering = ['-imported_at']
        indexes = [
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['tenant', 'import_type']),
        ]
    
    def __str__(self):
        return f"{self.get_import_type_display()} Import - {self.amount_gb} GB"
    
# ==================== EXISTING MODELS ====================
class SubscriptionPlan(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        'accounts.Tenant',
        on_delete=models.CASCADE,
        related_name='subscription_plans',
        null=True,
        blank=True
    )
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    bandwidth = models.IntegerField(help_text="Mbps")  # Mbps
    data_cap = models.IntegerField(null=True, blank=True, help_text="GB (leave blank for unlimited)")  # GB, null = unlimited
    duration_days = models.IntegerField(default=30, help_text="Subscription duration in days")
    is_active = models.BooleanField(default=True)
    
    # Paystack plan ID for recurring payments
    paystack_plan_code = models.CharField(max_length=100, blank=True)
    
    created_at = models.DateTimeField(default=tz.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'subscription_plans'
        unique_together = ['tenant', 'name']
        ordering = ['price']

    @property
    def active_subscribers(self):
        """Count active subscribers for this plan"""
        return self.subscriptions.filter(is_active=True).count()
    
    @property 
    def total_subscribers(self):
        """Count total subscribers for this plan"""
        return self.subscriptions.count()

    def __str__(self):
        return f"{self.name} - ${self.price}"

class Subscription(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE,
        related_name='subscriptions'
    )
    plan = models.ForeignKey(
        SubscriptionPlan, 
        on_delete=models.CASCADE,
        related_name='subscriptions'
    )
    start_date = models.DateTimeField(default=tz.now)
    end_date = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    auto_renew = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=tz.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'subscriptions'
        ordering = ['-created_at']

    @property
    def is_currently_active(self):
        """Check if subscription is currently active"""
        now = tz.now()
        return self.start_date <= now <= self.end_date and self.is_active
    
    @property
    def days_remaining(self):
        """Calculate days remaining in subscription"""
        if self.end_date:
            today = tz.now().date()
            remaining = (self.end_date.date() - today).days
            return max(0, remaining)
        return 0
    
    def save(self, *args, **kwargs):
        # Auto-set end_date if not provided
        if not self.end_date and self.plan:
            self.end_date = tz.now() + timedelta(days=self.plan.duration_days)
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.user.username} - {self.plan.name}"

class Payment(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('refunded', 'Refunded'),
    ]

    # Payment method choices
    PAYMENT_METHOD_CHOICES = [
        ('paystack', 'Paystack'),
        ('mpesa', 'M-Pesa'),
        ('bank', 'Bank Transfer'),
        ('cash', 'Cash'),
        ('manual', 'Manual Entry'),
    ]
    
    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHOD_CHOICES,
        default='paystack'
    )
    
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    reference = models.CharField(max_length=100, unique=True, default=uuid.uuid4)
    paystack_reference = models.CharField(max_length=100, blank=True, null=True)
    paystack_access_code = models.CharField(max_length=100, blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    created_at = models.DateTimeField(default=tz.now)
    updated_at = models.DateTimeField(auto_now=True)

    # Correctly linked to SubscriptionPlan
    plan = models.ForeignKey(
        SubscriptionPlan, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='payments'
    )
    user = models.ForeignKey(
        CustomUser, 
        on_delete=models.CASCADE,
        related_name='payments'
    )

    subscription_activated = models.BooleanField(default=False, verbose_name="Subscription Auto-Activated")
    approved_by = models.ForeignKey(
        CustomUser, 
        null=True, 
        blank=True, 
        on_delete=models.SET_NULL,
        related_name='approved_payments',
        verbose_name="Approved By"
    )
    approval_date = models.DateTimeField(null=True, blank=True, verbose_name="Approval Date")

    class Meta:
        db_table = 'billing_payment'
        ordering = ['-created_at']

    def __str__(self):
        return f"Payment {self.reference} - {self.user.username} - ${self.amount}"

    @property
    def tenant(self):
        """Return the tenant associated with the payment via the user"""
        return getattr(self.user, 'tenant', None)
    
    def auto_activate_subscription(self):
        """
        Automatically activate subscription when payment is completed
        """
        try:
            if self.status == 'completed' and self.user and self.plan and not self.subscription_activated:

                from billing.services import subscription_service
                subscription_service.auto_activate_from_payment(self)
                               
                return True
                
        except Exception as e:
            logger.error(f"Failed to auto-activate subscription for payment {self.id}: {e}")
        
        return False
    
    def save(self, *args, **kwargs):
        # Check if status changed to completed
        if self.pk:
            old_payment = Payment.objects.get(pk=self.pk)
            if old_payment.status != 'completed' and self.status == 'completed':
                # Status changed to completed, trigger auto-activation
                self.auto_activate_subscription()
        elif self.status == 'completed':
            # New payment marked as completed
            self.auto_activate_subscription()
        
        super().save(*args, **kwargs)

class BulkBandwidthPackage(models.Model):
    """Model for bulk bandwidth packages sold by vendors"""
    PACKAGE_TYPES = [
        ('dedicated', 'Dedicated Bandwidth'),
        ('shared', 'Shared Bandwidth'),
        ('burst', 'Burst Bandwidth'),
    ]
    UNIT_TYPES = [
        ('mbps', 'Mbps'),
        ('gbps', 'Gbps'),
    ]
    
    vendor = models.ForeignKey('DataVendor', on_delete=models.CASCADE, related_name='bandwidth_packages')
    name = models.CharField(max_length=200)
    package_type = models.CharField(max_length=20, choices=PACKAGE_TYPES, default='dedicated')
    bandwidth_amount = models.DecimalField(max_digits=10, decimal_places=2, help_text="Amount of bandwidth")
    unit = models.CharField(max_length=10, choices=UNIT_TYPES, default='mbps')
    
    # Pricing
    base_cost = models.DecimalField(max_digits=10, decimal_places=2)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2)
    commission_rate = models.DecimalField(max_digits=5, decimal_places=2, default=7.5)
    
    # Duration
    validity_days = models.IntegerField(default=30)
    
    # Technical details
    upstream_commit = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    downstream_commit = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    burst_limit = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    # Status
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Bandwidth Package'
        verbose_name_plural = 'Bandwidth Packages'
    
    def __str__(self):
        return f"{self.name} ({self.bandwidth_amount} {self.unit})"


class ISPBandwidthPurchase(models.Model):
    """Purchase of bandwidth packages by ISPs"""
    STATUS_CHOICES = [
        ('pending', 'Pending Payment'),
        ('completed', 'Completed'),
        ('active', 'Active'),
        ('expired', 'Expired'),
        ('cancelled', 'Cancelled'),
    ]
    
    tenant = models.ForeignKey('accounts.Tenant', on_delete=models.CASCADE, related_name='bandwidth_purchases')
    bandwidth_package = models.ForeignKey(BulkBandwidthPackage, on_delete=models.CASCADE)
    
    # Purchase details
    quantity = models.IntegerField(default=1)
    total_bandwidth = models.DecimalField(max_digits=10, decimal_places=2, help_text="Total bandwidth purchased")
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    
    # Commission
    platform_commission = models.DecimalField(max_digits=10, decimal_places=2)
    isp_net_amount = models.DecimalField(max_digits=10, decimal_places=2)
    
    # Status
    payment_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    activation_date = models.DateTimeField(null=True, blank=True)
    expiry_date = models.DateTimeField(null=True, blank=True)
    
    # Technical allocation
    allocated_ip_range = models.CharField(max_length=100, blank=True, null=True)
    router_allocation = models.ForeignKey('router_manager.Router', on_delete=models.SET_NULL, null=True, blank=True)
    
    # Metadata
    purchased_at = models.DateTimeField(auto_now_add=True)
    activated_by = models.ForeignKey('accounts.CustomUser', on_delete=models.SET_NULL, null=True, blank=True)
    notes = models.TextField(blank=True)

    wallet_deposited = models.BooleanField(default=False, verbose_name="Deposited to Wallet")
    wallet_deposited_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-purchased_at']
    
    def __str__(self):
        return f"{self.tenant.name} - {self.bandwidth_package.name} ({self.payment_status})"


class ISPDataPurchase(models.Model):
    """ISP purchases from marketplace"""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]
    
    PAYMENT_METHODS = [
        ('paystack', 'PayStack'),
        ('wallet', 'Wallet Balance'),
        ('bank', 'Bank Transfer'),
    ]
    
    tenant = models.ForeignKey('accounts.Tenant', on_delete=models.CASCADE, related_name='data_purchases')
    bulk_package = models.ForeignKey('BulkDataPackage', on_delete=models.SET_NULL, null=True, blank=True)
    bulk_bandwidth_package = models.ForeignKey('BulkBandwidthPackage', on_delete=models.SET_NULL, null=True, blank=True)
    package_type = models.CharField(max_length=20, choices=[('data', 'Data'), ('bandwidth', 'Bandwidth')], default='data')    
    quantity = models.IntegerField(default=1)
    total_data_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_bandwidth_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    platform_commission = models.DecimalField(max_digits=10, decimal_places=2)
    isp_net_amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS, default='paystack')
    payment_reference = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    purchased_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    # If these fields are required:
    vendor_commission = models.DecimalField(max_digits=10, decimal_places=2)
    vendor_commission_rate = models.DecimalField(max_digits=5, decimal_places=2)

    wallet_deposited = models.BooleanField(default=False, verbose_name="Deposited to Wallet")
    wallet_deposited_at = models.DateTimeField(null=True, blank=True)
    
      
    class Meta:
        ordering = ['-purchased_at']
    
    def __str__(self):
        return f"Purchase #{self.id} - {self.get_status_display()} - KSh {self.total_price}"

# ==================== HELPER FUNCTIONS ====================

def create_payment_for_bulk_purchase(bulk_purchase, user=None):
    """Create a payment record for bulk purchase"""
    from django.db import transaction
    
    try:
        with transaction.atomic():
            # Create payment
            payment = Payment.objects.create(
                user=user or bulk_purchase.created_by,
                amount=bulk_purchase.total_price,
                status='completed',
                reference=f"BULK-{bulk_purchase.id}-{tz.now().strftime('%Y%m%d%H%M%S')}",
                payment_method='manual',  # Change to 'bulk_purchase' if you add it to choices
                metadata={
                    'bulk_purchase_id': str(bulk_purchase.id),
                    'package_name': bulk_purchase.package.name,
                    'quantity': bulk_purchase.quantity,
                    'tenant_id': str(bulk_purchase.tenant.id)
                }
            )
            
            # Link payment to bulk purchase
            bulk_purchase.payment = payment
            bulk_purchase.payment_status = 'completed'
            bulk_purchase.save()
            
            return payment
    except Exception as e:
        logger.error(f"Failed to create payment for bulk purchase {bulk_purchase.id}: {e}")
        return None


def create_commission_for_payment(payment, commission_rate=None):
    """Create commission transaction for a payment"""
    if not payment.user.tenant:
        return None
    
    try:
        # Determine commission rate
        if commission_rate is None:
            # Get default commission rate for subscription type
            commission = PlatformCommission.objects.filter(
                service_type='subscription',
                applies_to_all=True,
                is_active=True
            ).first()
            commission_rate = commission.rate if commission else Decimal('7.5')
        
        # Calculate commission amount
        commission_amount = (payment.amount * commission_rate) / Decimal('100')
        
        # Create commission transaction
        commission_transaction = CommissionTransaction.objects.create(
            tenant=payment.user.tenant,
            payment=payment,
            commission_type='subscription',
            transaction_amount=payment.amount,
            commission_amount=commission_amount,
            net_amount=payment.amount - commission_amount,
            status='calculated',
            description=f"Commission for subscription payment {payment.reference}",
            metadata={
                'customer_id': str(payment.user.id),
                'plan_name': payment.plan.name if payment.plan else 'N/A',
                'commission_rate': str(commission_rate)
            }
        )
        
        return commission_transaction
    except Exception as e:
        logger.error(f"Failed to create commission for payment {payment.id}: {e}")
        return None


def create_commission_for_bulk_data_purchase(bulk_purchase):
    """Create commission for bulk data purchase"""
    try:
        # Check if commission already exists
        existing_commission = CommissionTransaction.objects.filter(
            bulk_purchase=bulk_purchase
        ).exists()
        
        if existing_commission:
            return None
        
        # Create commission transaction
        commission_transaction = CommissionTransaction.objects.create(
            tenant=bulk_purchase.tenant,
            payment=bulk_purchase.payment,
            commission_type='bulk_data',
            transaction_amount=bulk_purchase.total_price,
            commission_amount=bulk_purchase.platform_commission,
            net_amount=bulk_purchase.isp_net_amount,
            bulk_purchase=bulk_purchase,
            status='calculated',
            description=f"Commission for bulk data purchase: {bulk_purchase.package.name} x{bulk_purchase.quantity}",
            metadata={
                'purchase_id': str(bulk_purchase.id),
                'package_name': bulk_purchase.package.name,
                'quantity': bulk_purchase.quantity,
                'commission_calculated': bulk_purchase.commission_calculated
            }
        )
        
        return commission_transaction
    except Exception as e:
        logger.error(f"Failed to create commission for bulk purchase {bulk_purchase.id}: {e}")
        return None


def create_commission_for_bandwidth_purchase(bandwidth_purchase):
    """Create commission for bandwidth purchase"""
    try:
        # Check if commission already exists
        existing_commission = CommissionTransaction.objects.filter(
            bandwidth_purchase=bandwidth_purchase
        ).exists()
        
        if existing_commission:
            return None
        
        # Create commission transaction
        commission_transaction = CommissionTransaction.objects.create(
            tenant=bandwidth_purchase.tenant,
            commission_type='bandwidth',
            transaction_amount=bandwidth_purchase.total_price,
            commission_amount=bandwidth_purchase.platform_commission,
            net_amount=bandwidth_purchase.isp_net_amount,
            bandwidth_purchase=bandwidth_purchase,
            status='calculated',
            description=f"Commission for bandwidth purchase: {bandwidth_purchase.bandwidth_package.name}",
            metadata={
                'purchase_id': str(bandwidth_purchase.id),
                'package_name': bandwidth_purchase.bandwidth_package.name,
                'quantity': bandwidth_purchase.quantity
            }
        )
        
        return commission_transaction
    except Exception as e:
        logger.error(f"Failed to create commission for bandwidth purchase {bandwidth_purchase.id}: {e}")
        return None

