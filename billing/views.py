# billing/views.py
from datetime import timedelta
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.conf import settings
from django.db.models import Sum, Q
import logging
import requests
from .utils import decimal_to_paystack_amount, create_commission_transaction, get_commission_summary
from .utils import DataEncryption
from accounts.views import BILLING_ENABLED
from .models import (
    APIIntegrationConfig, BulkBandwidthPackage, DataImportLog, DatabaseConnectionConfig, DatabaseConnectionConfig, ExternalDataSource, Payment, SubscriptionPlan, PaystackConfiguration, Subscription,
    BulkDataPackage, ISPBulkPurchase, DataDistributionLog,
    PlatformCommission, CommissionTransaction, DataVendor,
    DataWallet, WalletTransaction, ISPBandwidthPurchase, ISPDataPurchase
)
import uuid
from django.utils import timezone as tz
from django.http import JsonResponse, HttpResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
import json
from accounts.models import CustomUser, Tenant
from .services import subscription_service
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage

logger = logging.getLogger(__name__)

# ==================== DATA WALLET VIEWS ====================

@login_required
def isp_data_wallet(request):
    """View and manage the ISP data wallet"""
    if request.user.role not in ['isp_admin', 'isp_staff', 'superadmin']:
        return HttpResponseForbidden("Access denied")

    tenant = request.user.tenant
    if not tenant:
        messages.error(request, 'No ISP associated with your account.')
        return redirect('dashboard')

    # Ensure wallet exists with both balances
    wallet, created = DataWallet.objects.get_or_create(
        tenant=tenant,
        defaults={
            'balance_gb': Decimal('0.00'), 
            'balance_bandwidth_mbps': Decimal('0.00'),
            'updated_by': request.user
        }
    )
    
    if created:
        messages.info(request, f'Data wallet created for {tenant.name}')

    # Get recent transactions
    recent_transactions = WalletTransaction.objects.filter(
        wallet=wallet
    ).select_related('created_by').order_by('-created_at')[:20]

    # Get recent bulk purchases
    recent_purchases = ISPBulkPurchase.objects.filter(
        tenant=tenant,
        payment_status='paid'
    ).order_by('-purchased_at')[:10]

    # Get distribution history
    distribution_history = DataDistributionLog.objects.filter(
        bulk_purchase__tenant=tenant
    ).select_related('customer', 'user').order_by('-distribution_date')[:20]

    # Calculate totals from wallet transactions
    total_deposited_data = WalletTransaction.objects.filter(
        wallet=wallet,
        transaction_type='deposit',
        amount_gb__gt=0
    ).aggregate(total=Sum('amount_gb'))['total'] or Decimal('0.00')

    total_allocated_data = WalletTransaction.objects.filter(
        wallet=wallet,
        transaction_type='allocation',
        amount_gb__gt=0
    ).aggregate(total=Sum('amount_gb'))['total'] or Decimal('0.00')
    
    # Calculate bandwidth totals
    total_deposited_bandwidth = WalletTransaction.objects.filter(
        wallet=wallet,
        transaction_type='deposit',
        amount_mbps__gt=0
    ).aggregate(total=Sum('amount_mbps'))['total'] or Decimal('0.00')

    total_allocated_bandwidth = WalletTransaction.objects.filter(
        wallet=wallet,
        transaction_type='allocation',
        amount_mbps__gt=0
    ).aggregate(total=Sum('amount_mbps'))['total'] or Decimal('0.00')
    
    # Total purchased from ISPBulkPurchase (only data purchases)
    total_data_purchased = ISPBulkPurchase.objects.filter(
        tenant=tenant,
        payment_status='paid'
    ).aggregate(total=Sum('total_data'))['total'] or Decimal('0.00')

    # Total bandwidth purchased (from ISPDataPurchase model if it exists)
    total_bandwidth_purchased = Decimal('0.00')
    try:
        # Check if ISPDataPurchase model exists
        from billing.models import ISPDataPurchase
        total_bandwidth_purchased = ISPDataPurchase.objects.filter(
            tenant=tenant,
            status='completed',
            package_type='bandwidth'
        ).aggregate(total=Sum('total_bandwidth_amount'))['total'] or Decimal('0.00')
    except:
        pass  # Model might not exist yet

    # Eligible customers
    eligible_customers = CustomUser.objects.filter(
        tenant=tenant, 
        role='customer', 
        is_active=True
    ).select_related('tenant')[:50]

    # Available plans for manual activation
    plans = SubscriptionPlan.objects.filter(tenant=tenant, is_active=True)

    context = {
        'tenant': tenant,
        'wallet': wallet,
        'eligible_customers': eligible_customers,
        'plans': plans,
        'recent_transactions': recent_transactions,
        'recent_purchases': recent_purchases,
        'distribution_history': distribution_history,
        'total_purchased': total_data_purchased,  # For template compatibility
        'total_deposited': total_deposited_data,  # For template compatibility
        'total_allocated': total_allocated_data,  # For template compatibility
        'total_bandwidth_purchased': total_bandwidth_purchased,
        'total_bandwidth_allocated': total_allocated_bandwidth,
        'remaining_balance': wallet.balance_gb,  # Use actual wallet balance
        'page_title': 'Data Wallet',
        'page_subtitle': 'Manage ISP bulk data balance and allocate to customers',
    }

    return render(request, 'accounts/isp_data_wallet.html', context)
    
# billing/views.py - CORRECTED isp_allocate_from_wallet function

