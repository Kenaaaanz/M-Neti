# billing/admin.py
from django.contrib import admin
from .models import (
    PaystackConfiguration, SubscriptionPlan, Subscription, Payment,
    PlatformCommission, CommissionTransaction, CommissionSettlement,
    DataVendor, BulkDataPackage, ISPBulkPurchase, DataDistributionLog,
    DataWallet, WalletTransaction, ExternalDataSource,
    DatabaseConnectionConfig, APIIntegrationConfig, DataImportLog,
    BulkBandwidthPackage, ISPBandwidthPurchase, ISPDataPurchase
)
from django.utils import timezone

# Payment Admin with auto-activation support
@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['reference', 'user', 'plan', 'amount', 'status', 'created_at', 'subscription_activated']
    list_filter = ['status', 'payment_method', 'subscription_activated']
    search_fields = ['reference', 'user__username', 'user__email']
    readonly_fields = ['created_at', 'updated_at']
    actions = ['approve_payments', 'mark_as_completed']
    
    fieldsets = (
        ('Payment Information', {
            'fields': ('user', 'plan', 'amount', 'reference', 'status')
        }),
        ('Payment Details', {
            'fields': ('payment_method', 'paystack_reference', 'paystack_access_code')
        }),
        ('Auto-Activation', {
            'fields': ('subscription_activated', 'approved_by', 'approval_date'),
            'classes': ('collapse',),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )
    
    @admin.action(description='Approve selected payments and activate subscriptions')
    def approve_payments(self, request, queryset):
        for payment in queryset:
            if payment.status != 'completed':
                payment.status = 'completed'
                payment.approved_by = request.user
                payment.approval_date = timezone.now()
                payment.save()  # This triggers auto-activation
                
                # Log the action
                from django.contrib import messages
                self.message_user(
                    request, 
                    f"Payment {payment.reference} approved and subscription activated", 
                    messages.SUCCESS
                )
        
        self.message_user(request, f"{queryset.count()} payments approved and subscriptions activated.")
    
    @admin.action(description='Mark as completed (auto-activate)')
    def mark_as_completed(self, request, queryset):
        for payment in queryset:
            payment.status = 'completed'
            payment.save()  # This triggers auto-activation
        
        self.message_user(request, f"{queryset.count()} payments marked as completed and subscriptions activated.")
    
    def save_model(self, request, obj, form, change):
        # If status changed to completed, log who approved it
        if change:
            old_obj = Payment.objects.get(pk=obj.pk)
            if old_obj.status != 'completed' and obj.status == 'completed':
                obj.approved_by = request.user
                obj.approval_date = timezone.now()
                
        super().save_model(request, obj, form, change)

# Register other models
@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = ['name', 'tenant', 'price', 'bandwidth', 'is_active']
    list_filter = ['is_active', 'tenant']
    search_fields = ['name', 'description']

@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ['user', 'plan', 'start_date', 'end_date', 'is_active']
    list_filter = ['is_active', 'plan']
    search_fields = ['user__username', 'user__email']

@admin.register(PaystackConfiguration)
class PaystackConfigurationAdmin(admin.ModelAdmin):
    list_display = ['tenant', 'account_name', 'is_active']
    list_filter = ['is_active', 'tenant']

@admin.register(PlatformCommission)
class PlatformCommissionAdmin(admin.ModelAdmin):
    list_display = ['service_type', 'rate', 'tenant', 'is_active']
    list_filter = ['service_type', 'is_active']

@admin.register(CommissionTransaction)
class CommissionTransactionAdmin(admin.ModelAdmin):
    list_display = ['payment', 'tenant', 'commission_amount', 'status']
    list_filter = ['status', 'tenant']

# Register all other models...
admin.site.register(CommissionSettlement)
admin.site.register(DataVendor)
admin.site.register(BulkDataPackage)
admin.site.register(ISPBulkPurchase)
admin.site.register(DataDistributionLog)
admin.site.register(DataWallet)
admin.site.register(WalletTransaction)
admin.site.register(ExternalDataSource)
admin.site.register(DatabaseConnectionConfig)
admin.site.register(APIIntegrationConfig)
admin.site.register(DataImportLog)
admin.site.register(BulkBandwidthPackage)
admin.site.register(ISPBandwidthPurchase)
admin.site.register(ISPDataPurchase)