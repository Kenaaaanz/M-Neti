# billing/view_admin.py
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Sum, Count
from .models import (
    PaystackConfiguration, Tenant, BulkDataPackage, DataVendor, 
    PlatformCommission, ISPBulkPurchase, CommissionTransaction
)
from .paystack import PaystackAPI
from decimal import Decimal

@staff_member_required
def admin_configure_paystack_subaccount(request, tenant_id):
    """Configure Paystack subaccount for a tenant - FOR SUPERADMINS"""
    tenant = get_object_or_404(Tenant, id=tenant_id)
    
    try:
        config = PaystackConfiguration.objects.get(tenant=tenant)
    except PaystackConfiguration.DoesNotExist:
        config = None
    
    if request.method == 'POST':
        bank_code = request.POST.get('bank_code')
        account_number = request.POST.get('account_number')
        account_name = request.POST.get('account_name')
        
        if not all([bank_code, account_number, account_name]):
            messages.error(request, "All fields are required")
            return redirect('configure_paystack', tenant_id=tenant_id)
        
        paystack = PaystackAPI()
        
        try:
            # Create subaccount with 7.5% platform fee
            response = paystack.create_subaccount(
                business_name=tenant.name,
                bank_code=bank_code,
                account_number=account_number,
                percentage_charge=7.5
            )
            
            if response and response.get('status'):
                subaccount_data = response['data']
                
                # Store subaccount info in session for display
                subaccount_info = {
                    'bank_code': bank_code,
                    'account_number': account_number,
                    'account_name': account_name,
                    'subaccount_code': subaccount_data['subaccount_code'],
                    'business_name': tenant.name
                }
                request.session['paystack_subaccount_info'] = subaccount_info
                
                # Save only the fields that exist in the model
                if config:
                    # Only update fields that actually exist in the model
                    if hasattr(config, 'subaccount_code'):
                        config.subaccount_code = subaccount_data['subaccount_code']
                    
                    # Store additional data in available fields if they exist
                    if hasattr(config, 'public_key'):
                        # Use public_key field to store bank code if needed
                        config.public_key = f"bank:{bank_code}"
                    
                    if hasattr(config, 'secret_key'):
                        # Use secret_key field to store account info if needed
                        config.secret_key = f"account:{account_number}"
                    
                    config.is_active = True
                    config.save()
                    messages.success(request, f"Paystack subaccount updated successfully for {tenant.name}")
                else:
                    # Create new config with only the fields that exist
                    create_data = {
                        'tenant': tenant,
                        'is_active': True
                    }
                    
                    # Only add fields that exist in the model
                    if hasattr(PaystackConfiguration, 'subaccount_code'):
                        create_data['subaccount_code'] = subaccount_data['subaccount_code']
                    
                    if hasattr(PaystackConfiguration, 'public_key'):
                        create_data['public_key'] = f"bank:{bank_code}"
                    
                    if hasattr(PaystackConfiguration, 'secret_key'):
                        create_data['secret_key'] = f"account:{account_number}"
                    
                    PaystackConfiguration.objects.create(**create_data)
                    messages.success(request, f"Paystack subaccount created successfully for {tenant.name}")
                
                return redirect('admin:index')
            else:
                error_msg = response.get('message', 'Unknown error occurred')
                messages.error(request, f"Failed to create Paystack subaccount: {error_msg}")
        
        except Exception as e:
            messages.error(request, f"Error configuring Paystack: {str(e)}")
    
    # Get banks list - using Kenya instead of Nigeria
    paystack = PaystackAPI()
    banks_response = paystack._make_request("GET", "bank", params={"country": "kenya"})
    
    banks = []
    if banks_response and banks_response.get('status'):
        banks = banks_response.get('data', [])
    else:
        messages.warning(request, "Could not load banks list from Paystack")
    
    # Get subaccount info from session for display
    subaccount_info = request.session.get('paystack_subaccount_info', {})
    
    context = {
        'tenant': tenant,
        'config': config,
        'banks': banks,
        'subaccount_info': subaccount_info,
        'debug': False  # Set to True for debugging
    }
    
    return render(request, 'admin/configure_paystack.html', context)

@staff_member_required
def admin_bulk_data_packages(request):
    """Superadmin: Manage bulk data packages"""
    packages = BulkDataPackage.objects.all().order_by('-created_at')
    vendors = DataVendor.objects.filter(is_active=True)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'create_package':
            name = request.POST.get('name')
            data_amount = request.POST.get('data_amount')
            price = request.POST.get('price')
            source_type = request.POST.get('source_type')
            commission_rate = request.POST.get('commission_rate', 7.5)
            
            package = BulkDataPackage.objects.create(
                name=name,
                data_amount=data_amount,
                price=price,
                selling_price=price,
                source_type=source_type,
                commission_rate=commission_rate,
                is_active=True,
                created_by=request.user
            )
            
            messages.success(request, f'Package "{name}" created successfully')
            
        elif action == 'update_package':
            package_id = request.POST.get('package_id')
            package = get_object_or_404(BulkDataPackage, id=package_id)
            
            package.name = request.POST.get('name')
            package.data_amount = request.POST.get('data_amount')
            package.price = request.POST.get('price')
            package.selling_price = request.POST.get('price')
            package.commission_rate = request.POST.get('commission_rate', 7.5)
            package.is_active = request.POST.get('is_active') == 'on'
            package.save()
            
            messages.success(request, f'Package "{package.name}" updated successfully')
    
    context = {
        'packages': packages,
        'vendors': vendors,
    }
    
    return render(request, 'admin/bulk_data_packages.html', context)