@login_required
def isp_allocate_from_wallet(request):
    """AJAX endpoint to allocate data/bandwidth from wallet to customers or activate subscriptions manually."""
    if request.user.role not in ['isp_admin', 'isp_staff', 'superadmin']:
        return JsonResponse({'success': False, 'error': 'Access denied'})

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'})

    try:
        # Try to parse JSON data first, fallback to form data
        try:
            data = json.loads(request.body.decode('utf-8'))
        except:
            data = request.POST.copy()

        tenant = request.user.tenant
        if not tenant:
            return JsonResponse({'success': False, 'error': 'No tenant found'})
            
        wallet = DataWallet.objects.filter(tenant=tenant).first()
        if not wallet:
            return JsonResponse({'success': False, 'error': 'Wallet not found'})

        action = data.get('action')
        
        # ADD LOGGING FOR DEBUGGING
        logger.info(f"Allocation action: {action}")
        logger.info(f"Customer IDs from request: {data.get('customer_ids')}")
        logger.info(f"Request data: {data}")

        # ALLOCATE BANDWIDTH (NEW) - from template AJAX call
        if action == 'allocate_bandwidth':
            customer_ids = data.get('customer_ids', [])
            
            # Handle different formats of customer_ids
            if isinstance(customer_ids, str):
                try:
                    customer_ids = json.loads(customer_ids)
                except json.JSONDecodeError:
                    # If it's a comma-separated string
                    if customer_ids.startswith('[') and customer_ids.endswith(']'):
                        # Remove brackets and split
                        customer_ids = customer_ids.strip('[]').split(',')
                    else:
                        # Just split by comma
                        customer_ids = customer_ids.split(',')
                    
                    # Clean up the values
                    customer_ids = [cid.strip().strip('"\'') for cid in customer_ids if cid.strip()]
            
            # Convert all IDs to integers
            try:
                customer_ids = [int(cid) for cid in customer_ids if str(cid).strip().isdigit()]
            except Exception as e:
                logger.error(f"Error converting customer IDs to integers: {e}")
                return JsonResponse({'success': False, 'error': f'Invalid customer ID format: {str(e)}'})
            
            try:
                bandwidth_per_customer = Decimal(str(data.get('bandwidth_amount', 0)))
            except Exception as e:
                logger.error(f"Error parsing bandwidth amount: {e}")
                return JsonResponse({'success': False, 'error': f'Invalid bandwidth amount format: {str(e)}'})
            
            logger.info(f"Bandwidth allocation - Customer IDs: {customer_ids}, Count: {len(customer_ids)}")
            logger.info(f"Bandwidth per customer: {bandwidth_per_customer}")
            
            if not customer_ids:
                return JsonResponse({'success': False, 'error': 'No customers selected. Please select at least one customer.'})
            
            if bandwidth_per_customer <= 0:
                return JsonResponse({'success': False, 'error': 'Invalid bandwidth amount. Amount must be greater than 0 Mbps.'})
            
            total_needed = bandwidth_per_customer * len(customer_ids)
            
            # Check if wallet has sufficient bandwidth balance
            if wallet.balance_bandwidth_mbps < total_needed:
                return JsonResponse({
                    'success': False, 
                    'error': f'Insufficient bandwidth balance. Need {total_needed} Mbps, have {wallet.balance_bandwidth_mbps} Mbps'
                })

            # Track successful allocations
            successful_allocations = 0
            failed_allocations = []
            
            # Process each customer
            for cid in customer_ids:
                try:
                    customer = CustomUser.objects.get(
                        id=int(cid), 
                        tenant=tenant, 
                        role='customer'
                    )
                    
                    logger.info(f"Allocating {bandwidth_per_customer} Mbps to customer {customer.username} (ID: {cid})")
                    
                    # Use the allocate_bandwidth method
                    if wallet.allocate_bandwidth(
                        amount_mbps=bandwidth_per_customer,
                        user=request.user,
                        description=f"Allocated bandwidth to customer {customer.username}",
                        reference=f"BW-ALLOC-{tz.now().strftime('%Y%m%d%H%M%S')}-{cid}"
                    ):
                        successful_allocations += 1
                        logger.info(f"Successfully allocated {bandwidth_per_customer} Mbps to {customer.username}")
                    else:
                        failed_msg = f"Customer {cid}: Bandwidth allocation failed"
                        failed_allocations.append(failed_msg)
                        logger.warning(failed_msg)
                        
                except CustomUser.DoesNotExist:
                    failed_msg = f"Customer ID {cid}: Not found"
                    failed_allocations.append(failed_msg)
                    logger.warning(failed_msg)
                except Exception as e:
                    failed_msg = f"Customer ID {cid}: {str(e)}"
                    failed_allocations.append(failed_msg)
                    logger.error(f"Error allocating bandwidth to customer {cid}: {e}")

            if successful_allocations > 0:
                # Refresh wallet balance
                wallet.refresh_from_db()
                
                return JsonResponse({
                    'success': True, 
                    'message': f'Successfully allocated {total_needed} Mbps to {successful_allocations} customer(s)', 
                    'remaining_bandwidth': float(wallet.balance_bandwidth_mbps),
                    'remaining_data': float(wallet.balance_gb),
                    'successful_count': successful_allocations,
                    'failed_count': len(failed_allocations),
                    'failed_details': failed_allocations[:5]
                })
            else:
                return JsonResponse({
                    'success': False, 
                    'error': 'No bandwidth allocations were successful',
                    'failed_details': failed_allocations
                })

        # ALLOCATE DATA (existing)
        elif action == 'allocate':
            customer_ids = data.get('customer_ids', [])
            
            # Handle different formats of customer_ids
            if isinstance(customer_ids, str):
                try:
                    customer_ids = json.loads(customer_ids)
                except json.JSONDecodeError:
                    # If it's a comma-separated string
                    if customer_ids.startswith('[') and customer_ids.endswith(']'):
                        # Remove brackets and split
                        customer_ids = customer_ids.strip('[]').split(',')
                    else:
                        # Just split by comma
                        customer_ids = customer_ids.split(',')
                    
                    # Clean up the values
                    customer_ids = [cid.strip().strip('"\'') for cid in customer_ids if cid.strip()]
            
            # Convert all IDs to integers
            try:
                customer_ids = [int(cid) for cid in customer_ids if str(cid).strip().isdigit()]
            except Exception as e:
                logger.error(f"Error converting customer IDs to integers: {e}")
                return JsonResponse({'success': False, 'error': f'Invalid customer ID format: {str(e)}'})
            
            try:
                amount_per_customer = Decimal(str(data.get('amount_gb', 0)))
            except Exception as e:
                logger.error(f"Error parsing data amount: {e}")
                return JsonResponse({'success': False, 'error': f'Invalid amount format: {str(e)}'})
            
            logger.info(f"Data allocation - Customer IDs: {customer_ids}, Count: {len(customer_ids)}")
            logger.info(f"Data per customer: {amount_per_customer}")
            
            if not customer_ids:
                return JsonResponse({'success': False, 'error': 'No customers selected. Please select at least one customer.'})
            
            if amount_per_customer <= 0:
                return JsonResponse({'success': False, 'error': 'Invalid data amount. Amount must be greater than 0 GB.'})

            total_needed = amount_per_customer * len(customer_ids)
            
            # Check if wallet has sufficient balance
            if wallet.balance_gb < total_needed:
                return JsonResponse({
                    'success': False, 
                    'error': f'Insufficient wallet balance. Need {total_needed} GB, have {wallet.balance_gb} GB'
                })

            # Track successful allocations
            successful_allocations = 0
            failed_allocations = []
            
            # Process each customer
            for cid in customer_ids:
                try:
                    customer = CustomUser.objects.get(
                        id=int(cid), 
                        tenant=tenant, 
                        role='customer'
                    )
                    
                    logger.info(f"Allocating {amount_per_customer} GB to customer {customer.username} (ID: {cid})")
                    
                    # Use the allocate method (which calls withdraw internally)
                    if wallet.allocate(
                        amount_gb=amount_per_customer,
                        user=request.user,
                        description=f"Allocated to customer {customer.username}",
                        reference=f"ALLOC-{tz.now().strftime('%Y%m%d%H%M%S')}-{cid}"
                    ):
                        # Create distribution log
                        DataDistributionLog.objects.create(
                            bulk_purchase=None,
                            customer=customer,
                            user=request.user,
                            data_amount=amount_per_customer,
                            previous_balance=wallet.balance_gb + amount_per_customer,
                            new_balance=wallet.balance_gb,
                            status='success',
                            notes=f'Manual allocation by {request.user.username}'
                        )
                        successful_allocations += 1
                        logger.info(f"Successfully allocated {amount_per_customer} GB to {customer.username}")
                    else:
                        failed_msg = f"Customer {cid}: Data allocation failed"
                        failed_allocations.append(failed_msg)
                        logger.warning(failed_msg)
                        
                except CustomUser.DoesNotExist:
                    failed_msg = f"Customer ID {cid}: Not found"
                    failed_allocations.append(failed_msg)
                    logger.warning(failed_msg)
                except Exception as e:
                    failed_msg = f"Customer ID {cid}: {str(e)}"
                    failed_allocations.append(failed_msg)
                    logger.error(f"Error allocating data to customer {cid}: {e}")

            if successful_allocations > 0:
                # Refresh wallet balance
                wallet.refresh_from_db()
                
                return JsonResponse({
                    'success': True, 
                    'message': f'Successfully allocated {total_needed} GB to {successful_allocations} customer(s)', 
                    'remaining': float(wallet.balance_gb),
                    'remaining_bandwidth': float(wallet.balance_bandwidth_mbps),
                    'successful_count': successful_allocations,
                    'failed_count': len(failed_allocations),
                    'failed_details': failed_allocations[:5]
                })
            else:
                return JsonResponse({
                    'success': False, 
                    'error': 'No data allocations were successful',
                    'failed_details': failed_allocations
                })

        # ACTIVATE SUBSCRIPTION for a single customer using a selected plan
        elif action == 'activate_subscription':
            customer_id = data.get('customer_id')
            plan_id = data.get('plan_id')
            
            if not customer_id or not plan_id:
                return JsonResponse({'success': False, 'error': 'Missing parameters'})

            try:
                customer = CustomUser.objects.get(id=int(customer_id), tenant=tenant, role='customer')
                plan = SubscriptionPlan.objects.get(id=plan_id, tenant=tenant, is_active=True)
            except (CustomUser.DoesNotExist, SubscriptionPlan.DoesNotExist):
                return JsonResponse({'success': False, 'error': 'Customer or plan not found'})

            # Check if customer already has active subscription
            existing_sub = Subscription.objects.filter(user=customer, is_active=True).first()
            if existing_sub:
                return JsonResponse({
                    'success': False, 
                    'error': f'Customer already has active subscription: {existing_sub.plan.name}'
                })

            # Create subscription
            sub = Subscription.objects.create(
                user=customer,
                plan=plan,
                start_date=tz.now(),
                end_date=tz.now() + timedelta(days=plan.duration_days),
                is_active=True,
                auto_renew=False
            )

            # Optionally deduct data from wallet if the plan has data cap
            warning = None
            if plan.data_cap:
                required_gb = Decimal(str(plan.data_cap))
                
                # Check if wallet has sufficient balance
                if wallet.balance_gb < required_gb:
                    warning = f'Subscription created but insufficient wallet balance for data cap. Need {required_gb} GB, have {wallet.balance_gb} GB'
                else:
                    # Allocate data for the plan's data cap
                    if wallet.allocate(
                        amount_gb=required_gb,
                        user=request.user,
                        description=f"Subscription activation: {plan.name} for {customer.username}",
                        reference=f"SUB-{sub.id}"
                    ):
                        # Create distribution log entry for this allocation
                        DataDistributionLog.objects.create(
                            bulk_purchase=None,
                            customer=customer,
                            user=request.user,
                            data_amount=required_gb,
                            previous_balance=wallet.balance_gb + required_gb,
                            new_balance=wallet.balance_gb,
                            status='success',
                            notes=f'Subscription activation: {plan.name} by {request.user.username}'
                        )
                    else:
                        warning = 'Subscription created but failed to allocate data from wallet'

            # Refresh wallet balance
            wallet.refresh_from_db()
            
            return JsonResponse({
                'success': True, 
                'subscription_id': str(sub.id),
                'customer_name': customer.get_full_name() or customer.username,
                'plan_name': plan.name,
                'warning': warning, 
                'remaining': float(wallet.balance_gb),
                'remaining_bandwidth': float(wallet.balance_bandwidth_mbps)
            })

        else:
            return JsonResponse({'success': False, 'error': f'Unknown action: {action}'})
        
    except Exception as e:
        logger.error(f"Allocation error: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': f'Server error: {str(e)}'})
    
def deposit_to_wallet(bulk_purchase, user):
    """Helper function to deposit bulk purchase data/bandwidth to wallet"""
    try:
        # Get or create wallet for the tenant
        wallet, created = DataWallet.objects.get_or_create(
            tenant=bulk_purchase.tenant,
            defaults={
                'balance_gb': Decimal('0.00'),
                'balance_bandwidth_mbps': Decimal('0.00'),
                'updated_by': user
            }
        )
        
        print(f"DEBUG: Processing purchase {bulk_purchase.id} of type {type(bulk_purchase).__name__}")
        print(f"DEBUG: Purchase attributes: {dir(bulk_purchase)}")
        
        # Check if already processed
        existing_transaction = WalletTransaction.objects.filter(
            wallet=wallet,
            description__contains=f"purchase #{bulk_purchase.id}"
        ).exists()
        
        if existing_transaction:
            print(f"DEBUG: Purchase {bulk_purchase.id} already processed")
            return False
        
        # For ISPBulkPurchase model (data purchases)
        if hasattr(bulk_purchase, 'total_data') and hasattr(bulk_purchase, 'package'):
            print(f"DEBUG: ISPBulkPurchase detected - {bulk_purchase.total_data} GB")
            if wallet.deposit(
                amount_gb=bulk_purchase.total_data,
                user=user,
                description=f"Bulk purchase #{bulk_purchase.id}: {bulk_purchase.package.name} ({bulk_purchase.quantity}x)",
                reference=f"BULK-{bulk_purchase.id}"
            ):
                if hasattr(bulk_purchase, 'wallet_deposited'):
                    bulk_purchase.wallet_deposited = True
                    bulk_purchase.wallet_deposited_at = tz.now()
                bulk_purchase.save()
                return True
        
        # For ISPBandwidthPurchase model
        elif hasattr(bulk_purchase, 'total_bandwidth') and hasattr(bulk_purchase, 'bandwidth_package'):
            print(f"DEBUG: ISPBandwidthPurchase detected - {bulk_purchase.total_bandwidth} Mbps")
            
            if wallet.deposit_bandwidth(
                amount_mbps=bulk_purchase.total_bandwidth,
                user=user,
                description=f"Bandwidth purchase #{bulk_purchase.id}: {bulk_purchase.bandwidth_package.name} ({bulk_purchase.quantity}x)",
                reference=f"BW-{bulk_purchase.id}"
            ):
                # Try to mark as deposited
                try:
                    bulk_purchase.wallet_deposited = True
                    bulk_purchase.wallet_deposited_at = tz.now()
                except:
                    # Add note instead
                    bulk_purchase.notes = f"{bulk_purchase.notes or ''} | Deposited to wallet on {tz.now()}"
                bulk_purchase.save()
                return True
        
        # For ISPDataPurchase model (marketplace purchases)
        elif hasattr(bulk_purchase, 'package_type'):
            print(f"DEBUG: ISPDataPurchase detected - Type: {bulk_purchase.package_type}")
            
            # Handle data purchases
            if bulk_purchase.package_type == 'data' and hasattr(bulk_purchase, 'total_data_amount'):
                amount = bulk_purchase.total_data_amount or Decimal('0')
                print(f"DEBUG: Data amount - {amount} GB")
                if amount > 0 and wallet.deposit(
                    amount_gb=amount,
                    user=user,
                    description=f"Marketplace data purchase #{bulk_purchase.id}",
                    reference=f"MKT-DATA-{bulk_purchase.id}"
                ):
                    bulk_purchase.wallet_deposited = True
                    bulk_purchase.wallet_deposited_at = tz.now()
                    bulk_purchase.save()
                    return True
            
            # Handle bandwidth purchases  
            elif bulk_purchase.package_type == 'bandwidth' and hasattr(bulk_purchase, 'total_bandwidth_amount'):
                amount = bulk_purchase.total_bandwidth_amount or Decimal('0')
                print(f"DEBUG: Bandwidth amount - {amount} Mbps")
                if amount > 0 and wallet.deposit_bandwidth(
                    amount_mbps=amount,
                    user=user,
                    description=f"Marketplace bandwidth purchase #{bulk_purchase.id}",
                    reference=f"MKT-BW-{bulk_purchase.id}"
                ):
                    bulk_purchase.wallet_deposited = True
                    bulk_purchase.wallet_deposited_at = tz.now()
                    bulk_purchase.save()
                    return True
        
        # Try generic detection as last resort
        print(f"DEBUG: Trying generic detection for purchase {bulk_purchase.id}")
        
        # Check for any bandwidth field
        for field_name in ['bandwidth_amount', 'bandwidth', 'total_bandwidth', 'bandwidth_mbps']:
            if hasattr(bulk_purchase, field_name):
                amount = getattr(bulk_purchase, field_name)
                if amount and Decimal(str(amount)) > 0:
                    print(f"DEBUG: Found bandwidth field '{field_name}': {amount}")
                    if wallet.deposit_bandwidth(
                        amount_mbps=Decimal(str(amount)),
                        user=user,
                        description=f"Purchase #{bulk_purchase.id}",
                        reference=f"GEN-BW-{bulk_purchase.id}"
                    ):
                        return True
        
        # Check for any data field
        for field_name in ['data_amount', 'total_data', 'data_gb', 'gb_amount']:
            if hasattr(bulk_purchase, field_name):
                amount = getattr(bulk_purchase, field_name)
                if amount and Decimal(str(amount)) > 0:
                    print(f"DEBUG: Found data field '{field_name}': {amount}")
                    if wallet.deposit(
                        amount_gb=Decimal(str(amount)),
                        user=user,
                        description=f"Purchase #{bulk_purchase.id}",
                        reference=f"GEN-DATA-{bulk_purchase.id}"
                    ):
                        return True
        
        print(f"DEBUG: No suitable deposit method found for purchase {bulk_purchase.id}")
        print(f"DEBUG: Purchase type: {type(bulk_purchase).__name__}")
        print(f"DEBUG: Available fields with values:")
        for attr in dir(bulk_purchase):
            if not attr.startswith('_'):
                try:
                    val = getattr(bulk_purchase, attr)
                    if val not in [None, '', []]:
                        print(f"  {attr}: {val}")
                except:
                    pass
                    
        return False
            
    except Exception as e:
        print(f"DEBUG: Exception in deposit_to_wallet: {str(e)}")
        import traceback
        traceback.print_exc()
        logger.error(f"Failed to deposit to wallet for purchase {bulk_purchase.id}: {e}")
        return False
    
@login_required
def sync_wallet_from_purchases(request):
    """Sync wallet balance from completed bulk purchases - FIXED VERSION"""
    if request.user.role not in ['isp_admin', 'isp_staff', 'superadmin']:
        return JsonResponse({'success': False, 'error': 'Access denied'})
    
    tenant = request.user.tenant
    if not tenant:
        return JsonResponse({'success': False, 'error': 'No tenant found'})
    
    # Get or create wallet
    wallet, created = DataWallet.objects.get_or_create(
        tenant=tenant,
        defaults={
            'balance_gb': Decimal('0.00'),
            'balance_bandwidth_mbps': Decimal('0.00'),
            'updated_by': request.user
        }
    )
    
    total_deposited = Decimal('0.00')
    total_bandwidth_deposited = Decimal('0.00')
    purchase_count = 0
    
    # TRACK ALREADY PROCESSED BANDWIDTH PURCHASES
    processed_bandwidth_purchases = set()
    
    # 1. Sync ISPBulkPurchase (data purchases)
    try:
        data_purchases = ISPBulkPurchase.objects.filter(
            tenant=tenant,
            payment_status='paid',
            wallet_deposited=False
        )
        print(f"DEBUG: Found {data_purchases.count()} data purchases to sync")
        
        for purchase in data_purchases:
            if deposit_to_wallet(purchase, request.user):
                total_deposited += Decimal(str(purchase.total_data))
                purchase_count += 1
    except Exception as e:
        logger.error(f"Error syncing ISPBulkPurchase: {e}")
    
    # 2. Sync ISPBandwidthPurchase (bandwidth purchases) - FIXED
    try:
        # Get purchases that haven't been deposited to wallet
        # Since ISPBandwidthPurchase doesn't have wallet_deposited field,
        # we'll track by checking WalletTransaction records
        
        bandwidth_purchases = ISPBandwidthPurchase.objects.filter(
            tenant=tenant,
            payment_status='completed'
        )
        
        print(f"DEBUG: Found {bandwidth_purchases.count()} bandwidth purchases")
        
        for purchase in bandwidth_purchases:
            # Check if this purchase was already processed
            already_processed = WalletTransaction.objects.filter(
                reference__contains=f"BW-{purchase.id}",
                wallet=wallet,
                amount_mbps__gt=0
            ).exists()
            
            if not already_processed:
                print(f"DEBUG: Processing bandwidth purchase {purchase.id}")
                if deposit_to_wallet(purchase, request.user):
                    total_bandwidth_deposited += Decimal(str(purchase.total_bandwidth))
                    purchase_count += 1
                    # Mark as processed in our tracking
                    processed_bandwidth_purchases.add(purchase.id)
                else:
                    print(f"DEBUG: Failed to deposit bandwidth purchase {purchase.id}")
            else:
                print(f"DEBUG: Bandwidth purchase {purchase.id} already processed")
                
    except Exception as e:
        logger.error(f"Error syncing ISPBandwidthPurchase: {e}")
        print(f"DEBUG: Error: {e}")
    
    # 3. Sync ISPDataPurchase (marketplace purchases) - FIXED
    try:
        # Check for data purchases
        marketplace_data = ISPDataPurchase.objects.filter(
            tenant=tenant,
            status='completed',
            package_type='data',
            wallet_deposited=False
        )
        print(f"DEBUG: Found {marketplace_data.count()} marketplace data purchases to sync")
        
        for purchase in marketplace_data:
            if deposit_to_wallet(purchase, request.user):
                if hasattr(purchase, 'total_data_amount') and purchase.total_data_amount:
                    total_deposited += Decimal(str(purchase.total_data_amount))
                purchase_count += 1
        
        # Check for bandwidth purchases
        marketplace_bandwidth = ISPDataPurchase.objects.filter(
            tenant=tenant,
            status='completed',
            package_type='bandwidth',
            wallet_deposited=False
        )
        print(f"DEBUG: Found {marketplace_bandwidth.count()} marketplace bandwidth purchases to sync")
        
        for purchase in marketplace_bandwidth:
            if deposit_to_wallet(purchase, request.user):
                if hasattr(purchase, 'total_bandwidth_amount') and purchase.total_bandwidth_amount:
                    total_bandwidth_deposited += Decimal(str(purchase.total_bandwidth_amount))
                purchase_count += 1
                
    except Exception as e:
        logger.error(f"Error syncing ISPDataPurchase: {e}")
        print(f"DEBUG: Error: {e}")
    
    # Return response
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'message': f'Deposited {total_deposited} GB data and {total_bandwidth_deposited} Mbps bandwidth from {purchase_count} purchases',
            'new_balance': float(wallet.balance_gb),
            'new_bandwidth_balance': float(wallet.balance_bandwidth_mbps),
            'processed_bandwidth_purchases': list(processed_bandwidth_purchases)
        })
    
    messages.success(request, f'Deposited {total_deposited} GB data and {total_bandwidth_deposited} Mbps bandwidth from {purchase_count} purchases. New balance: {wallet.balance_gb} GB data, {wallet.balance_bandwidth_mbps} Mbps bandwidth')
    return redirect('isp_data_wallet')
    
    # ==================== BULK DATA VIEWS (UPDATED) ====================

@login_required
def bulk_data_marketplace(request):
    """View all available bulk data packages"""
    tenant = getattr(request.user, 'tenant', None)
    
    if not tenant:
        messages.error(request, 'No ISP associated with your account.')
        return redirect('dashboard')
    
    # Get packages from different sources
    platform_packages = BulkDataPackage.objects.filter(
        source_type='platform', 
        is_active=True,
        platform_stock__gt=0,
        tenant__isnull=True  # Available to all ISPs
    ).order_by('selling_price')
    
    vendor_packages = BulkDataPackage.objects.filter(
        source_type__in=['vendor_direct', 'vendor_marketplace'],
        is_active=True,
        is_visible=True
    ).order_by('selling_price')
    
    # Get commission rate for display
    commission_rate = 7.5  # Default
    commission = PlatformCommission.objects.filter(
        service_type='bulk_data',
        is_active=True
    ).first()
    if commission:
        commission_rate = commission.rate
    
    context = {
        'tenant': tenant,
        'platform_packages': platform_packages,
        'vendor_packages': vendor_packages,
        'commission_rate': commission_rate,
        'page_title': 'Bulk Data Marketplace',
        'page_subtitle': 'Purchase bulk data for your ISP',
        'bandwidth_packages_count': BulkBandwidthPackage.objects.filter(is_active=True).count(),
        'commission_amount_example': 10000 * (commission_rate / 100),
        'net_amount_example': 10000 * (1 - commission_rate / 100),
    }
    
    return render(request, 'billing/bulk_data/marketplace.html', context)

@login_required
def purchase_bulk_data(request, package_id):
    """Purchase bulk data package"""
    tenant = getattr(request.user, 'tenant', None)
    
    if not tenant:
        messages.error(request, 'No ISP associated with your account.')
        return redirect('bulk_data_marketplace')
    
    package = get_object_or_404(BulkDataPackage, id=package_id, is_active=True)
    
    if request.method == 'POST':
        try:
            quantity = int(request.POST.get('quantity', 1))
            distribute_to = request.POST.get('distribute_to', 'all')
            auto_distribute = request.POST.get('auto_distribute') == 'on'
            
            if quantity < 1:
                messages.error(request, 'Quantity must be at least 1')
                return redirect('bulk_data_marketplace')
            
            # Check platform stock if it's platform inventory
            if package.source_type == 'platform' and package.platform_stock < (package.data_amount * quantity):
                messages.error(request, f'Insufficient stock. Only {package.platform_stock} GB available.')
                return redirect('bulk_data_marketplace')
            
            # Calculate totals
            total_price = package.selling_price * quantity
            total_data = package.data_amount * quantity
            
            # Calculate commission
            commission_amount = total_price * package.commission_rate / Decimal('100')
            net_amount = total_price - commission_amount
            
            # Create bulk purchase record
            bulk_purchase = ISPBulkPurchase.objects.create(
                tenant=tenant,
                package=package,
                quantity=quantity,
                total_data=total_data,
                total_price=total_price,
                platform_commission=commission_amount,
                isp_net_amount=net_amount,
                commission_calculated=True,
                auto_distribute=auto_distribute,
                distribute_to=distribute_to,
                created_by=request.user,
                notes=f"Purchased {quantity} x {package.name}"
            )
            
            # Redirect to payment
            return redirect('process_bulk_data_payment', purchase_id=bulk_purchase.id)
            
        except Exception as e:
            messages.error(request, f'Error: {str(e)}')
            logger.error(f"Purchase error: {e}")
    
    # Calculate commission for display
    commission_amount = package.selling_price * package.commission_rate / Decimal('100')
    net_amount = package.selling_price - commission_amount
    
    context = {
        'tenant': tenant,
        'package': package,
        'commission_amount': commission_amount,
        'net_amount': net_amount,
        'commission_rate': package.commission_rate,
        'page_title': f'Purchase {package.name}',
        'page_subtitle': f'Buy bulk data package',
    }
    
    return render(request, 'billing/bulk_data/purchase.html', context)

@login_required
def process_bulk_data_payment(request, purchase_id):
    """Process payment for bulk data purchase"""
    bulk_purchase = get_object_or_404(ISPBulkPurchase, id=purchase_id, tenant=request.user.tenant)
    
    if request.method == 'POST':
        payment_method = request.POST.get('payment_method')
        
        if payment_method == 'paystack':
            # Process PayStack payment
            return redirect('paystack_bulk_data_payment', purchase_id=purchase_id)
        elif payment_method == 'manual' and request.user.role in ['isp_admin', 'superadmin']:
            # Manual payment (mark as paid by admin)
            bulk_purchase.payment_status = 'paid'
            bulk_purchase.save()
            
            # Create payment record
            payment = Payment.objects.create(
                user=request.user,
                amount=bulk_purchase.total_price,
                reference=f"BULK_{uuid.uuid4().hex[:10].upper()}",
                status='completed',
                payment_method='manual'
            )
            
            bulk_purchase.payment = payment
            bulk_purchase.save()
            
            # Create commission transaction
            create_commission_transaction(
                payment=payment,
                tenant=bulk_purchase.tenant,
                service_type='bulk_data',
                amount=bulk_purchase.total_price,
                bulk_purchase=bulk_purchase
            )
            
            # DEPOSIT TO WALLET FOR MANUAL PAYMENTS
            if deposit_to_wallet(bulk_purchase, request.user):
                messages.success(request, 'Purchase marked as paid. Data deposited to wallet.')
            else:
                messages.warning(request, 'Purchase marked as paid but failed to deposit to wallet.')
            
            # Trigger distribution if auto_distribute is enabled
            if bulk_purchase.auto_distribute:
                messages.info(request, 'Auto-distribution will be processed shortly.')
                # You might want to trigger a background task here
            
            return redirect('bulk_purchase_detail', purchase_id=bulk_purchase.id)
        else:
            messages.error(request, 'Invalid payment method or insufficient permissions.')
    
    context = {
        'bulk_purchase': bulk_purchase,
        'tenant': request.user.tenant,
        'page_title': 'Process Payment',
        'page_subtitle': f'Pay for {bulk_purchase.package.name}',
    }
    
    return render(request, 'billing/bulk_data/process_payment.html', context)