@staff_member_required
def admin_commission_settings(request):
    """Superadmin: Manage platform commission rates"""
    commissions = PlatformCommission.objects.all()
    
    if request.method == 'POST':
        service_type = request.POST.get('service_type')
        rate = request.POST.get('rate')
        applies_to_all = request.POST.get('applies_to_all') == 'true'
        tenant_id = request.POST.get('tenant_id')
        
        tenant = None
        if tenant_id and not applies_to_all:
            tenant = Tenant.objects.get(id=tenant_id)
        
        commission, created = PlatformCommission.objects.update_or_create(
            service_type=service_type,
            tenant=tenant if not applies_to_all else None,
            defaults={
                'rate': rate,
                'applies_to_all': applies_to_all,
                'is_active': True,
            }
        )
        
        messages.success(request, f'Commission settings updated for {service_type}')
    
    context = {
        'commissions': commissions,
        'tenants': Tenant.objects.all(),
    }
    return render(request, 'admin/commission_settings.html', context)

@staff_member_required
def admin_bulk_purchases_report(request):
    """Superadmin: Report on bulk data purchases"""
    # Filter parameters
    status_filter = request.GET.get('status', '')
    tenant_filter = request.GET.get('tenant', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    
    purchases = ISPBulkPurchase.objects.all().order_by('-purchased_at')
    
    if status_filter:
        purchases = purchases.filter(payment_status=status_filter)
    
    if tenant_filter:
        purchases = purchases.filter(tenant_id=tenant_filter)
    
    if date_from:
        purchases = purchases.filter(purchased_at__gte=date_from)
    
    if date_to:
        purchases = purchases.filter(purchased_at__lte=date_to)
    
    # Statistics
    total_purchases = purchases.count()
    total_amount = purchases.aggregate(total=Sum('total_price'))['total'] or Decimal('0')
    total_commission = purchases.aggregate(total=Sum('platform_commission'))['total'] or Decimal('0')
    total_isp_net = purchases.aggregate(total=Sum('isp_net_amount'))['total'] or Decimal('0')
    
    context = {
        'purchases': purchases,
        'total_purchases': total_purchases,
        'total_amount': total_amount,
        'total_commission': total_commission,
        'total_isp_net': total_isp_net,
        'tenants': Tenant.objects.all(),
    }
    
    return render(request, 'admin/bulk_purchases_report.html', context)

@staff_member_required
def admin_platform_commission_report(request):
    """Platform-wide commission report"""
    # Summary by service type
    by_service = CommissionTransaction.objects.values(
        'commission__service_type'
    ).annotate(
        total_amount=Sum('transaction_amount'),
        total_commission=Sum('commission_amount'),
        count=Count('id')
    ).order_by('-total_commission')
    
    # Summary by ISP
    by_isp = CommissionTransaction.objects.values(
        'tenant__name'
    ).annotate(
        total_amount=Sum('transaction_amount'),
        total_commission=Sum('commission_amount'),
        count=Count('id')
    ).order_by('-total_commission')
    
    # Total summary
    total_summary = CommissionTransaction.objects.aggregate(
        total_transactions=Sum('transaction_amount'),
        total_commission=Sum('commission_amount'),
        total_count=Count('id')
    )
    
    context = {
        'by_service': by_service,
        'by_isp': by_isp,
        'total_summary': total_summary,
    }
    
    return render(request, 'admin/platform_commission_report.html', context)

@staff_member_required
def admin_data_vendors(request):
    """Manage data vendors"""
    vendors = DataVendor.objects.all().order_by('-created_at')
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'create_vendor':
            vendor = DataVendor.objects.create(
                name=request.POST.get('name'),
                company_name=request.POST.get('company_name'),
                contact_email=request.POST.get('contact_email'),
                contact_phone=request.POST.get('contact_phone'),
                commission_rate=request.POST.get('commission_rate', 5.0),
                is_approved=True,
                is_active=True
            )
            
            messages.success(request, f'Vendor "{vendor.name}" created successfully')
            
        elif action == 'toggle_approval':
            vendor_id = request.POST.get('vendor_id')
            vendor = get_object_or_404(DataVendor, id=vendor_id)
            vendor.is_approved = not vendor.is_approved
            vendor.save()
            
            status = "approved" if vendor.is_approved else "unapproved"
            messages.success(request, f'Vendor "{vendor.name}" {status}')
    
    context = {
        'vendors': vendors,
    }
    
    return render(request, 'admin/data_vendors.html', context)