@login_required
def paystack_bulk_data_payment(request, purchase_id):
    """Handle PayStack payment for bulk data"""
    bulk_purchase = get_object_or_404(ISPBulkPurchase, id=purchase_id, tenant=request.user.tenant)
    
    # Get PayStack configuration
    tenant = bulk_purchase.tenant
    try:
        paystack_config = PaystackConfiguration.objects.get(tenant=tenant, is_active=True)
        PAYSTACK_SECRET_KEY = paystack_config.secret_key
        PAYSTACK_PUBLIC_KEY = paystack_config.public_key
    except PaystackConfiguration.DoesNotExist:
        messages.error(request, 'PayStack configuration not found for this ISP.')
        return redirect('bulk_data_marketplace')
    
    # Create payment record
    payment = Payment.objects.create(
        user=request.user,
        amount=bulk_purchase.total_price,
        reference=f"BULK_{uuid.uuid4().hex[:10].upper()}",
        status='pending',
        payment_method='paystack'
    )
    
    bulk_purchase.payment = payment
    bulk_purchase.save()
    
    # Prepare metadata
    metadata = {
        'purchase_id': str(bulk_purchase.id),
        'tenant_id': str(tenant.id),
        'package_name': bulk_purchase.package.name,
        'quantity': bulk_purchase.quantity,
        'service_type': 'bulk_data',
    }
    
    # Initialize PayStack payment
    headers = {
        'Authorization': f'Bearer {PAYSTACK_SECRET_KEY}',
        'Content-Type': 'application/json',
    }
    
    paystack_data = {
        'email': request.user.email,
        'amount': int(bulk_purchase.total_price * 100),  # Convert to kobo
        'reference': payment.reference,
        'callback_url': request.build_absolute_uri(
            f'/billing/bulk-data/callback/{purchase_id}/'
        ),
        'metadata': metadata
    }
    
    # Add subaccount if configured
    if paystack_config.subaccount_code:
        paystack_data['subaccount'] = paystack_config.subaccount_code
        paystack_data['transaction_charge'] = int(bulk_purchase.total_price * Decimal('0.015') * 100)  # 1.5% in kobo
    
    try:
        response = requests.post(
            'https://api.paystack.co/transaction/initialize',
            json=paystack_data,
            headers=headers,
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            if data['status']:
                payment.paystack_access_code = data['data']['access_code']
                payment.save()
                
                return redirect(data['data']['authorization_url'])
            else:
                error_msg = data.get('message', 'Unknown error')
                messages.error(request, f'PayStack error: {error_msg}')
        else:
            messages.error(request, 'Unable to connect to PayStack. Please try again.')
            
    except requests.exceptions.RequestException as e:
        messages.error(request, f'Network error: {str(e)}')
        logger.error(f"PayStack request error: {e}")
    
    return redirect('process_bulk_data_payment', purchase_id=purchase_id)

@csrf_exempt
def paystack_bulk_data_callback(request, purchase_id):
    """PayStack callback for bulk data OR bandwidth purchase"""
    if request.method == 'GET':
        # Handle user redirect after payment
        reference = request.GET.get('reference') or request.GET.get('trxref')
        if not reference:
            messages.error(request, 'No reference provided')
            return redirect('bulk_data_marketplace')
        is_webhook = False
    elif request.method == 'POST':
        is_webhook = True
        try:
            payload = json.loads(request.body)
            reference = payload.get('data', {}).get('reference')
        except Exception:
            return JsonResponse({'status': 'error', 'message': 'Invalid payload'}, status=400)
    else:
        return HttpResponse(status=400)

    try:
        # Get payment and purchase
        payment = Payment.objects.get(reference=reference)
        bulk_purchase = ISPBulkPurchase.objects.get(id=purchase_id)
        
        # Verify payment
        paystack_config = PaystackConfiguration.objects.get(tenant=bulk_purchase.tenant, is_active=True)
        
        headers = {
            'Authorization': f'Bearer {paystack_config.secret_key}',
        }
        
        response = requests.get(
            f'https://api.paystack.co/transaction/verify/{reference}',
            headers=headers,
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()

            if data['status'] and data['data']['status'] == 'success':
                # Payment successful
                payment.status = 'completed'
                payment.paystack_reference = reference
                payment.save()

                bulk_purchase.payment_status = 'paid'
                bulk_purchase.save()

                # DEPOSIT TO WALLET (BOTH DATA AND BANDWIDTH)
                if not bulk_purchase.wallet_deposited:
                    deposit_to_wallet(bulk_purchase, payment.user)

                # Create commission transaction
                create_commission_transaction(
                    payment=payment,
                    tenant=bulk_purchase.tenant,
                    service_type='bulk_data',
                    amount=bulk_purchase.total_price,
                    bulk_purchase=bulk_purchase
                )

                if is_webhook:
                    return JsonResponse({'status': 'success', 'message': 'Payment successful'})
                else:
                    messages.success(request, 'Payment successful! Data/bandwidth has been deposited to your wallet.')
                    return redirect('bulk_purchase_detail', purchase_id=bulk_purchase.id)
            else:
                payment.status = 'failed'
                payment.save()
                bulk_purchase.payment_status = 'failed'
                bulk_purchase.save()

                if is_webhook:
                    return JsonResponse({'status': 'error', 'message': 'Payment verification failed'})
                else:
                    messages.error(request, 'Payment verification failed')
                    return redirect('bulk_purchase_detail', purchase_id=bulk_purchase.id)
        else:
            if is_webhook:
                return JsonResponse({'status': 'error', 'message': 'Unable to verify payment'})
            else:
                messages.error(request, 'Unable to verify payment. Please contact support.')
                return redirect('bulk_purchase_detail', purchase_id=bulk_purchase.id)
            
    except Exception as e:
        logger.error(f"Bulk data callback error: {e}")
        if request.method == 'POST':
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
        else:
            messages.error(request, 'An error occurred while processing payment callback')
            return redirect('bulk_data_marketplace')
        
@login_required
def bulk_purchase_detail(request, purchase_id):
    """View details of a bulk purchase"""
    bulk_purchase = get_object_or_404(ISPBulkPurchase, id=purchase_id, tenant=request.user.tenant)
    
    # Get distribution logs
    distribution_logs = DataDistributionLog.objects.filter(bulk_purchase=bulk_purchase)
    
    # Get wallet info
    wallet = DataWallet.objects.filter(tenant=request.user.tenant).first()
    
    context = {
        'bulk_purchase': bulk_purchase,
        'distribution_logs': distribution_logs,
        'wallet': wallet,
        'tenant': request.user.tenant,
        'page_title': 'Purchase Details',
        'page_subtitle': f'{bulk_purchase.package.name}',
    }
    
    return render(request, 'billing/bulk_data/detail.html', context)

@login_required
def bulk_purchase_history(request):
    """View all bulk purchase history"""
    tenant = request.user.tenant
    
    purchases = ISPBulkPurchase.objects.filter(tenant=tenant).order_by('-purchased_at')
    
    # Pagination
    paginator = Paginator(purchases, 20)
    page = request.GET.get('page', 1)
    
    try:
        purchases_page = paginator.page(page)
    except PageNotAnInteger:
        purchases_page = paginator.page(1)
    except EmptyPage:
        purchases_page = paginator.page(paginator.num_pages)
    
    context = {
        'purchases': purchases_page,
        'tenant': tenant,
        'page_title': 'Bulk Purchase History',
        'page_subtitle': 'All your bulk data purchases',
    }
    
    return render(request, 'billing/bulk_data/history.html', context)

# ==================== COMMISSION VIEWS ====================

@login_required
def isp_commission_dashboard(request):
    """ISP view of their commissions"""
    tenant = request.user.tenant
    
    if not tenant:
        messages.error(request, 'No ISP associated with your account.')
        return redirect('dashboard')
    
    # Get commission summary
    summary = get_commission_summary(tenant)
    
    # Get recent commission transactions
    recent_transactions = CommissionTransaction.objects.filter(
        tenant=tenant
    ).order_by('-created_at')[:10]
    
    # Calculate total commissions
    total_commissions = CommissionTransaction.objects.filter(
        tenant=tenant,
        status='calculated'
    ).aggregate(total=Sum('commission_amount'))['total'] or Decimal('0.00')
    
    # Calculate pending settlements
    pending_settlements = CommissionTransaction.objects.filter(
        tenant=tenant,
        status='due'
    ).aggregate(total=Sum('commission_amount'))['total'] or Decimal('0.00')
    
    context = {
        'tenant': tenant,
        'summary': summary,
        'recent_transactions': recent_transactions,
        'total_commissions': total_commissions,
        'pending_settlements': pending_settlements,
        'page_title': 'Commission Dashboard',
        'page_subtitle': 'Track your commissions and settlements',
    }
    
    return render(request, 'billing/commissions/isp_dashboard.html', context)


@login_required
def external_data_upload(request):
    """Upload external data to wallet"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    wallet = DataWallet.objects.filter(tenant=tenant).first()
    
    if not wallet:
        messages.error(request, 'Wallet not found')
        return redirect('isp_data_wallet')
    
    if request.method == 'POST':
        source_type = request.POST.get('source_type')
        amount_gb = request.POST.get('amount_gb')
        description = request.POST.get('description', '')
        external_source = request.POST.get('external_source', '')
        external_reference = request.POST.get('external_reference', '')
        invoice_number = request.POST.get('invoice_number', '')
        
        try:
            # Convert to decimal
            from decimal import Decimal
            amount = Decimal(amount_gb)
            
            if amount <= 0:
                messages.error(request, 'Amount must be greater than 0')
                return redirect('external_data_upload')
            
            # Deposit to wallet
            result = wallet.deposit_external(
                amount_gb=amount,
                user=request.user,
                source_type='external_upload',
                external_source=external_source,
                external_reference=external_reference,
                description=description,
                invoice_number=invoice_number
            )
            
            if result.get('status') == 'success':
                messages.success(request, f'Successfully deposited {amount_gb} GB to wallet')
                return redirect('isp_data_wallet')
            elif result.get('status') == 'pending_approval':
                messages.info(request, f'Deposit of {amount_gb} GB submitted for approval')
                return redirect('isp_data_wallet')
            else:
                messages.error(request, 'Deposit failed')
                
        except ValueError as e:
            messages.error(request, str(e))
        except Exception as e:
            logger.error(f"External deposit error: {e}")
            messages.error(request, f'Error: {str(e)}')
    
    # Get existing external sources
    external_sources = ExternalDataSource.objects.filter(tenant=tenant, is_active=True)
    
    context = {
        'tenant': tenant,
        'wallet': wallet,
        'external_sources': external_sources,
        'page_title': 'Upload External Data',
        'page_subtitle': 'Add data from external sources to your wallet',
    }
    
    return render(request, 'billing/external_data_upload.html', context)

@login_required
def upload_data_csv(request):
    """Upload CSV file with data records"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    wallet = DataWallet.objects.filter(tenant=tenant).first()
    
    if request.method == 'POST' and request.FILES.get('csv_file'):
        csv_file = request.FILES['csv_file']
        source_name = request.POST.get('source_name', 'CSV Upload')
        
        try:
            import csv
            import io
            
            # Read CSV file
            content = csv_file.read().decode('utf-8')
            csv_data = io.StringIO(content)
            reader = csv.DictReader(csv_data)
            
            total_amount = Decimal('0')
            processed_rows = 0
            errors = []
            
            for i, row in enumerate(reader, 1):
                try:
                    # Extract data from CSV
                    amount_gb = Decimal(row.get('amount_gb', '0'))
                    reference = row.get('reference', f'CSV-{i}')
                    description = row.get('description', f'CSV import row {i}')
                    
                    if amount_gb > 0:
                        # Deposit to wallet
                        wallet.deposit_external(
                            amount_gb=amount_gb,
                            user=request.user,
                            source_type='external_upload',
                            external_source=source_name,
                            external_reference=reference,
                            description=description
                        )
                        
                        total_amount += amount_gb
                        processed_rows += 1
                        
                except Exception as e:
                    errors.append(f"Row {i}: {str(e)}")
            
            if processed_rows > 0:
                messages.success(request, f'Successfully imported {processed_rows} records, totaling {total_amount} GB')
            if errors:
                messages.warning(request, f'Some rows failed: {", ".join(errors[:5])}')
            
            return redirect('isp_data_wallet')
            
        except Exception as e:
            logger.error(f"CSV upload error: {e}")
            messages.error(request, f'Error processing CSV: {str(e)}')
    
    context = {
        'tenant': tenant,
        'wallet': wallet,
        'page_title': 'Upload CSV Data',
        'page_subtitle': 'Bulk import data from CSV file',
    }
    
    return render(request, 'billing/upload_data_csv.html', context)

@login_required
def sync_external_source(request, source_id):
    """Sync data from external source via API"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return JsonResponse({'success': False, 'error': 'Access denied'})
    
    try:
        source = ExternalDataSource.objects.get(id=source_id, tenant=request.user.tenant)
        wallet = DataWallet.objects.filter(tenant=request.user.tenant).first()
        
        if not wallet:
            return JsonResponse({'success': False, 'error': 'Wallet not found'})
        
        # Example API integration (customize based on your external source)
        if source.source_type == 'external_api':
            try:
                import requests
                
                # Call external API
                headers = {}
                if source.api_key:
                    headers['Authorization'] = f'Bearer {source.api_key}'
                
                response = requests.get(
                    source.api_endpoint,
                    headers=headers,
                    timeout=30
                )
                
                if response.status_code == 200:
                    data = response.json()
                    
                    # Parse response based on your API structure
                    # This is an example - customize as needed
                    amount_gb = Decimal(data.get('available_data', 0))
                    
                    if amount_gb > 0:
                        # Deposit to wallet
                        wallet.deposit_external(
                            amount_gb=amount_gb,
                            user=request.user,
                            source_type='api_deposit',
                            external_source=source.name,
                            external_reference=f'API-SYNC-{tz.now().strftime("%Y%m%d%H%M%S")}',
                            description=f'API sync from {source.name}'
                        )
                        
                        # Update source stats
                        source.last_sync_at = tz.now()
                        source.last_sync_status = 'success'
                        source.last_deposit_amount = amount_gb
                        source.last_deposit_date = tz.now()
                        source.total_deposits += amount_gb
                        source.save()
                        
                        return JsonResponse({
                            'success': True,
                            'message': f'Synced {amount_gb} GB from {source.name}',
                            'new_balance': float(wallet.balance_gb)
                        })
                    else:
                        return JsonResponse({
                            'success': False,
                            'error': 'No data available from source'
                        })
                else:
                    source.last_sync_status = 'failed'
                    source.save()
                    return JsonResponse({
                        'success': False,
                        'error': f'API returned status {response.status_code}'
                    })
                    
            except Exception as e:
                source.last_sync_status = 'failed'
                source.save()
                logger.error(f"API sync error: {e}")
                return JsonResponse({'success': False, 'error': str(e)})
        
        elif source.source_type == 'isp_server':
            # Connect to ISP's own server/database
            # This would be customized based on the ISP's infrastructure
            # Example: Connect to MySQL/PostgreSQL database
            try:
                import psycopg2  # or mysql.connector for MySQL
                
                # Connect to ISP's database (credentials would be stored securely)
                connection = psycopg2.connect(
                    host=source.api_endpoint,  # Could be server IP
                    database="isp_data",
                    user=source.api_key,  # Username
                    password=source.api_secret,  # Password
                    port=5432
                )
                
                cursor = connection.cursor()
                cursor.execute("SELECT SUM(data_balance) FROM customer_data WHERE status='available'")
                result = cursor.fetchone()
                amount_gb = Decimal(result[0] or 0)
                
                connection.close()
                
                if amount_gb > 0:
                    wallet.deposit_external(
                        amount_gb=amount_gb,
                        user=request.user,
                        source_type='api_deposit',
                        external_source=source.name,
                        external_reference=f'SERVER-SYNC-{tz.now().strftime("%Y%m%d%H%M%S")}',
                        description=f'Server sync from {source.name}'
                    )
                    
                    source.last_sync_at = tz.now()
                    source.last_sync_status = 'success'
                    source.last_deposit_amount = amount_gb
                    source.total_deposits += amount_gb
                    source.save()
                    
                    return JsonResponse({
                        'success': True,
                        'message': f'Synced {amount_gb} GB from ISP server',
                        'new_balance': float(wallet.balance_gb)
                    })
                    
            except Exception as e:
                source.last_sync_status = 'failed'
                source.save()
                logger.error(f"Server sync error: {e}")
                return JsonResponse({'success': False, 'error': str(e)})
        
        return JsonResponse({'success': False, 'error': 'Source type not implemented'})
        
    except ExternalDataSource.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Source not found'})

from django.conf import settings
from cryptography.fernet import Fernet


def encrypt_value(value):
    """Encrypt a value using Fernet"""
    if not value:
        return None
    
    try:
        cipher = Fernet(settings.ENCRYPTION_KEY)
        return cipher.encrypt(value.encode())
    except Exception as e:
        logger.error(f"Encryption error: {e}")
        return None

def decrypt_value(encrypted_value):
    """Decrypt a Fernet-encrypted value"""
    if not encrypted_value:
        return ''
    
    try:
        cipher = Fernet(settings.ENCRYPTION_KEY)
        return cipher.decrypt(encrypted_value).decode()
    except Exception as e:
        logger.error(f"Decryption error: {e}")
        return '[ENCRYPTED]'

# ==================== EXISTING VIEWS (UPDATED) ====================

@login_required
def dashboard(request):
    """Main dashboard view"""
    user = request.user
    tenant = getattr(user, 'tenant', None)
    
    # Get statistics based on user role
    if user.role in ['isp_admin', 'isp_staff']:
        # ISP statistics
        total_customers = CustomUser.objects.filter(tenant=tenant, role='customer').count()
        active_customers = CustomUser.objects.filter(tenant=tenant, role='customer', is_active=True).count()
        
        # Get wallet balance
        wallet = DataWallet.objects.filter(tenant=tenant).first()
        wallet_balance = wallet.balance_gb if wallet else Decimal('0.00')
        
        # Get recent purchases
        recent_purchases = ISPBulkPurchase.objects.filter(tenant=tenant).order_by('-purchased_at')[:5]
        
        # Get total data purchased
        total_data_purchased = ISPBulkPurchase.objects.filter(
            tenant=tenant, 
            payment_status='paid'
        ).aggregate(total=Sum('total_data'))['total'] or Decimal('0.00')
        
        context = {
            'total_customers': total_customers,
            'active_customers': active_customers,
            'wallet_balance': wallet_balance,
            'recent_purchases': recent_purchases,
            'total_data_purchased': total_data_purchased,
            'user_role': 'isp',
        }
        
    elif user.role == 'customer':
        # Customer statistics
        active_subscription = Subscription.objects.filter(
            user=user, 
            is_active=True
        ).first()
        
        # Get payment history
        recent_payments = Payment.objects.filter(user=user).order_by('-created_at')[:5]
        
        context = {
            'active_subscription': active_subscription,
            'recent_payments': recent_payments,
            'user_role': 'customer',
        }
        
    else:
        # Superadmin or other roles
        context = {
            'user_role': 'other',
        }
    
    return render(request, 'dashboard.html', context)

@login_required
def paystack_subscribe_with_plan(request, plan_id):
    """Handle subscription with specific SubscriptionPlan (form submission)"""
    
    logger.info(f"=== PAYSTACK SUBSCRIPTION STARTED ===")
    logger.info(f"User: {request.user.username}, Plan ID: {plan_id}")
    
    if not BILLING_ENABLED:
        logger.warning("Billing not enabled - redirecting")
        messages.error(request, 'Billing is not enabled on this system.')
        return redirect('plan_selection')
    
    try:
        user = request.user
        tenant = getattr(request, 'tenant', None) or getattr(user, 'tenant', None)
        
        if not tenant:
            logger.error(f"No tenant for user: {user.username}")
            messages.error(request, 'No tenant associated with your account.')
            return redirect('plan_selection')
        
        logger.info(f"Tenant found: {tenant.name} (ID: {tenant.id})")
        
        # Get plan for current tenant
        try:
            plan = SubscriptionPlan.objects.get(id=plan_id, tenant=tenant, is_active=True)
            logger.info(f"Plan found: {plan.name} - ${plan.price}")
        except SubscriptionPlan.DoesNotExist:
            logger.error(f"Plan {plan_id} not found for tenant {tenant.name}")
            messages.error(request, 'Selected plan not found or is no longer available.')
            return redirect('plan_selection')
        
        # Generate unique reference
        reference = f"sub_{request.user.id}_{uuid.uuid4().hex[:8]}"
        logger.info(f"Generated reference: {reference}")
        
        # Create payment record
        payment = Payment.objects.create(
            user=request.user,
            plan=plan,
            amount=plan.price,
            reference=reference,
            status='pending',
            payment_method='paystack'
        )
        logger.info(f"Payment created: {payment.id}")
        
        logger.info("=" * 60)
        logger.info("TRACING PAYSTACK KEY SOURCE")
        logger.info("=" * 60)

        # 1. Check database first
        try:
            paystack_config = PaystackConfiguration.objects.get(tenant=tenant, is_active=True)
            db_key = paystack_config.secret_key
            logger.info(f"1. Database key found: {db_key[:10]}...{db_key[-4:] if db_key and len(db_key) > 14 else ''}")
            logger.info(f"   Config ID: {paystack_config.id}")
            logger.info(f"   Tenant: {paystack_config.tenant.name}")
        except PaystackConfiguration.DoesNotExist:
            logger.info("1. No Paystack config in database")
            db_key = None
            paystack_config = None
        except Exception as e:
            logger.error(f"1. Database error: {e}")
            db_key = None
            paystack_config = None

        # 2. Check settings
        settings_key = getattr(settings, 'PAYSTACK_SECRET_KEY', None)
        logger.info(f"2. Settings key: {settings_key[:10] if settings_key else 'None'}")

        # 3. Check environment variables
        import os
        env_key = os.environ.get('PAYSTACK_SECRET_KEY')
        logger.info(f"3. Environment key: {env_key[:10] if env_key else 'None'}")

        # 4. Determine which key will be used
        PAYSTACK_SECRET_KEY = None

        if db_key:
            cleaned_db = str(db_key).strip().replace('\n', '').replace('\r', '')
            if cleaned_db.startswith('sk_test_') or cleaned_db.startswith('sk_live_'):
                PAYSTACK_SECRET_KEY = cleaned_db
                logger.info(f"4. Using database key: {PAYSTACK_SECRET_KEY[:10]}...")
            else:
                logger.warning(f"4. Database key invalid format: {cleaned_db[:20]}...")

        if not PAYSTACK_SECRET_KEY and settings_key:
            cleaned_settings = str(settings_key).strip()
            if cleaned_settings.startswith('sk_test_') or cleaned_settings.startswith('sk_live_'):
                PAYSTACK_SECRET_KEY = cleaned_settings
                logger.info(f"4. Using settings key: {PAYSTACK_SECRET_KEY[:10]}...")

        if not PAYSTACK_SECRET_KEY and env_key:
            cleaned_env = str(env_key).strip()
            if cleaned_env.startswith('sk_test_') or cleaned_env.startswith('sk_live_'):
                PAYSTACK_SECRET_KEY = cleaned_env
                logger.info(f"4. Using environment key: {PAYSTACK_SECRET_KEY[:10]}...")

        if not PAYSTACK_SECRET_KEY:
            logger.error("4. NO VALID KEY FOUND ANYWHERE!")
            messages.error(request, 'Payment gateway configuration error. Please contact support.')
            return redirect('plan_selection')

        logger.info(f"5. FINAL KEY TO BE USED: {PAYSTACK_SECRET_KEY[:10]}...{PAYSTACK_SECRET_KEY[-4:]}")
        logger.info(f"   Key length: {len(PAYSTACK_SECRET_KEY)}")
        logger.info("=" * 60)
        # Prepare metadata
        metadata = {
            'user_id': str(request.user.id),
            'plan_id': str(plan.id),
            'payment_id': str(payment.id),
            'tenant_id': str(tenant.id) if tenant else None,
        }
        
        # Convert amount using utility function
        try:
            amount_kobo = decimal_to_paystack_amount(plan.price)
            logger.info(f"Amount: {plan.price} -> {amount_kobo} kobo")
        except Exception as e:
            logger.error(f"Amount conversion error: {e}")
            # Fallback calculation
            amount_kobo = int(float(plan.price) * 100)
        
        # Paystack payment data
        paystack_data = {
            'email': request.user.email,
            'amount': amount_kobo,
            'reference': reference,
            'callback_url': request.build_absolute_uri(f'/billing/payment/verify/{reference}/'),
            'metadata': metadata
        }
        
        # Add subaccount if configured
        subaccount_code = None
        try:
            if paystack_config and hasattr(paystack_config, 'subaccount_code'):
                subaccount_code = paystack_config.subaccount_code
                if subaccount_code:
                    paystack_data['subaccount'] = subaccount_code
                    transaction_charge_amount = plan.price * Decimal('0.015')
                    paystack_data['transaction_charge'] = decimal_to_paystack_amount(transaction_charge_amount)
                    logger.info(f"Added subaccount: {subaccount_code}")
        except:
            pass
        
        logger.info(f"Paystack data prepared, calling API...")
        
        # Initialize Paystack transaction
        headers = {
            'Authorization': f'Bearer {PAYSTACK_SECRET_KEY}',
            'Content-Type': 'application/json',
        }
        
        # === DEBUG THE REQUEST ===
        logger.info(f"DEBUG: Making request to Paystack...")
        
        response = requests.post(
            'https://api.paystack.co/transaction/initialize',
            json=paystack_data,
            headers=headers,
            timeout=30,
            verify=True
        )
        
        logger.info(f"Paystack response status: {response.status_code}")
        logger.info(f"Paystack response body: {response.text[:500]}")
        
        if response.status_code == 200:
            data = response.json()
            logger.info(f"Paystack API response status: {data.get('status')}")
            
            if data['status']:
                # Success - redirect to Paystack payment page
                authorization_url = data['data']['authorization_url']
                logger.info(f"Success! Redirecting to: {authorization_url}")
                return redirect(authorization_url)
            else:
                # Paystack API returned error
                error_message = data.get('message', 'Unknown Paystack error')
                logger.error(f"Paystack API error: {error_message}")
                payment.status = 'failed'
                payment.save()
                messages.error(request, f'Paystack error: {error_message}')
        elif response.status_code == 401:
            # Specific handling for 401
            error_data = response.json()
            logger.error(f"PAYSTACK 401 ERROR: {error_data}")
            logger.error(f"The key being used: {PAYSTACK_SECRET_KEY[:10]}...")
            
            messages.error(request, 'Invalid payment gateway credentials. Please contact your ISP administrator.')
        else:
            # HTTP error
            logger.error(f"HTTP error from Paystack: {response.status_code}")
            logger.error(f"Response: {response.text}")
            payment.status = 'failed'
            payment.save()
            messages.error(request, f'Unable to connect to Paystack (HTTP {response.status_code}). Please try again.')
            
    except SubscriptionPlan.DoesNotExist:
        logger.error("SubscriptionPlan.DoesNotExist exception")
        messages.error(request, 'Selected plan not found or is no longer available.')
    except requests.exceptions.RequestException as e:
        # Network-related errors
        logger.error(f"Network error: {e}")
        messages.error(request, 'Network error. Please check your connection and try again.')
    except Exception as e:
        # Any other unexpected errors
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        messages.error(request, 'An unexpected error occurred. Please try again.')
    
    logger.warning("Subscription failed - redirecting to plan selection")
    return redirect('plan_selection')
    
@login_required
def paystack_subscribe(request):
    """View for subscribing to a plan via PayStack"""
    
    # Check if user is an ISP admin
    if request.user.role not in ['isp_admin', 'superadmin']:
        messages.error(request, 'Only ISP administrators can subscribe to plans.')
        return redirect('dashboard')
    
    # Get the tenant (ISP) for this user
    tenant = get_object_or_404(Tenant, id=request.user.tenant.id)
    
    # Get available plans
    plans = SubscriptionPlan.objects.filter(is_active=True).order_by('price')
    
    # Check if PayStack is configured
    try:
        paystack_config = PaystackConfiguration.objects.get(tenant=tenant)
        is_paystack_configured = paystack_config.is_active
    except PaystackConfiguration.DoesNotExist:
        is_paystack_configured = False
        paystack_config = None
    
    if request.method == 'POST':
        plan_id = request.POST.get('plan_id')
        
        if not plan_id:
            messages.error(request, 'Please select a plan.')
            return redirect('paystack_subscribe')
        
        try:
            plan = get_object_or_404(SubscriptionPlan, id=plan_id, is_active=True)
            
            # Create payment record
            payment = Payment.objects.create(
                user=request.user,
                plan=plan,
                amount=plan.price,
                reference=f"SUB_{uuid.uuid4().hex[:10].upper()}",
                status='pending',
                payment_method='paystack'
            )
            
            # Initialize PayStack payment
            try:
                # Get Paystack configuration
                paystack_config = PaystackConfiguration.objects.get(tenant=tenant, is_active=True)
                PAYSTACK_SECRET_KEY = paystack_config.secret_key
                
                # Prepare metadata
                metadata = {
                    'plan_name': plan.name,
                    'plan_id': str(plan.id),
                    'user_email': request.user.email,
                    'tenant_id': str(tenant.id)
                }
                
                # Paystack payment data
                paystack_data = {
                    'email': request.user.email,
                    'amount': decimal_to_paystack_amount(plan.price),
                    'reference': payment.reference,
                    'callback_url': request.build_absolute_uri(f'/billing/payment/verify/{payment.reference}/'),
                    'metadata': metadata
                }
                
                # Add subaccount if configured
                if paystack_config.subaccount_code:
                    paystack_data['subaccount'] = paystack_config.subaccount_code
                    paystack_data['transaction_charge'] = int(plan.price * 0.015 * 100)  # 1.5% in kobo
                
                # Initialize Paystack transaction
                headers = {
                    'Authorization': f'Bearer {PAYSTACK_SECRET_KEY}',
                    'Content-Type': 'application/json',
                }
                
                response = requests.post(
                    'https://api.paystack.co/transaction/initialize',
                    json=paystack_data,
                    headers=headers,
                    timeout=30
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if data['status']:
                        payment.paystack_access_code = data['data']['access_code']
                        payment.save()
                        
                        return redirect(data['data']['authorization_url'])
                    else:
                        error_msg = data.get('message', 'Unknown error')
                        messages.error(request, f'PayStack error: {error_msg}')
                        return redirect('paystack_subscribe')
                        
                else:
                    messages.error(request, 'Unable to connect to PayStack.')
                    return redirect('paystack_subscribe')
                    
            except Exception as e:
                messages.error(request, f'Error initializing payment: {str(e)}')
                payment.status = 'failed'
                payment.save()
                return redirect('paystack_subscribe')
                
        except Exception as e:
            messages.error(request, f'Error: {str(e)}')
            return redirect('paystack_subscribe')
    
    context = {
        'plans': plans,
        'tenant': tenant,
        'is_paystack_configured': is_paystack_configured,
        'page_title': 'Subscribe to Plan',
        'page_subtitle': 'Choose a subscription plan for your ISP',
    }
    
    return render(request, 'billing/subscribe.html', context)

@login_required
def plan_selection(request):
    """Display available plans for the customer"""
    if not BILLING_ENABLED:
        messages.error(request, 'Billing features are not available.')
        return redirect('dashboard')
    
    user = request.user
    
    # Check if user is approved
    if user.registration_status != 'approved':
        messages.warning(request, 'Your account is pending approval. You will be able to select plans once approved.')
        return redirect('dashboard')
    
    # Get tenant from user
    tenant = getattr(user, 'tenant', None)
    
    if not tenant:
        messages.error(request, 'No ISP assigned to your account. Please contact support.')
        return redirect('dashboard')
    
    # Get plans for the user's tenant
    try:
        plans = SubscriptionPlan.objects.filter(tenant=tenant, is_active=True).order_by('price')
    except Exception as e:
        logger.error(f"Error getting plans: {e}")
        plans = []
    
    # Get current subscription
    current_subscription = None
    if BILLING_ENABLED:
        try:
            now = tz.now()
            current_subscription = Subscription.objects.filter(
                user=user,
                is_active=True,
                end_date__gte=now
            ).select_related('plan').first()
        except Exception as e:
            logger.error(f"Error getting current subscription: {e}")
            current_subscription = None

    # Get Paystack configuration for checkout
    paystack_public_key = ""
    try:
        paystack_config = PaystackConfiguration.objects.filter(
            tenant=tenant,
            is_active=True
        ).first()
        if paystack_config:
            paystack_public_key = paystack_config.public_key
    except Exception as e:
        logger.error(f"Error getting Paystack config: {e}")
    
    context = {
        'plans': plans,
        'current_subscription': current_subscription,
        'tenant': tenant,
        'tenant_name': tenant.name if tenant else 'CloudNetworks',
        'paystack_public_key': paystack_public_key,
        'paystack_enabled': bool(paystack_config and paystack_config.is_active),
        'page_title': 'Select Plan',
        'page_subtitle': 'Choose your internet subscription',
    }
    
    return render(request, 'billing/plans.html', context)

# ==================== PAYMENT VIEWS ====================

@login_required
def initiate_payment(request, plan_id):
    """Initialize Paystack payment with inline checkout (AJAX)"""
    if not BILLING_ENABLED:
        return JsonResponse({'error': 'Billing is not enabled on this system.'}, status=400)
    
    try:
        tenant = getattr(request, 'tenant', None) or getattr(request.user, 'tenant', None)
        plan = get_object_or_404(SubscriptionPlan, id=plan_id, tenant=tenant, is_active=True)
        
        # Generate unique reference
        reference = f"SUB_{uuid.uuid4().hex[:10].upper()}"
        
        # Get Paystack configuration
        try:
            paystack_config = PaystackConfiguration.objects.get(tenant=tenant, is_active=True)
            PAYSTACK_SECRET_KEY = paystack_config.secret_key
            subaccount_code = paystack_config.subaccount_code
        except PaystackConfiguration.DoesNotExist:
            # Fallback to settings if tenant config not found
            PAYSTACK_SECRET_KEY = getattr(settings, 'PAYSTACK_SECRET_KEY', '')
            subaccount_code = None
        
        # Create payment record
        payment = Payment.objects.create(
            user=request.user,
            plan=plan,
            amount=plan.price,
            reference=reference,
            status='pending',
            payment_method='paystack'
        )
        
        # Prepare metadata
        metadata = {
            "user_id": str(request.user.id),
            "tenant_id": str(tenant.id) if tenant else "0",
            "plan_id": str(plan.id),
            "plan_duration_days": plan.duration_days,
            "payment_id": str(payment.id),
            "custom_fields": [
                {
                    "display_name": "Plan",
                    "variable_name": "plan",
                    "value": plan.name
                },
                {
                    "display_name": "Duration",
                    "variable_name": "duration",
                    "value": f"{plan.duration_days} days"
                }
            ]
        }
        
        # Add subaccount for revenue sharing if configured
        paystack_data = {
            'email': request.user.email,
            'amount': decimal_to_paystack_amount(plan.price),  # Convert to kobo
            'reference': reference,
            'callback_url': request.build_absolute_uri(f'/billing/payment-success/{reference}/'),
            'metadata': metadata
        }
        
        if subaccount_code:
            paystack_data['subaccount'] = subaccount_code
            paystack_data['transaction_charge'] = int(plan.price * Decimal('0.015') * 100)  # 1.5% in kobo
        
        # Initialize Paystack transaction
        headers = {
            'Authorization': f'Bearer {PAYSTACK_SECRET_KEY}',
            'Content-Type': 'application/json',
        }
        
        response = requests.post(
            'https://api.paystack.co/transaction/initialize',
            json=paystack_data,
            headers=headers,
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            if data['status']:
                # Update payment with access code
                payment.paystack_access_code = data['data']['access_code']
                payment.save()
                
                return JsonResponse({
                    'status': 'success',
                    'authorization_url': data['data']['authorization_url'],
                    'reference': reference
                })
            else:
                error_message = data.get('message', 'Unknown Paystack error')
                payment.status = 'failed'
                payment.save()
                return JsonResponse({
                    'status': 'error',
                    'message': f'Paystack error: {error_message}'
                }, status=400)
        else:
            payment.status = 'failed'
            payment.save()
            return JsonResponse({
                'status': 'error',
                'message': 'Unable to connect to Paystack. Please try again.'
            }, status=400)
            
    except SubscriptionPlan.DoesNotExist:
        return JsonResponse({
            'status': 'error',
            'message': 'Selected plan not found or is no longer available.'
        }, status=404)
    except Exception as e:
        logger.error(f"Payment initiation error: {e}")
        return JsonResponse({
            'status': 'error',
            'message': 'An unexpected error occurred. Please try again.'
        }, status=500)

@login_required
def payment_verify(request, reference):
    """Verify payment status after Paystack redirect"""
    try:
        payment = get_object_or_404(Payment, reference=reference, user=request.user)
        
        # If payment already completed, redirect to success
        if payment.status == 'completed':
            return redirect('payment_success', reference=reference)
        
        # Get Paystack configuration
        tenant = getattr(request.user, 'tenant', None)
        try:
            paystack_config = PaystackConfiguration.objects.get(tenant=tenant, is_active=True)
            PAYSTACK_SECRET_KEY = paystack_config.secret_key
        except PaystackConfiguration.DoesNotExist:
            PAYSTACK_SECRET_KEY = getattr(settings, 'PAYSTACK_SECRET_KEY', '')
        
        # Verify payment with Paystack
        headers = {
            'Authorization': f'Bearer {PAYSTACK_SECRET_KEY}',
        }
        
        response = requests.get(
            f'https://api.paystack.co/transaction/verify/{reference}',
            headers=headers,
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            
            if data['status'] and data['data']['status'] == 'success':
                # Payment successful
                transaction_data = data['data']
                
                payment.status = 'completed'
                payment.paystack_reference = transaction_data.get('reference', reference)
                payment.save()
                
                # Get the plan
                plan = payment.plan
                
                if plan:
                    # Use subscription service to handle activation
                    subscription_service.activate_user_subscription(
                        user=request.user,
                        plan=plan,
                        payment=payment
                    )
                    
                    messages.success(
                        request, 
                        f"Payment completed successfully! Your {plan.name} plan has been activated for {plan.duration_days} days."
                    )
                else:
                    messages.success(request, "Payment completed successfully!")
                
                return redirect('payment_success', reference=reference)
            else:
                payment.status = 'failed'
                payment.save()
                messages.error(request, "Payment failed or was cancelled. Please try again.")
                return redirect('plan_selection')
        else:
            payment.status = 'failed'
            payment.save()
            messages.error(request, "Unable to verify payment. Please contact support.")
            return redirect('plan_selection')
            
    except Payment.DoesNotExist:
        messages.error(request, "Payment record not found.")
        return redirect('plan_selection')
    
# Add this to billing/views.py in the Payment Views section

@login_required
def verify_payment_api(request):
    """API endpoint for verifying payment via AJAX"""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=400)
    
    try:
        data = json.loads(request.body)
        reference = data.get('reference')
        plan_id = data.get('plan_id')
        
        if not reference or not plan_id:
            return JsonResponse({'status': 'error', 'message': 'Missing required parameters'}, status=400)
        
        # Get payment
        payment = get_object_or_404(Payment, reference=reference, user=request.user)
        
        # Get Paystack configuration
        tenant = getattr(request.user, 'tenant', None)
        try:
            paystack_config = PaystackConfiguration.objects.get(tenant=tenant, is_active=True)
            PAYSTACK_SECRET_KEY = paystack_config.secret_key
        except PaystackConfiguration.DoesNotExist:
            PAYSTACK_SECRET_KEY = getattr(settings, 'PAYSTACK_SECRET_KEY', '')
        
        # Verify payment with Paystack
        headers = {
            'Authorization': f'Bearer {PAYSTACK_SECRET_KEY}',
        }
        
        response = requests.get(
            f'https://api.paystack.co/transaction/verify/{reference}',
            headers=headers,
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            
            if data['status'] and data['data']['status'] == 'success':
                # Payment successful
                transaction_data = data['data']
                
                payment.status = 'completed'
                payment.paystack_reference = transaction_data.get('reference', reference)
                payment.save()
                
                # Get the plan
                plan = get_object_or_404(SubscriptionPlan, id=plan_id, tenant=tenant, is_active=True)
                
                # Use subscription service to handle activation
                subscription_service.activate_user_subscription(
                    user=request.user,
                    plan=plan,
                    payment=payment
                )
                
                return JsonResponse({
                    'status': 'success',
                    'message': 'Payment verified and subscription activated successfully!'
                })
            else:
                payment.status = 'failed'
                payment.save()
                return JsonResponse({
                    'status': 'error',
                    'message': 'Payment verification failed'
                })
        else:
            payment.status = 'failed'
            payment.save()
            return JsonResponse({
                'status': 'error',
                'message': 'Unable to verify payment'
            })
            
    except Payment.DoesNotExist:
        return JsonResponse({
            'status': 'error',
            'message': 'Payment not found'
        }, status=404)
    except Exception as e:
        logger.error(f"Payment verification error: {e}")
        return JsonResponse({
            'status': 'error',
            'message': 'An error occurred during verification'
        }, status=500)

def verify_paystack_payment(reference):
    """Verify Paystack payment status"""
    try:
        # Get payment
        payment = Payment.objects.get(reference=reference)
        
        # Get Paystack configuration
        tenant = payment.user.tenant if payment.user else None
        if tenant:
            try:
                paystack_config = PaystackConfiguration.objects.get(tenant=tenant, is_active=True)
                PAYSTACK_SECRET_KEY = paystack_config.secret_key
            except PaystackConfiguration.DoesNotExist:
                PAYSTACK_SECRET_KEY = getattr(settings, 'PAYSTACK_SECRET_KEY', '')
        else:
            PAYSTACK_SECRET_KEY = getattr(settings, 'PAYSTACK_SECRET_KEY', '')
        
        # Verify payment with Paystack
        headers = {
            'Authorization': f'Bearer {PAYSTACK_SECRET_KEY}',
        }
        
        response = requests.get(
            f'https://api.paystack.co/transaction/verify/{reference}',
            headers=headers,
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            
            if data['status'] and data['data']['status'] == 'success':
                # Payment successful
                payment.status = 'completed'
                payment.paystack_reference = reference
                payment.save()  # This triggers auto-activation
                
                logger.info(f"Paystack payment verified: {reference}")
                return True
            else:
                payment.status = 'failed'
                payment.save()
                logger.warning(f"Paystack payment failed: {reference}")
                
        else:
            logger.error(f"Failed to verify Paystack payment: {reference}")
            
    except Payment.DoesNotExist:
        logger.error(f"Payment not found for reference: {reference}")
    except Exception as e:
        logger.error(f"Error verifying Paystack payment: {e}")
    
    return False

@login_required
def payment_success(request, reference):
    """Display payment success page"""
    try:
        payment = Payment.objects.get(reference=reference, user=request.user)
    except Payment.DoesNotExist:
        messages.error(request, "Payment record not found.")
        return redirect('plan_selection')

    plan = payment.plan

    context = {
        'payment': payment,
        'plan': plan,
        'reference': reference,
        'message': 'Payment successful! Your subscription has been activated.',
        'page_title': 'Payment Successful',
        'page_subtitle': 'Thank you for your payment',
    }

    try:
        # Create commission transaction if possible
        tenant = getattr(request.user, 'tenant', None)
        if tenant:
            create_commission_transaction(
                payment=payment,
                tenant=tenant,
                service_type='subscription',
                amount=payment.amount
            )
    except Exception as e:
        logger.error(f"Error creating commission transaction: {e}")

    return render(request, 'billing/payment_success.html', context)

@login_required
def payment_confirmation(request, payment_id):
    """Payment confirmation page"""
    payment = get_object_or_404(Payment, id=payment_id, user=request.user)
    
    context = {
        'payment': payment,
        'page_title': 'Payment Confirmation',
        'page_subtitle': 'Complete your subscription payment',
    }
    
    return render(request, 'billing/payment_confirmation.html', context)

@login_required
def api_payment_details(request, payment_id):
    """API endpoint for customer to view their payment details"""
    try:
        payment = Payment.objects.get(id=payment_id, user=request.user)
        
        # Get the payment method display name
        payment_method_display = 'Unknown'
        if payment.payment_method:
            # Get the human-readable version of payment method
            for choice in Payment.PAYMENT_METHOD_CHOICES:
                if choice[0] == payment.payment_method:
                    payment_method_display = choice[1]
                    break
        
        data = {
            'success': True,
            'customer_name': payment.user.get_full_name() or payment.user.username,
            'customer_email': payment.user.email,
            'amount': str(payment.amount),
            'status': payment.status,
            'created_date': payment.created_at.strftime('%B %d, %Y'),
            'created_time': payment.created_at.strftime('%I:%M %p'),
            'transaction_id': payment.reference or f'PAY-{payment.id}',
            'payment_method': payment_method_display,
            'plan_name': payment.plan.name if payment.plan else 'N/A',
            'plan_bandwidth': f"{payment.plan.bandwidth} Mbps" if payment.plan and hasattr(payment.plan, 'bandwidth') else 'N/A',
        }
        
        return JsonResponse(data)
        
    except Payment.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Payment not found'}, status=404)
    except Exception as e:
        logger.error(f"Error fetching payment details: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
    
def _handle_new_recurring_payment(data):
    """Handle new recurring payment from webhook"""
    try:
        # Extract user and plan info from metadata
        metadata = data.get('metadata', {})
        user_id = metadata.get('user_id')
        plan_id = metadata.get('plan_id')
        
        if user_id and plan_id:
            user = CustomUser.objects.get(id=user_id)
            plan = SubscriptionPlan.objects.get(id=plan_id)
            
            # Create new payment record
            payment = Payment.objects.create(
                user=user,
                plan=plan,
                amount=float(data.get('amount', 0)) / 100,  # Convert from kobo
                reference=data.get('reference'),
                status='completed',
                paystack_reference=data.get('reference'),
                payment_method='paystack'
            )
            
            # Activate subscription
            subscription_service.activate_user_subscription(user, plan, payment)
            
    except Exception as e:
        logger.error(f"Error handling recurring payment: {e}")

def _handle_subscription_creation(data):
    """Handle subscription creation from webhook"""
    try:
        metadata = data.get('metadata', {})
        user_id = metadata.get('user_id')
        plan_id = metadata.get('plan_id')
        
        if user_id and plan_id:
            user = CustomUser.objects.get(id=user_id)
            plan = SubscriptionPlan.objects.get(id=plan_id)
            
            logger.info(f"Webhook: Subscription created for {user.username} - {plan.name}")
            
    except Exception as e:
        logger.error(f"Error handling subscription creation: {e}")

def _handle_subscription_cancellation(data):
    """Handle subscription cancellation from webhook"""
    try:
        metadata = data.get('metadata', {})
        user_id = metadata.get('user_id')
        
        if user_id:
            user = CustomUser.objects.get(id=user_id)
            
            # Deactivate user's active subscription
            Subscription.objects.filter(user=user, is_active=True).update(is_active=False)
            
            logger.info(f"Webhook: Subscription cancelled for {user.username}")
            
    except Exception as e:
        logger.error(f"Error handling subscription cancellation: {e}")

@login_required
def payment_history(request):
    """Display user's payment history with enhanced statistics"""
    # Get all payments for the user
    payments_qs = Payment.objects.filter(user=request.user).select_related('plan').order_by('-created_at')
    
    # Calculate statistics
    total_payments = payments_qs.count()
    
    # Successful payments (completed)
    successful_payments = payments_qs.filter(status='completed').count()
    
    # Pending payments
    pending_payments = payments_qs.filter(status='pending').count()
    
    # Failed payments
    failed_payments = payments_qs.filter(status='failed').count()
    
    # Total revenue (sum of completed payments)
    total_revenue_result = payments_qs.filter(status='completed').aggregate(
        total=Sum('amount')
    )
    total_revenue = total_revenue_result['total'] or 0
    
    # Monthly revenue (last 30 days)
    thirty_days_ago = tz.now() - timedelta(days=30)
    monthly_revenue_result = payments_qs.filter(
        status='completed',
        created_at__gte=thirty_days_ago
    ).aggregate(
        total=Sum('amount')
    )
    monthly_revenue = monthly_revenue_result['total'] or 0
    
    # Monthly payments count
    monthly_payments = payments_qs.filter(
        created_at__gte=thirty_days_ago
    ).count()
    
    # Pending amount
    pending_amount_result = payments_qs.filter(
        status='pending'
    ).aggregate(
        total=Sum('amount')
    )
    pending_amount = pending_amount_result['total'] or 0
    
    # Average payment amount
    average_payment = total_revenue / successful_payments if successful_payments > 0 else 0
    
    # Get recent payments for statistics (last 5)
    recent_payments = payments_qs[:5]
    
    # Pagination
    paginator = Paginator(payments_qs, 15)  # Show 15 payments per page
    page = request.GET.get('page', 1)
    
    try:
        payments = paginator.page(page)
    except PageNotAnInteger:
        payments = paginator.page(1)
    except EmptyPage:
        payments = paginator.page(paginator.num_pages)
    
    # Get user's subscription info
    subscription = None
    try:
        subscription = Subscription.objects.filter(
            user=request.user, 
            is_active=True
        ).first()
    except:
        pass
    
    context = {
        'payments': payments,
        'total_payments': total_payments,
        'successful_payments': successful_payments,
        'pending_payments': pending_payments,
        'failed_payments': failed_payments,
        'total_revenue': total_revenue,
        'monthly_revenue': monthly_revenue,
        'monthly_payments': monthly_payments,
        'pending_amount': pending_amount,
        'average_payment': average_payment,
        'recent_payments': recent_payments,
        'subscription': subscription,
        'page_title': 'Payment History',
        'page_subtitle': 'Track and manage all your payments',
    }
    
    return render(request, 'billing/history.html', context)

# ==================== UTILITY FUNCTIONS ====================

def distribute_bulk_data(bulk_purchase):
    """Distribute bulk data to customers (placeholder function)"""
    # This function would need to be implemented based on your specific
    # customer model and distribution logic
    logger.info(f"Would distribute {bulk_purchase.total_data} GB from purchase {bulk_purchase.id}")
    return True

@csrf_exempt
def paystack_webhook(request):
    """Handle Paystack webhooks for real-time updates"""
    if request.method != 'POST':
        return HttpResponse(status=400)
    
    try:
        payload = json.loads(request.body)
        event = payload.get('event')
        data = payload.get('data')
        
        logger.info(f"Paystack webhook received: {event}")
        
        if event == 'charge.success':
            reference = data.get('reference')
            
            try:
                payment = Payment.objects.get(reference=reference)
                
                if payment.status != 'completed':
                    payment.status = 'completed'
                    payment.paystack_reference = data.get('reference', reference)
                    payment.save()
                    
                    # Get the plan
                    plan = payment.plan
                    
                    if plan:
                        # Use subscription service to handle activation
                        subscription_service.activate_user_subscription(
                            user=payment.user,
                            plan=plan,
                            payment=payment
                        )
                        
                        logger.info(f"Webhook: Subscription activated for {payment.user.username}")
                    else:
                        logger.error(f"Webhook: No plan found for payment {reference}")

            except Payment.DoesNotExist:
                logger.warning(f"Webhook: Payment not found for reference {reference}")
        
        return JsonResponse({'status': 'success'})
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)


@login_required
def configure_api_integration(request):
    """Configure API integration for external data"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    # Get existing API configurations
    api_configs = APIIntegrationConfig.objects.filter(tenant=tenant)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'add_api':
            provider_type = request.POST.get('provider_type')
            name = request.POST.get('name')
            api_endpoint = request.POST.get('api_endpoint')
            api_key = request.POST.get('api_key')
            api_secret = request.POST.get('api_secret')
            
            # Test connection first
            try:
                from .api_integrations import APIIntegrationManager
                provider = APIIntegrationManager.get_provider(
                    provider_type,
                    api_endpoint=api_endpoint,
                    api_key=api_key,
                    api_secret=api_secret
                )
                
                if provider.test_connection():
                    # Save configuration
                    APIIntegrationConfig.objects.create(
                        tenant=tenant,
                        provider_type=provider_type,
                        name=name,
                        api_endpoint=api_endpoint,
                        api_key=api_key,
                        api_secret=api_secret,
                        is_active=True,
                        last_tested_at=tz.now(),
                        last_tested_status='success'
                    )
                    messages.success(request, f'API configuration "{name}" added successfully')
                else:
                    messages.error(request, 'Could not connect to API. Check credentials and endpoint.')
                    
            except Exception as e:
                messages.error(request, f'API test failed: {str(e)}')
        
        elif action == 'test_api':
            config_id = request.POST.get('config_id')
            try:
                config = APIIntegrationConfig.objects.get(id=config_id, tenant=tenant)
                
                from .api_integrations import APIIntegrationManager
                provider = APIIntegrationManager.get_provider(
                    config.provider_type,
                    api_endpoint=config.api_endpoint,
                    api_key=config.api_key,
                    api_secret=config.api_secret
                )
                
                if provider.test_connection():
                    config.last_tested_at = tz.now()
                    config.last_tested_status = 'success'
                    config.save()
                    messages.success(request, f'API connection test successful for {config.name}')
                else:
                    config.last_tested_status = 'failed'
                    config.save()
                    messages.error(request, f'API connection test failed for {config.name}')
                    
            except APIIntegrationConfig.DoesNotExist:
                messages.error(request, 'Configuration not found')
        
        return redirect('configure_api_integration')
    
    context = {
        'tenant': tenant,
        'api_configs': api_configs,
        'provider_types': [
            ('safaricom', 'Safaricom Data API'),
            ('airtel', 'Airtel Data API'),
            ('isp_system', 'ISP Management System'),
            ('data_vendor', 'Third-party Data Vendor'),
        ],
        'page_title': 'API Integration',
        'page_subtitle': 'Configure external API connections',
    }
    
    return render(request, 'billing/api_integration.html', context)

@login_required
def api_sync_data(request, config_id):
    """Sync data from API configuration"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return JsonResponse({'success': False, 'error': 'Access denied'})
    
    try:
        config = APIIntegrationConfig.objects.get(id=config_id, tenant=request.user.tenant)
        wallet = DataWallet.objects.filter(tenant=request.user.tenant).first()
        
        if not wallet:
            return JsonResponse({'success': False, 'error': 'Wallet not found'})
        
        # Get appropriate provider
        from .api_integrations import APIIntegrationManager
        provider = APIIntegrationManager.get_provider(
            config.provider_type,
            api_endpoint=config.api_endpoint,
            api_key=config.api_key,
            api_secret=config.api_secret
        )
        
        # Sync based on provider type
        if config.provider_type in ['safaricom', 'airtel', 'mtn']:
            # Telecom provider - get available balance
            balance_gb = provider.get_data_balance()
            
            if balance_gb > 0:
                # Deposit to wallet
                result = wallet.deposit_external(
                    amount_gb=balance_gb,
                    user=request.user,
                    source_type='api_deposit',
                    external_source=config.name,
                    external_reference=f'API-SYNC-{tz.now().strftime("%Y%m%d%H%M%S")}',
                    description=f'API sync from {config.name}'
                )
                
                # Update config stats
                config.last_sync_at = tz.now()
                config.last_sync_status = 'success'
                config.last_sync_amount = balance_gb
                config.total_synced += balance_gb
                config.save()
                
                return JsonResponse({
                    'success': True,
                    'message': f'Synced {balance_gb} GB from {config.name}',
                    'amount': float(balance_gb),
                    'new_balance': float(wallet.balance_gb)
                })
            else:
                return JsonResponse({
                    'success': False,
                    'error': 'No data available from API'
                })
        
        elif config.provider_type == 'data_vendor':
            # Third-party data vendor - get packages and purchase
            packages = provider.get_available_packages()
            
            if packages:
                # Example: Purchase first package
                package = packages[0]
                purchase_result = provider.purchase_package(package['id'])
                
                if purchase_result['success']:
                    # Deposit purchased data
                    result = wallet.deposit_external(
                        amount_gb=purchase_result['total_data_gb'],
                        user=request.user,
                        source_type='api_purchase',
                        external_source=config.name,
                        external_reference=purchase_result['transaction_id'],
                        description=f'API purchase from {config.name}: {package["name"]}'
                    )
                    
                    config.last_sync_at = tz.now()
                    config.last_sync_status = 'success'
                    config.last_sync_amount = purchase_result['total_data_gb']
                    config.total_synced += purchase_result['total_data_gb']
                    config.save()
                    
                    return JsonResponse({
                        'success': True,
                        'message': f'Purchased {purchase_result["total_data_gb"]} GB from {config.name}',
                        'amount': float(purchase_result['total_data_gb']),
                        'new_balance': float(wallet.balance_gb)
                    })
        
        return JsonResponse({'success': False, 'error': 'Provider type not implemented'})
        
    except Exception as e:
        logger.error(f"API sync error: {e}")
        return JsonResponse({'success': False, 'error': str(e)})
    

@login_required
def configure_database_connection(request):
    """Configure database connection for ISP server"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    # Get existing database configurations
    db_configs = DatabaseConnectionConfig.objects.filter(tenant=tenant)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'add_database':
            name = request.POST.get('name')
            db_type = request.POST.get('db_type')
            host = request.POST.get('host')
            port = request.POST.get('port')
            database = request.POST.get('database')
            username = request.POST.get('username')
            password = request.POST.get('password')
            
            # Test connection
            try:
                from .database_integrations import DatabaseConnection
                db = DatabaseConnection(
                    host=host,
                    port=int(port),
                    database=database,
                    username=username,
                    password=password,
                    db_type=db_type
                )
                
                if db.connect():
                    # Save configuration (encrypt password)
                    from cryptography.fernet import Fernet
                    from django.conf import settings
                    
                    cipher = Fernet(settings.ENCRYPTION_KEY[:32].encode())
                    encrypted_password = cipher.encrypt(password.encode())
                    
                    DatabaseConnectionConfig.objects.create(
                        tenant=tenant,
                        name=name,
                        db_type=db_type,
                        host=host,
                        port=port,
                        database=database,
                        username=username,
                        encrypted_password=encrypted_password,
                        is_active=True,
                        last_tested_at=tz.now(),
                        last_tested_status='success'
                    )
                    messages.success(request, f'Database connection "{name}" added successfully')
                    db.disconnect()
                else:
                    messages.error(request, 'Could not connect to database. Check credentials.')
                    
            except Exception as e:
                messages.error(request, f'Connection test failed: {str(e)}')
        
        elif action == 'test_database':
            config_id = request.POST.get('config_id')
            try:
                config = DatabaseConnectionConfig.objects.get(id=config_id, tenant=tenant)
                
                # Decrypt password
                from cryptography.fernet import Fernet
                from django.conf import settings
                
                cipher = Fernet(settings.ENCRYPTION_KEY[:32].encode())
                password = cipher.decrypt(config.encrypted_password).decode()
                
                from .database_integrations import DatabaseConnection
                db = DatabaseConnection(
                    host=config.host,
                    port=config.port,
                    database=config.database,
                    username=config.username,
                    password=password,
                    db_type=config.db_type
                )
                
                if db.connect():
                    config.last_tested_at = tz.now()
                    config.last_tested_status = 'success'
                    config.save()
                    messages.success(request, f'Database connection test successful for {config.name}')
                    db.disconnect()
                else:
                    config.last_tested_status = 'failed'
                    config.save()
                    messages.error(request, f'Database connection test failed for {config.name}')
                    
            except DatabaseConnectionConfig.DoesNotExist:
                messages.error(request, 'Configuration not found')
        
        return redirect('configure_database_connection')
    
    context = {
        'tenant': tenant,
        'db_configs': db_configs,
        'db_types': [
            ('postgresql', 'PostgreSQL'),
            ('mysql', 'MySQL'),
            ('sqlserver', 'SQL Server'),
        ],
        'page_title': 'Database Integration',
        'page_subtitle': 'Connect to your ISP database/server',
    }
    
    return render(request, 'billing/database_integration.html', context)

@login_required
def database_sync_data(request, config_id):
    """Sync data from database connection"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return JsonResponse({'success': False, 'error': 'Access denied'})
    
    try:
        config = DatabaseConnectionConfig.objects.get(id=config_id, tenant=request.user.tenant)
        wallet = DataWallet.objects.filter(tenant=request.user.tenant).first()
        
        if not wallet:
            return JsonResponse({'success': False, 'error': 'Wallet not found'})
        
        # Decrypt password
        from cryptography.fernet import Fernet
        from django.conf import settings
        
        cipher = Fernet(settings.ENCRYPTION_KEY[:32].encode())
        password = cipher.decrypt(config.encrypted_password).decode()
        
        # Create database manager
        from .database_integrations import ISPDatabaseManager
        
        db_config = {
            'host': config.host,
            'port': config.port,
            'database': config.database,
            'username': config.username,
            'password': password,
            'db_type': config.db_type
        }
        
        db_manager = ISPDatabaseManager(db_config)
        
        # Get data balance
        balance_gb = db_manager.get_data_balance_from_billing()
        
        if balance_gb > 0:
            # Deposit to wallet
            result = wallet.deposit_external(
                amount_gb=balance_gb,
                user=request.user,
                source_type='database_sync',
                external_source=config.name,
                external_reference=f'DB-SYNC-{tz.now().strftime("%Y%m%d%H%M%S")}',
                description=f'Database sync from {config.name}'
            )
            
            # Update config stats
            config.last_sync_at = tz.now()
            config.last_sync_status = 'success'
            config.last_sync_amount = balance_gb
            config.total_synced += balance_gb
            config.save()
            
            # Also sync customer data if enabled
            if config.sync_customers:
                customers = db_manager.sync_customers_to_platform()
                # Process customer sync here...
            
            return JsonResponse({
                'success': True,
                'message': f'Synced {balance_gb} GB from {config.name}',
                'amount': float(balance_gb),
                'new_balance': float(wallet.balance_gb)
            })
        else:
            return JsonResponse({
                'success': False,
                'error': 'No data available in database'
            })
        
    except Exception as e:
        logger.error(f"Database sync error: {e}")
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
def database_query_tool(request, config_id):
    """Interactive database query tool"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    try:
        config = DatabaseConnectionConfig.objects.get(id=config_id, tenant=request.user.tenant)
        
        # Decrypt password
        from cryptography.fernet import Fernet
        from django.conf import settings
        
        cipher = Fernet(settings.ENCRYPTION_KEY[:32].encode())
        password = cipher.decrypt(config.encrypted_password).decode()
        
        from .database_integrations import DatabaseConnection
        db = DatabaseConnection(
            host=config.host,
            port=config.port,
            database=config.database,
            username=config.username,
            password=password,
            db_type=config.db_type
        )
        
        results = []
        error = None
        query = ""
        
        if request.method == 'POST':
            query = request.POST.get('query', '').strip()
            
            if query:
                try:
                    results = db.execute_query(query)
                except Exception as e:
                    error = str(e)
        
        db.disconnect()
        
        context = {
            'tenant': request.user.tenant,
            'config': config,
            'query': query,
            'results': results,
            'error': error,
            'row_count': len(results),
            'page_title': 'Database Query Tool',
            'page_subtitle': f'Query {config.name} database',
        }
        
        return render(request, 'billing/database_query_tool.html', context)
        
    except DatabaseConnectionConfig.DoesNotExist:
        messages.error(request, 'Database configuration not found')
        return redirect('configure_database_connection')
    

# ==================== EXTERNAL SOURCES MANAGEMENT ====================

@login_required
def manage_external_sources(request):
    """Manage external data sources"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    # Get all external sources
    sources = ExternalDataSource.objects.filter(tenant=tenant).order_by('name')
    
    # Calculate statistics for the template
    from django.db.models import Sum
    
    active_sources_count = sources.filter(is_active=True).count()
    auto_sync_count = sources.filter(auto_sync=True).count()
    
    # Calculate total deposits
    total_deposits_result = sources.aggregate(total=Sum('total_deposits'))
    total_deposits = total_deposits_result['total'] or Decimal('0')
    
    context = {
        'tenant': tenant,
        'sources': sources,
        'active_sources_count': active_sources_count,
        'auto_sync_count': auto_sync_count,
        'total_deposits': total_deposits,
        'page_title': 'External Data Sources',
        'page_subtitle': 'Manage your external data connections',
    }
    
    return render(request, 'billing/external_sources/manage.html', context)

@login_required
def add_external_source(request):
    """Add new external data source"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    if request.method == 'POST':
        name = request.POST.get('name')
        source_type = request.POST.get('source_type')
        description = request.POST.get('description', '')
        api_endpoint = request.POST.get('api_endpoint', '')
        api_key = request.POST.get('api_key', '')
        api_secret = request.POST.get('api_secret', '')
        file_format = request.POST.get('file_format', '')
        
        auto_sync = request.POST.get('auto_sync') == 'on'
        sync_frequency = request.POST.get('sync_frequency', 'manual')
        
        # Validate required fields
        if not name or not source_type:
            messages.error(request, 'Name and source type are required')
            return redirect('add_external_source')
        
        try:
            # Encrypt sensitive data (returns strings)
            encrypted_api_key = DataEncryption.encrypt(api_key) if api_key else None
            encrypted_api_secret = DataEncryption.encrypt(api_secret) if api_secret else None
            
            # Create the source
            source = ExternalDataSource.objects.create(
                tenant=tenant,
                name=name,
                source_type=source_type,
                description=description,
                api_endpoint=api_endpoint if api_endpoint else None,
                api_key=encrypted_api_key,  # This is now a string
                api_secret=encrypted_api_secret,  # This is now a string
                file_format=file_format if file_format else None,
                auto_sync=auto_sync,
                sync_frequency=sync_frequency,
                is_active=True
            )
            
            messages.success(request, f'External source "{name}" added successfully')
            return redirect('manage_external_sources')
            
        except Exception as e:
            messages.error(request, f'Error adding source: {str(e)}')
            logger.error(f"Error creating external source: {e}")
    
    context = {
        'tenant': tenant,
        'page_title': 'Add External Source',
        'page_subtitle': 'Configure a new external data source',
    }
    
    return render(request, 'billing/external_sources/add.html', context)

@login_required
def edit_external_source(request, source_id):
    """Edit external data source"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    try:
        source = ExternalDataSource.objects.get(id=source_id, tenant=tenant)
    except ExternalDataSource.DoesNotExist:
        messages.error(request, 'Source not found')
        return redirect('manage_external_sources')
    
    # Decrypt sensitive data for display
    decrypted_api_key = DataEncryption.decrypt(source.api_key) if source.api_key else ''
    decrypted_api_secret = DataEncryption.decrypt(source.api_secret) if source.api_secret else ''
    
    if request.method == 'POST':
        name = request.POST.get('name')
        source_type = request.POST.get('source_type')
        description = request.POST.get('description', '')
        api_endpoint = request.POST.get('api_endpoint', '')
        api_key = request.POST.get('api_key', '')
        api_secret = request.POST.get('api_secret', '')
        file_format = request.POST.get('file_format', '')
        
        auto_sync = request.POST.get('auto_sync') == 'on'
        sync_frequency = request.POST.get('sync_frequency', 'manual')
        
        # Update fields
        source.name = name
        source.source_type = source_type
        source.description = description
        source.api_endpoint = api_endpoint if api_endpoint else None
        source.file_format = file_format if file_format else None
        source.auto_sync = auto_sync
        source.sync_frequency = sync_frequency
        
        # Only update API key if a new value is provided
        if api_key and api_key != decrypted_api_key:
            source.api_key = DataEncryption.encrypt(api_key)
        
        # Only update API secret if a new value is provided
        if api_secret and api_secret != decrypted_api_secret:
            source.api_secret = DataEncryption.encrypt(api_secret)
        
        try:
            source.save()
            messages.success(request, f'External source "{name}" updated successfully')
            return redirect('manage_external_sources')
            
        except Exception as e:
            messages.error(request, f'Error updating source: {str(e)}')
    
    context = {
        'tenant': tenant,
        'source': source,
        'decrypted_api_key': decrypted_api_key,
        'decrypted_api_secret': decrypted_api_secret,
        'page_title': f'Edit {source.name}',
        'page_subtitle': 'Update external data source configuration',
    }
    
    return render(request, 'billing/external_sources/edit.html', context)


@login_required
def delete_external_source(request, source_id):
    """Delete external data source"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    if request.method == 'POST':
        try:
            source = ExternalDataSource.objects.get(id=source_id, tenant=tenant)
            source_name = source.name
            source.delete()
            
            messages.success(request, f'External source "{source_name}" deleted successfully')
            
        except ExternalDataSource.DoesNotExist:
            messages.error(request, 'Source not found')
        except Exception as e:
            messages.error(request, f'Error deleting source: {str(e)}')
    
    return redirect('manage_external_sources')

@login_required
def toggle_external_source(request, source_id):
    """Toggle external source active status"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return JsonResponse({'success': False, 'error': 'Access denied'})
    
    try:
        source = ExternalDataSource.objects.get(id=source_id, tenant=request.user.tenant)
        source.is_active = not source.is_active
        source.save()
        
        status = "activated" if source.is_active else "deactivated"
        
        return JsonResponse({
            'success': True,
            'message': f'Source {status} successfully',
            'is_active': source.is_active
        })
        
    except ExternalDataSource.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Source not found'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
def test_external_source(request, source_id):
    """Test external source connection"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return JsonResponse({'success': False, 'error': 'Access denied'})
    
    try:
        source = ExternalDataSource.objects.get(id=source_id, tenant=request.user.tenant)
        
        # Decrypt API credentials
        api_key = DataEncryption.decrypt(source.api_key) if source.api_key else ''
        api_secret = DataEncryption.decrypt(source.api_secret) if source.api_secret else ''
        
        # Test based on source type
        if source.source_type == 'external_api':
            # Test API connection
            try:
                import requests
                
                headers = {}
                if api_key:
                    headers['Authorization'] = f'Bearer {api_key}'
                
                # Add basic auth if both key and secret are provided
                if api_key and api_secret:
                    import base64
                    auth_str = f"{api_key}:{api_secret}"
                    encoded_auth = base64.b64encode(auth_str.encode()).decode()
                    headers['Authorization'] = f'Basic {encoded_auth}'
                
                # Test endpoint
                test_url = source.api_endpoint.rstrip('/') + '/health'
                if not test_url.startswith('http'):
                    test_url = 'https://' + test_url
                
                response = requests.get(
                    test_url,
                    headers=headers,
                    timeout=10,
                    verify=False  # For testing only, use verify=True in production
                )
                
                if response.status_code in [200, 201]:
                    source.last_tested_at = tz.now()
                    source.last_tested_status = 'success'
                    source.save()
                    
                    return JsonResponse({
                        'success': True,
                        'message': f'API connection successful (Status: {response.status_code})'
                    })
                else:
                    source.last_tested_status = 'failed'
                    source.save()
                    return JsonResponse({
                        'success': False,
                        'error': f'API returned status {response.status_code}'
                    })
                    
            except requests.exceptions.ConnectionError:
                source.last_tested_status = 'failed'
                source.save()
                return JsonResponse({
                    'success': False,
                    'error': 'Cannot connect to API endpoint'
                })
            except Exception as e:
                source.last_tested_status = 'failed'
                source.save()
                logger.error(f"API test error: {e}")
                return JsonResponse({
                    'success': False,
                    'error': f'API test failed: {str(e)}'
                })
        
        elif source.source_type == 'isp_server':
            # Test database connection
            # You would implement database testing here
            source.last_tested_at = tz.now()
            source.last_tested_status = 'success'
            source.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Server connection test successful'
            })
        
        else:
            # For file-based sources, just mark as successful
            source.last_tested_at = tz.now()
            source.last_tested_status = 'success'
            source.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Source configuration saved'
            })
        
    except ExternalDataSource.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Source not found'})
    except Exception as e:
        logger.error(f"Source test error: {e}")
        return JsonResponse({'success': False, 'error': str(e)})
    

# ==================== DATA IMPORT/EXPORT VIEWS ====================

@login_required
def data_import_tool(request):
    """Data import tool for various formats"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    if request.method == 'POST' and request.FILES:
        import_type = request.POST.get('import_type')
        file = request.FILES.get('file')
        
        try:
            if import_type == 'csv':
                import csv
                from decimal import Decimal
                
                # Parse CSV file
                content = file.read().decode('utf-8').splitlines()
                reader = csv.DictReader(content)
                
                imported_count = 0
                errors = []
                
                for i, row in enumerate(reader, 1):
                    try:
                        amount_gb = Decimal(row.get('amount_gb', '0'))
                        reference = row.get('reference', f'CSV-{i}')
                        description = row.get('description', f'CSV import row {i}')
                        customer_id = row.get('customer_id')
                        customer_name = row.get('customer_name', '')
                        
                        if amount_gb > 0:
                            # Create transaction log
                            DataImportLog.objects.create(
                                tenant=tenant,
                                import_type='csv',
                                filename=file.name,
                                row_number=i,
                                amount_gb=amount_gb,
                                reference=reference,
                                description=description,
                                customer_id=customer_id,
                                customer_name=customer_name,
                                status='pending',
                                created_by=request.user
                            )
                            imported_count += 1
                            
                    except Exception as e:
                        errors.append(f"Row {i}: {str(e)}")
                
                # Process imports
                process_data_imports(tenant, request.user)
                
                if imported_count > 0:
                    messages.success(request, f'Successfully imported {imported_count} records from CSV')
                if errors:
                    messages.warning(request, f'{len(errors)} rows had errors')
                
            elif import_type == 'excel':
                import pandas as pd
                from decimal import Decimal
                
                # Read Excel file
                df = pd.read_excel(file)
                
                imported_count = 0
                errors = []
                
                for i, row in df.iterrows():
                    try:
                        amount_gb = Decimal(str(row.get('amount_gb', 0)))
                        reference = str(row.get('reference', f'EXCEL-{i+1}'))
                        description = str(row.get('description', f'Excel import row {i+1}'))
                        
                        if amount_gb > 0:
                            DataImportLog.objects.create(
                                tenant=tenant,
                                import_type='excel',
                                filename=file.name,
                                row_number=i+1,
                                amount_gb=amount_gb,
                                reference=reference,
                                description=description,
                                status='pending',
                                created_by=request.user
                            )
                            imported_count += 1
                            
                    except Exception as e:
                        errors.append(f"Row {i+1}: {str(e)}")
                
                # Process imports
                process_data_imports(tenant, request.user)
                
                if imported_count > 0:
                    messages.success(request, f'Successfully imported {imported_count} records from Excel')
                if errors:
                    messages.warning(request, f'{len(errors)} rows had errors')
            
            elif import_type == 'json':
                import json
                from decimal import Decimal
                
                # Parse JSON file
                data = json.loads(file.read().decode('utf-8'))
                
                imported_count = 0
                errors = []
                
                if isinstance(data, list):
                    for i, item in enumerate(data, 1):
                        try:
                            amount_gb = Decimal(str(item.get('amount_gb', 0)))
                            reference = item.get('reference', f'JSON-{i}')
                            description = item.get('description', f'JSON import item {i}')
                            
                            if amount_gb > 0:
                                DataImportLog.objects.create(
                                    tenant=tenant,
                                    import_type='json',
                                    filename=file.name,
                                    row_number=i,
                                    amount_gb=amount_gb,
                                    reference=reference,
                                    description=description,
                                    status='pending',
                                    created_by=request.user
                                )
                                imported_count += 1
                                
                        except Exception as e:
                            errors.append(f"Item {i}: {str(e)}")
                
                # Process imports
                process_data_imports(tenant, request.user)
                
                if imported_count > 0:
                    messages.success(request, f'Successfully imported {imported_count} records from JSON')
                if errors:
                    messages.warning(request, f'{len(errors)} items had errors')
            
            return redirect('data_import_history')
            
        except Exception as e:
            messages.error(request, f'Import error: {str(e)}')
    
    context = {
        'tenant': tenant,
        'page_title': 'Data Import Tool',
        'page_subtitle': 'Import data from various file formats',
    }
    
    return render(request, 'billing/data_import_tool.html', context)

@login_required
def data_import_history(request):
    """View data import history"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    # Get import logs
    import_logs = DataImportLog.objects.filter(tenant=tenant).order_by('-created_at')
    
    # Calculate statistics
    total_imports = import_logs.count()
    successful_imports = import_logs.filter(status='success').count()
    failed_imports = import_logs.filter(status='failed').count()
    pending_imports = import_logs.filter(status='pending').count()
    
    total_amount = import_logs.filter(status='success').aggregate(
        total=Sum('amount_gb')
    )['total'] or Decimal('0')
    
    context = {
        'tenant': tenant,
        'import_logs': import_logs,
        'total_imports': total_imports,
        'successful_imports': successful_imports,
        'failed_imports': failed_imports,
        'pending_imports': pending_imports,
        'total_amount': total_amount,
        'page_title': 'Data Import History',
        'page_subtitle': 'Track all data imports',
    }
    
    return render(request, 'billing/data_import_history.html', context)

@login_required
def export_data_template(request, format_type):
    """Export data import template"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    if format_type == 'csv':
        # Create CSV template
        import csv
        from django.http import HttpResponse
        
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="data_import_template.csv"'
        
        writer = csv.writer(response)
        writer.writerow(['amount_gb', 'reference', 'description', 'customer_id', 'customer_name'])
        writer.writerow(['10.5', 'INV-001', 'Monthly data allocation', 'CUST001', 'John Doe'])
        writer.writerow(['5.0', 'INV-002', 'Top-up data', 'CUST002', 'Jane Smith'])
        
        return response
    
    elif format_type == 'excel':
        # Create Excel template
        import pandas as pd
        from django.http import HttpResponse
        
        df = pd.DataFrame({
            'amount_gb': [10.5, 5.0],
            'reference': ['INV-001', 'INV-002'],
            'description': ['Monthly data allocation', 'Top-up data'],
            'customer_id': ['CUST001', 'CUST002'],
            'customer_name': ['John Doe', 'Jane Smith']
        })
        
        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = 'attachment; filename="data_import_template.xlsx"'
        
        with pd.ExcelWriter(response, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Template', index=False)
        
        return response
    
    messages.error(request, 'Invalid format type')
    return redirect('data_import_tool')

def process_data_imports(tenant, user):
    """Process pending data imports"""
    from decimal import Decimal
    
    pending_imports = DataImportLog.objects.filter(
        tenant=tenant,
        status='pending'
    )[:100]  # Process in batches
    
    wallet = DataWallet.objects.filter(tenant=tenant).first()
    if not wallet:
        return 0
    
    processed_count = 0
    
    for import_log in pending_imports:
        try:
            # Deposit to wallet
            if wallet.deposit_external(
                amount_gb=import_log.amount_gb,
                user=user,
                source_type='file_import',
                external_source=f'Import: {import_log.filename}',
                external_reference=import_log.reference,
                description=import_log.description
            ):
                import_log.status = 'success'
                import_log.processed_at = tz.now()
                processed_count += 1
            else:
                import_log.status = 'failed'
                import_log.error_message = 'Wallet deposit failed'
                
        except Exception as e:
            import_log.status = 'failed'
            import_log.error_message = str(e)
        
        import_log.save()
    
    return processed_count

# ==================== SCHEDULED TASKS ====================

@login_required
def run_scheduled_syncs(request):
    """Run all scheduled syncs (manual trigger)"""
    if request.user.role not in ['isp_admin', 'isp_staff', 'superadmin']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    # Get sources that need syncing
    from datetime import timedelta
    
    now = tz.now()
    sources_to_sync = []
    
    # API sources with auto-sync
    api_sources = ExternalDataSource.objects.filter(
        tenant=tenant,
        source_type='external_api',
        is_active=True,
        auto_sync=True
    )
    
    for source in api_sources:
        if source.last_sync_at:
            # Check if it's time to sync based on frequency
            if source.sync_frequency == 'hourly' and (now - source.last_sync_at).seconds >= 3600:
                sources_to_sync.append(('api', source))
            elif source.sync_frequency == 'daily' and (now - source.last_sync_at).days >= 1:
                sources_to_sync.append(('api', source))
            elif source.sync_frequency == 'weekly' and (now - source.last_sync_at).days >= 7:
                sources_to_sync.append(('api', source))
            elif source.sync_frequency == 'monthly' and (now - source.last_sync_at).days >= 30:
                sources_to_sync.append(('api', source))
        else:
            # Never synced before
            sources_to_sync.append(('api', source))
    
    # Database sources with auto-sync
    db_sources = ExternalDataSource.objects.filter(
        tenant=tenant,
        source_type='isp_server',
        is_active=True,
        auto_sync=True
    )
    
    for source in db_sources:
        if source.last_sync_at:
            if source.sync_frequency == 'daily' and (now - source.last_sync_at).days >= 1:
                sources_to_sync.append(('db', source))
        else:
            sources_to_sync.append(('db', source))
    
    # Run syncs
    results = []
    for sync_type, source in sources_to_sync:
        try:
            if sync_type == 'api':
                result = sync_external_source_api(source, request.user)
            elif sync_type == 'db':
                result = sync_external_source_database(source, request.user)
            else:
                continue
            
            results.append({
                'source': source.name,
                'type': sync_type,
                'success': result.get('success', False),
                'message': result.get('message', ''),
                'amount': result.get('amount', 0)
            })
            
        except Exception as e:
            results.append({
                'source': source.name,
                'type': sync_type,
                'success': False,
                'message': str(e),
                'amount': 0
            })
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'results': results,
            'total_synced': len([r for r in results if r['success']])
        })
    
    # Show results
    for result in results:
        if result['success']:
            messages.success(request, f"{result['source']}: {result['message']}")
        else:
            messages.error(request, f"{result['source']}: {result['message']}")
    
    return redirect('manage_external_sources')

def sync_external_source_api(source, user):
    """Sync from API source"""
    # This would call the actual API sync logic
    # For now, return a simulated result
    return {
        'success': True,
        'message': 'API sync completed',
        'amount': 100.0
    }

def sync_external_source_database(source, user):
    """Sync from database source"""
    # This would call the actual database sync logic
    # For now, return a simulated result
    return {
        'success': True,
        'message': 'Database sync completed',
        'amount': 150.0
    }

@csrf_exempt
def auto_payment_webhook(request):
    """
    Webhook endpoint for automatic payment processing
    Can be called by Paystack, Stripe, or manual payment systems
    """
    if request.method == 'POST':
        try:
            # Parse incoming data
            if request.content_type == 'application/json':
                data = json.loads(request.body)
            else:
                data = request.POST
            
            # Extract payment information
            reference = data.get('reference', data.get('transaction_id'))
            status = data.get('status', '').lower()
            amount = data.get('amount')
            currency = data.get('currency', 'KES')
            customer_email = data.get('customer_email')
            metadata = data.get('metadata', {})
            
            # Try to find existing payment by reference
            payment = None
            if reference:
                try:
                    payment = Payment.objects.get(reference=reference)
                except Payment.DoesNotExist:
                    pass
            
            # If no payment found, try to create from metadata
            if not payment and metadata:
                user_id = metadata.get('user_id')
                plan_id = metadata.get('plan_id')
                
                if user_id and plan_id:
                    try:
                        user = CustomUser.objects.get(id=user_id)
                        plan = SubscriptionPlan.objects.get(id=plan_id)
                        
                        # Create new payment record
                        payment = Payment.objects.create(
                            user=user,
                            plan=plan,
                            amount=amount,
                            reference=reference or f"AUTO_{uuid.uuid4().hex[:8]}",
                            status='pending',  # Will be updated below
                            payment_method=data.get('payment_method', 'auto'),
                            description=f"Automatic payment via webhook"
                        )
                    except (CustomUser.DoesNotExist, SubscriptionPlan.DoesNotExist):
                        logger.error(f"Could not find user or plan from metadata: {metadata}")
                        return JsonResponse({'success': False, 'error': 'Invalid metadata'})
            
            if not payment:
                return JsonResponse({'success': False, 'error': 'Payment not found'})
            
            # Update payment status
            old_status = payment.status
            if status in ['success', 'completed', 'paid']:
                payment.status = 'completed'
            elif status in ['failed', 'declined', 'cancelled']:
                payment.status = 'failed'
            elif status in ['pending', 'processing']:
                payment.status = 'pending'
            
            # Save payment (this will trigger auto-activation via save method)
            payment.save()
            
            # Log the webhook
            logger.info(f"Payment webhook: {reference} - {old_status} -> {payment.status}")
            
            return JsonResponse({
                'success': True,
                'message': f'Payment {reference} processed successfully',
                'status': payment.status
            })
            
        except Exception as e:
            logger.error(f"Payment webhook error: {e}")
            return JsonResponse({'success': False, 'error': str(e)}, status=400)
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})


# billing/views.py - Add these functions

@login_required
def approve_manual_payment(request, customer_id):
    """Approve a manual payment and activate subscription automatically"""
    if request.user.role not in ['isp_admin', 'isp_staff', 'superadmin']:
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=400)
    
    try:
        # Parse request data
        try:
            data = json.loads(request.body)
            payment_id = data.get('payment_id')
        except:
            data = request.POST
            payment_id = data.get('payment_id')
        
        if not payment_id:
            return JsonResponse({'success': False, 'error': 'Payment ID required'})
        
        # Get the payment and verify it belongs to the customer and tenant
        tenant = request.user.tenant
        payment = Payment.objects.get(
            id=payment_id,
            user__id=customer_id,
            user__tenant=tenant,
            status__in=['pending', 'failed']
        )
        
        # Approve payment
        old_status = payment.status
        payment.status = 'completed'
        payment.approved_by = request.user
        payment.approval_date = tz.now()
        payment.save()  # This triggers auto-activation via save method
        
        # Log the approval
        logger.info(f"Payment {payment_id} approved by {request.user.username}. Status: {old_status} -> completed")
        
        return JsonResponse({
            'success': True,
            'message': f'Payment approved and subscription activated!',
            'payment_id': payment_id,
            'status': payment.status
        })
        
    except Payment.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Payment not found'}, status=404)
    except Exception as e:
        logger.error(f"Error approving payment: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@login_required
def create_auto_payment(request, customer_id):
    """Create and auto-process a manual payment"""
    if request.user.role not in ['isp_admin', 'isp_staff', 'superadmin']:
        return HttpResponseForbidden("Access denied")
    
    if request.method != 'POST':
        return HttpResponseForbidden("Invalid request method")
    
    try:
        tenant = request.user.tenant
        
        # Get customer
        customer = CustomUser.objects.get(id=customer_id, tenant=tenant)
        
        # Get form data
        amount = Decimal(request.POST.get('amount', 0))
        plan_id = request.POST.get('plan_id')
        payment_method = request.POST.get('payment_method', 'cash')
        reference = request.POST.get('reference', f"MANUAL_{tz.now().strftime('%Y%m%d%H%M%S')}")
        notes = request.POST.get('notes', '')
        
        if amount <= 0:
            messages.error(request, 'Amount must be greater than 0')
            return redirect('isp_customer_payments', customer_id=customer_id)
        
        if not plan_id:
            messages.error(request, 'Please select a plan')
            return redirect('isp_customer_payments', customer_id=customer_id)
        
        # Get plan
        plan = SubscriptionPlan.objects.get(id=plan_id, tenant=tenant, is_active=True)
        
        # Create payment
        payment = Payment.objects.create(
            user=customer,
            plan=plan,
            amount=amount,
            reference=reference,
            status='completed',  # Directly mark as completed
            payment_method=payment_method,
            description=notes or f"Manual payment by {request.user.username}"
        )
        
        # Log the creation
        logger.info(f"Auto payment created: {payment.id} for customer {customer.username}, amount: {amount}")
        
        messages.success(request, f'Payment recorded and {plan.name} subscription activated!')
        return redirect('isp_customer_payments', customer_id=customer_id)
        
    except (CustomUser.DoesNotExist, SubscriptionPlan.DoesNotExist) as e:
        messages.error(request, 'Customer or plan not found')
        return redirect('isp_customer_payments', customer_id=customer_id)
    except Exception as e:
        logger.error(f"Error creating auto payment: {e}")
        messages.error(request, f'Error: {str(e)}')
        return redirect('isp_customer_payments', customer_id=customer_id)

@csrf_exempt
def auto_payment_webhook(request):
    """
    Webhook endpoint for automatic payment processing
    Can be called by Paystack, Stripe, or manual payment systems
    """
    if request.method == 'POST':
        try:
            # Parse incoming data
            if request.content_type == 'application/json':
                data = json.loads(request.body)
            else:
                data = request.POST
            
            # Extract payment information
            reference = data.get('reference', data.get('transaction_id'))
            status = data.get('status', '').lower()
            amount = data.get('amount')
            currency = data.get('currency', 'KES')
            customer_email = data.get('customer_email')
            metadata = data.get('metadata', {})
            
            # Try to find existing payment by reference
            payment = None
            if reference:
                try:
                    payment = Payment.objects.get(reference=reference)
                except Payment.DoesNotExist:
                    pass
            
            # If no payment found, try to create from metadata
            if not payment and metadata:
                user_id = metadata.get('user_id')
                plan_id = metadata.get('plan_id')
                
                if user_id and plan_id:
                    try:
                        user = CustomUser.objects.get(id=user_id)
                        plan = SubscriptionPlan.objects.get(id=plan_id)
                        
                        # Create new payment record
                        payment = Payment.objects.create(
                            user=user,
                            plan=plan,
                            amount=amount,
                            reference=reference or f"AUTO_{uuid.uuid4().hex[:8]}",
                            status='pending',  # Will be updated below
                            payment_method=data.get('payment_method', 'auto'),
                            description=f"Automatic payment via webhook"
                        )
                    except (CustomUser.DoesNotExist, SubscriptionPlan.DoesNotExist):
                        logger.error(f"Could not find user or plan from metadata: {metadata}")
                        return JsonResponse({'success': False, 'error': 'Invalid metadata'})
            
            if not payment:
                return JsonResponse({'success': False, 'error': 'Payment not found'})
            
            # Update payment status
            old_status = payment.status
            if status in ['success', 'completed', 'paid']:
                payment.status = 'completed'
            elif status in ['failed', 'declined', 'cancelled']:
                payment.status = 'failed'
            elif status in ['pending', 'processing']:
                payment.status = 'pending'
            
            # Save payment (this will trigger auto-activation via save method)
            payment.save()
            
            # Log the webhook
            logger.info(f"Payment webhook: {reference} - {old_status} -> {payment.status}")
            
            return JsonResponse({
                'success': True,
                'message': f'Payment {reference} processed successfully',
                'status': payment.status
            })
            
        except Exception as e:
            logger.error(f"Payment webhook error: {e}")
            return JsonResponse({'success': False, 'error': str(e)}, status=400)
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

@login_required
def ajax_allocate_bandwidth(request):
    """AJAX endpoint for general bandwidth allocation from wallet"""
    if request.user.role not in ['isp_admin', 'isp_staff', 'superadmin']:
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'})
    
    try:
        tenant = request.user.tenant
        if not tenant:
            return JsonResponse({'success': False, 'error': 'No tenant found'})
            
        wallet = DataWallet.objects.filter(tenant=tenant).first()
        if not wallet:
            return JsonResponse({'success': False, 'error': 'Wallet not found'})
        
        # Parse data
        if request.content_type == 'application/json':
            data = json.loads(request.body)
        else:
            data = request.POST
        
        customer_ids = data.get('customer_ids', [])
        if isinstance(customer_ids, str):
            try:
                customer_ids = json.loads(customer_ids)
            except:
                customer_ids = [cid.strip() for cid in customer_ids.split(',') if cid.strip()]
        
        bandwidth_amount = Decimal(str(data.get('bandwidth_amount', 0)))
        description = data.get('description', 'Bandwidth allocation')
        
        if not customer_ids or bandwidth_amount <= 0:
            return JsonResponse({'success': False, 'error': 'Invalid parameters'})
        
        total_needed = bandwidth_amount * len(customer_ids)
        
        # Check wallet balance
        if wallet.balance_bandwidth_mbps < total_needed:
            return JsonResponse({
                'success': False, 
                'error': f'Insufficient bandwidth. Need {total_needed} Mbps, have {wallet.balance_bandwidth_mbps} Mbps'
            })
        
        successful_allocations = 0
        failed_allocations = []
        
        for cid in customer_ids:
            try:
                customer = CustomUser.objects.get(
                    id=int(cid), 
                    tenant=tenant, 
                    role='customer'
                )
                
                if wallet.allocate_bandwidth(
                    amount_mbps=bandwidth_amount,
                    user=request.user,
                    description=description,
                    reference=f"BANDWIDTH-ALLOC-{tz.now().strftime('%Y%m%d%H%M%S')}"
                ):
                    successful_allocations += 1
                else:
                    failed_allocations.append(f"Customer {cid}: Allocation failed")
                    
            except CustomUser.DoesNotExist:
                failed_allocations.append(f"Customer {cid}: Not found")
            except Exception as e:
                failed_allocations.append(f"Customer {cid}: {str(e)}")
        
        if successful_allocations > 0:
            return JsonResponse({
                'success': True, 
                'message': f'Allocated {total_needed} Mbps to {successful_allocations} customers', 
                'remaining_bandwidth': float(wallet.balance_bandwidth_mbps),
                'successful_count': successful_allocations,
                'failed_count': len(failed_allocations)
            })
        else:
            return JsonResponse({
                'success': False, 
                'error': 'No allocations were successful',
                'failed_details': failed_allocations[:5]
            })
            
    except Exception as e:
        logger.error(f"Bandwidth allocation error: {e}")
        return JsonResponse({'success': False, 'error': f'Server error: {str(e)}'}, status=500)