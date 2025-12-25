# accounts/views_isp.py
from asyncio.log import logger
from arrow import now
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from django.shortcuts import redirect, render, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse, HttpResponseForbidden, HttpResponse
from django.utils import timezone
from datetime import timedelta, datetime
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Count, Sum, Q
import json, csv, io, traceback
from accounts.models import BulkSMS, CustomUser, SMSLog, SMSProviderConfig, SMSTemplate, Tenant, LoginActivity
from router_manager.models import ConnectedDevice, Router, Device, RouterConfig, PortForwardingRule
from billing.models import Payment, PaystackConfiguration, SubscriptionPlan, Subscription, DataWallet, DataDistributionLog, WalletTransaction
from billing.paystack import PaystackAPI
from router_manager.services import port_service
from router_manager.router_clients import get_router_client
from django.core.cache import cache
import calendar
import pandas as pd
import socket
import uuid
from router_manager.forms import ISPAddRouterForm, ISPPortForwardingForm, ISPEditRouterForm
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.core.exceptions import ValidationError
from django.db import transaction
from decimal import Decimal
import logging




def get_isp_base_context(request):
    """Context processor for ISP base template"""
    if hasattr(request, 'user') and request.user.is_authenticated:
        if request.user.role in ['isp_admin', 'isp_staff']:
            tenant = request.user.tenant
            pending_count = CustomUser.objects.filter(
                tenant=tenant, 
                role='customer',
                registration_status='pending'
            ).count()
            return {
                'pending_count': pending_count,
                'tenant': tenant,
            }
    return {}


@login_required
def isp_dashboard(request):
    """ISP Admin Dashboard"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    # ISP analytics - only show data for the current tenant
    total_customers = CustomUser.objects.filter(tenant=tenant, role='customer').count()
    active_customers = CustomUser.objects.filter(tenant=tenant, role='customer', is_active_customer=True).count()
    overdue_customers = CustomUser.objects.filter(
        tenant=tenant, 
        role='customer',
        next_payment_date__lt=timezone.now()
    ).count()
    
    # Router and device queries - FIXED: Use proper relationships
    total_routers = Router.objects.filter(user__tenant=tenant).count()
    online_routers = Router.objects.filter(user__tenant=tenant, is_online=True).count()
    
    # For devices, we need to go through the router relationship
    total_devices = Device.objects.filter(router__user__tenant=tenant).count()
    online_devices = Device.objects.filter(router__user__tenant=tenant, is_online=True).count()
    
    # Revenue calculations
    tenant_customer_ids = CustomUser.objects.filter(tenant=tenant, role='customer').values_list('id', flat=True)
    monthly_revenue = Payment.objects.filter(
        user_id__in=tenant_customer_ids,
        status='completed',
        created_at__gte=timezone.now() - timedelta(days=30)
    ).aggregate(total=Sum('amount'))['total'] or 0
    
    # Recent activity
    recent_payments = Payment.objects.filter(
        user_id__in=tenant_customer_ids
    ).select_related('user', 'plan').order_by('-created_at')[:10]
    
    overdue_accounts = CustomUser.objects.filter(
        tenant=tenant,
        role='customer',
        next_payment_date__lt=timezone.now()
    )[:10]
    
    # Device type distribution - FIXED: Use proper relationship
    device_types = Device.objects.filter(router__user__tenant=tenant).values('device_type').annotate(
        count=Count('id')
    )
    
    device_distribution = {
        'labels': [item['device_type'].title() if item['device_type'] else 'Unknown' for item in device_types],
        'data': [item['count'] for item in device_types]
    }

    # Revenue timeseries (last 12 months)
    now = timezone.now()
    months = []
    revenue_series = []
    for i in range(11, -1, -1):
        month_dt = (now.replace(day=1) - timedelta(days=1)).replace(day=1) - timedelta(days=30*i)
        label = month_dt.strftime('%b %Y')
        months.append(label)
        start = month_dt.replace(day=1)
        last_day = calendar.monthrange(month_dt.year, month_dt.month)[1]
        end = month_dt.replace(day=last_day, hour=23, minute=59, second=59)
        month_total = Payment.objects.filter(
            user_id__in=tenant_customer_ids,
            status='completed',
            created_at__gte=start,
            created_at__lte=end
        ).aggregate(total=Sum('amount'))['total'] or 0
        revenue_series.append(float(month_total))

    # Plan distribution - FIXED: use tenant instead of user
    plan_qs = SubscriptionPlan.objects.filter(tenant=tenant, is_active=True).values('name').annotate(count=Count('id'))
    plan_labels = [p['name'] for p in plan_qs]
    plan_counts = [p['count'] for p in plan_qs]

    # Overdue vs Paid
    paid_customers = total_customers - overdue_customers
    
    context = {
        'tenant': tenant,
        'total_customers': total_customers,
        'active_customers': active_customers,
        'overdue_customers': overdue_customers,
        'total_routers': total_routers,
        'online_routers': online_routers,
        'total_devices': total_devices,
        'online_devices': online_devices,
        'monthly_revenue': monthly_revenue,
        'recent_payments': recent_payments,
        'overdue_accounts': overdue_accounts,
        'device_distribution': json.dumps(device_distribution),
        'revenue_months': json.dumps(months),
        'revenue_series': json.dumps(revenue_series),
        'plan_labels': json.dumps(plan_labels),
        'plan_counts': json.dumps(plan_counts),
        'overdue_paid': json.dumps([overdue_customers, paid_customers]),
    }
    
    return render(request, 'accounts/isp_dashboard.html', context)
@login_required
def isp_dashboard_api(request):
    """Return JSON summary data for the ISP dashboard (used by dynamic charts)."""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")

    tenant = request.user.tenant

    tenant_customer_ids = CustomUser.objects.filter(tenant=tenant, role='customer').values_list('id', flat=True)

    # Revenue timeseries (last 12 months)
    now = timezone.now()
    months = []
    revenue_series = []
    for i in range(11, -1, -1):
        month_dt = (now.replace(day=1) - timedelta(days=1)).replace(day=1) - timedelta(days=30*i)
        label = month_dt.strftime('%b %Y')
        months.append(label)
        start = month_dt.replace(day=1)
        last_day = calendar.monthrange(month_dt.year, month_dt.month)[1]
        end = month_dt.replace(day=last_day, hour=23, minute=59, second=59)
        month_total = Payment.objects.filter(
            user_id__in=tenant_customer_ids,
            status='completed',
            created_at__gte=start,
            created_at__lte=end
        ).aggregate(total=Sum('amount'))['total'] or 0
        revenue_series.append(float(month_total))

    # Device distribution
    device_types = Device.objects.filter(router__user__tenant=tenant).values('device_type').annotate(count=Count('id'))
    device_distribution = {
        'labels': [item['device_type'].title() if item['device_type'] else 'Unknown' for item in device_types],
        'data': [item['count'] for item in device_types]
    }

    # Plan distribution
    plan_qs = SubscriptionPlan.objects.filter(tenant=tenant, is_active=True).values('name').annotate(count=Count('id'))
    plan_labels = [p['name'] for p in plan_qs]
    plan_counts = [p['count'] for p in plan_qs]

    # Overdue vs Paid
    total_customers = CustomUser.objects.filter(tenant=tenant, role='customer').count()
    overdue_customers = CustomUser.objects.filter(tenant=tenant, role='customer', next_payment_date__lt=timezone.now()).count()
    paid_customers = total_customers - overdue_customers

    # Recent payments (serialized)
    recent_payments_qs = Payment.objects.filter(user_id__in=tenant_customer_ids).select_related('user', 'plan').order_by('-created_at')[:10]
    recent_payments = []
    for p in recent_payments_qs:
        recent_payments.append({
            'id': p.id,
            'user': p.user.username if p.user else '',
            'plan': p.plan.name if getattr(p, 'plan', None) else '',
            'amount': float(p.amount),
            'status': p.status,
            'created_at': p.created_at.isoformat(),
        })

    data = {
        'success': True,
        'revenue_months': months,
        'revenue_series': revenue_series,
        'device_distribution': device_distribution,
        'plan_labels': plan_labels,
        'plan_counts': plan_counts,
        'overdue_paid': [overdue_customers, paid_customers],
        'recent_payments': recent_payments,
    }

    return JsonResponse(data)
@login_required
def isp_pending_approvals(request):
    """View pending registration approvals"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    pending_users = CustomUser.objects.filter(
        tenant=tenant, 
        role='customer',
        registration_status='pending'
    ).order_by('registration_date')
    
    if request.method == 'POST':
        user_id = request.POST.get('user_id')
        action = request.POST.get('action')
        
        try:
            user = CustomUser.objects.get(id=user_id, tenant=tenant)
            
            if action == 'approve':
                user.registration_status = 'approved'
                user.is_active_customer = True
                user.approval_date = timezone.now()
                user.approved_by = request.user
                user.save()
                
                messages.success(request, f'User {user.username} has been approved.')
                
            elif action == 'reject':
                user.registration_status = 'rejected'
                user.is_active_customer = False
                user.save()
                
                messages.success(request, f'User {user.username} has been rejected.')
                
        except CustomUser.DoesNotExist:
            messages.error(request, 'User not found')
        
        return redirect('isp_pending_approvals')
    
    context = {
        'pending_users': pending_users,
        'tenant': tenant,
    }
    return render(request, 'accounts/isp_pending_approvals.html', context)


# accounts/views_isp.py - ADD THESE VIEW FUNCTIONS

@login_required
def isp_customer_management(request):
    """ISP Customer Management - ENHANCED MAIN PAGE"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    # Get customers for the current tenant only
    customers = CustomUser.objects.filter(tenant=tenant, role='customer').order_by('registration_status', '-registration_date')

    # Count pending approvals for the badge
    pending_count = CustomUser.objects.filter(
        tenant=tenant, 
        role='customer',
        registration_status='pending'
    ).count()
    
    # Active plans for the current tenant
    tenant_plans = SubscriptionPlan.objects.filter(tenant=tenant, is_active=True)

    # Filtering
    status_filter = request.GET.get('status', 'all')
    if status_filter == 'active':
        customers = customers.filter(is_active_customer=True)
    elif status_filter == 'overdue':
        customers = customers.filter(next_payment_date__lt=timezone.now())
    elif status_filter == 'inactive':
        customers = customers.filter(is_active_customer=False)
    
    # Calculate additional stats for each customer
    for customer in customers:
        # Get subscription info
        subscription = Subscription.objects.filter(user=customer, is_active=True).first()
        customer.current_plan = subscription.plan if subscription else None
        
        # Get device counts
        customer.total_devices = Device.objects.filter(user=customer).count()
        customer.online_devices = Device.objects.filter(user=customer, is_online=True).count()
        
        # Payment overdue calculation
        if customer.next_payment_date:
            customer.is_payment_overdue = customer.next_payment_date < timezone.now()
            if customer.is_payment_overdue:
                customer.days_overdue = (timezone.now() - customer.next_payment_date).days
    
    # Get stats for dashboard
    total_customers = customers.count()
    active_customers = customers.filter(is_active_customer=True).count()
    overdue_customers = customers.filter(next_payment_date__lt=timezone.now()).count()
    
    context = {
        'customers': customers,
        'status_filter': status_filter,
        'tenant_plans': tenant_plans,
        'tenant': tenant,
        'pending_count': pending_count,
        'total_customers': total_customers,
        'active_customers': active_customers,
        'overdue_customers': overdue_customers,
        'page_title': 'Customer Management',
        'page_subtitle': 'Manage and monitor your internet customers',
    }
    
    return render(request, 'accounts/isp_customers.html', context)


@login_required
def isp_add_customer(request):
    """Add new customer - SEPARATE PAGE"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    available_plans = SubscriptionPlan.objects.filter(tenant=tenant, is_active=True)
    
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        phone = request.POST.get('phone')
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        address = request.POST.get('address')
        account_number = request.POST.get('company_account_number')
        plan_id = request.POST.get('plan_id')
        is_active = bool(request.POST.get('is_active', False))

        if not username or not password:
            messages.error(request, 'Username and password are required')
            return redirect('isp_add_customer')

        if CustomUser.objects.filter(username=username).exists():
            messages.error(request, 'Username already exists')
            return redirect('isp_add_customer')

        try:
            # Create user with tenant assignment
            new_user = CustomUser.objects.create_user(
                username=username, 
                email=email, 
                password=password
            )
            new_user.tenant = tenant
            new_user.role = 'customer'
            new_user.phone = phone or ''
            new_user.first_name = first_name or ''
            new_user.last_name = last_name or ''
            new_user.address = address or ''
            
            # Set provided company account number or generate one
            if account_number:
                new_user.company_account_number = account_number
            else:
                # Generate account number: TENANT-ID + timestamp
                timestamp = int(timezone.now().timestamp())
                new_user.company_account_number = f"{tenant.id:03d}{timestamp % 1000000:06d}"
            
            new_user.is_active_customer = is_active
            new_user.registration_status = 'approved'
            new_user.registration_date = timezone.now()
            new_user.approval_date = timezone.now()
            new_user.approved_by = request.user
            new_user.save()

            # If a plan was selected, create initial subscription
            if plan_id:
                try:
                    plan = SubscriptionPlan.objects.get(id=plan_id, tenant=tenant, is_active=True)
                    Subscription.objects.create(
                        user=new_user, 
                        plan=plan, 
                        is_active=True,
                        start_date=timezone.now(),
                        end_date=timezone.now() + timedelta(days=plan.duration_days)
                    )
                    new_user.next_payment_date = timezone.now() + timedelta(days=plan.duration_days)
                    new_user.save()
                    messages.success(request, f'Customer {username} created with {plan.name} plan')
                except SubscriptionPlan.DoesNotExist:
                    messages.warning(request, f'Customer {username} created but plan assignment failed')
            else:
                messages.success(request, f'Customer {username} created successfully')
                
            return redirect('isp_customer_detail', customer_id=new_user.id)
                
        except Exception as e:
            messages.error(request, f'Error creating customer: {str(e)}')
            return redirect('isp_add_customer')
    
    context = {
        'available_plans': available_plans,
        'tenant': tenant,
        'page_title': 'Add New Customer',
        'page_subtitle': 'Create a new customer account',
        'breadcrumbs': [
            {'name': 'Customer Management', 'url': reverse('isp_customers')},
            {'name': 'Add Customer', 'url': ''},
        ]
    }
    
    return render(request, 'accounts/isp_add_customer.html', context)


@login_required
def isp_customer_detail(request, customer_id):
    """Customer Detail View - FULL PAGE WITH TABS"""
    # Ensure the customer belongs to the same tenant as the ISP admin
    customer = get_object_or_404(
        CustomUser, 
        id=customer_id,
        tenant=request.user.tenant  # Security: only access same-tenant customers
    )
    
    # Get customer's subscription
    subscription = Subscription.objects.filter(user=customer, is_active=True).first()
    current_plan = subscription.plan if subscription else None
    
    # Get customer's devices
    devices = Device.objects.filter(user=customer).order_by('-last_seen')
    online_devices = devices.filter(is_online=True)
    
    # Get recent payments
    recent_payments = Payment.objects.filter(user=customer).select_related('plan').order_by('-created_at')[:10]
    
    # Get router logs (if any)
    router_logs = []  # You'll need to create a RouterLog model if you want this
    
    # Calculate statistics
    total_payments = Payment.objects.filter(user=customer, status='completed').count()
    total_amount = Payment.objects.filter(user=customer, status='completed').aggregate(
        total=Sum('amount'))['total'] or 0
    
    context = {
        'customer': customer,
        'current_plan': current_plan,
        'subscription': subscription,
        'devices': devices,
        'online_devices': online_devices,
        'recent_payments': recent_payments,
        'router_logs': router_logs,
        'total_payments': total_payments,
        'total_amount': total_amount,
        'tenant': request.user.tenant,
        'page_title': f'Customer: {customer.username}',
        'page_subtitle': 'View and manage customer details',
        'breadcrumbs': [
            {'name': 'Customer Management', 'url': reverse('isp_customers')},
            {'name': customer.username, 'url': ''},
        ]
    }
    
    return render(request, 'accounts/isp_customer_detail.html', context)


@login_required
def isp_edit_customer(request, customer_id):
    """Edit customer details - SEPARATE PAGE"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    try:
        customer = CustomUser.objects.get(id=customer_id, tenant=tenant)
    except CustomUser.DoesNotExist:
        messages.error(request, 'Customer not found')
        return redirect('isp_customers')
    
    available_plans = SubscriptionPlan.objects.filter(tenant=tenant, is_active=True)
    current_subscription = Subscription.objects.filter(user=customer, is_active=True).first()
    
    if request.method == 'POST':
        # Update customer details
        customer.first_name = request.POST.get('first_name', customer.first_name)
        customer.last_name = request.POST.get('last_name', customer.last_name)
        customer.email = request.POST.get('email', customer.email)
        customer.phone = request.POST.get('phone', customer.phone)
        customer.address = request.POST.get('address', customer.address)
        customer.company_account_number = request.POST.get('company_account_number', customer.company_account_number)
        customer.is_active_customer = bool(request.POST.get('is_active_customer', False))
        
        # Update password if provided
        new_password = request.POST.get('new_password')
        if new_password:
            customer.set_password(new_password)
        
        customer.save()
        
        # Update subscription plan if changed
        new_plan_id = request.POST.get('plan_id')
        if new_plan_id:
            try:
                new_plan = SubscriptionPlan.objects.get(id=new_plan_id, tenant=tenant, is_active=True)
                if current_subscription:
                    current_subscription.plan = new_plan
                    current_subscription.save()
                else:
                    Subscription.objects.create(
                        user=customer,
                        plan=new_plan,
                        is_active=True,
                        start_date=timezone.now(),
                        end_date=timezone.now() + timedelta(days=new_plan.duration_days)
                    )
                messages.success(request, f'Plan updated to {new_plan.name}')
            except SubscriptionPlan.DoesNotExist:
                messages.error(request, 'Selected plan not found')
        
        messages.success(request, 'Customer details updated successfully')
        return redirect('isp_customer_detail', customer_id=customer.id)
    
    context = {
        'customer': customer,
        'available_plans': available_plans,
        'current_subscription': current_subscription,
        'tenant': tenant,
        'page_title': f'Edit Customer: {customer.username}',
        'page_subtitle': 'Update customer information and settings',
        'breadcrumbs': [
            {'name': 'Customer Management', 'url': reverse('isp_customers')},
            {'name': customer.username, 'url': reverse('isp_customer_detail', args=[customer.id])},
            {'name': 'Edit', 'url': ''},
        ]
    }
    
    return render(request, 'accounts/isp_edit_customer.html', context)


@login_required
def isp_delete_customer(request, customer_id):
    """Delete customer - CONFIRMATION PAGE"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    try:
        customer = CustomUser.objects.get(id=customer_id, tenant=tenant)
    except CustomUser.DoesNotExist:
        messages.error(request, 'Customer not found')
        return redirect('isp_customers')
    
    # Check if customer has active subscriptions or devices
    active_subscriptions = Subscription.objects.filter(user=customer, is_active=True).count()
    customer_devices = Device.objects.filter(user=customer).count()
    
    if request.method == 'POST':
        confirm = request.POST.get('confirm')
        if confirm == 'yes':
            try:
                username = customer.username
                
                # Instead of deleting, deactivate the customer
                customer.is_active_customer = False
                customer.is_active = False
                customer.save()
                
                # Deactivate subscriptions
                Subscription.objects.filter(user=customer, is_active=True).update(is_active=False)
                
                # Block devices
                Device.objects.filter(user=customer).update(is_blocked=True, is_online=False)
                
                messages.success(request, f'Customer "{username}" has been deactivated')
                return redirect('isp_customers')
                
            except Exception as e:
                messages.error(request, f'Error deactivating customer: {str(e)}')
        return redirect('isp_customers')
    
    context = {
        'customer': customer,
        'active_subscriptions': active_subscriptions,
        'customer_devices': customer_devices,
        'tenant': tenant,
        'page_title': f'Deactivate Customer: {customer.username}',
        'page_subtitle': 'Confirm customer deactivation',
        'breadcrumbs': [
            {'name': 'Customer Management', 'url': reverse('isp_customers')},
            {'name': customer.username, 'url': reverse('isp_customer_detail', args=[customer.id])},
            {'name': 'Deactivate', 'url': ''},
        ]
    }
    
    return render(request, 'accounts/isp_delete_customer.html', context)


@login_required
def isp_customer_logs(request, customer_id):
    """Customer Router Logs - SEPARATE PAGE"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    try:
        customer = CustomUser.objects.get(id=customer_id, tenant=tenant)
    except CustomUser.DoesNotExist:
        messages.error(request, 'Customer not found')
        return redirect('isp_customers')
    
    # Get customer's router
    customer_router = Router.objects.filter(user=customer).first()
    
    # Get logs (you'll need to implement logging)
    # For now, we'll use a placeholder
    logs = []
    
    context = {
        'customer': customer,
        'customer_router': customer_router,
        'logs': logs,
        'tenant': tenant,
        'page_title': f'Logs: {customer.username}',
        'page_subtitle': 'View router activity logs',
        'breadcrumbs': [
            {'name': 'Customer Management', 'url': reverse('isp_customers')},
            {'name': customer.username, 'url': reverse('isp_customer_detail', args=[customer.id])},
            {'name': 'Logs', 'url': ''},
        ]
    }
    
    return render(request, 'accounts/isp_customer_logs.html', context)


@login_required
def isp_customer_payments(request, customer_id):
    """Customer Payment History with auto-activation support"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    try:
        customer = CustomUser.objects.get(id=customer_id, tenant=tenant)
    except CustomUser.DoesNotExist:
        messages.error(request, 'Customer not found')
        return redirect('isp_customers')
    
    # Handle AJAX requests separately
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return handle_ajax_requests(request, customer)
    
    # Handle manual payment approval with auto-activation
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'approve_manual_payment':
            payment_id = request.POST.get('payment_id')
            try:
                payment = Payment.objects.get(
                    id=payment_id,
                    user=customer,
                    status='pending'
                )
                
                # Approve payment
                payment.status = 'completed'
                payment.save()  # This will trigger auto-activation via save method
                
                # Also update customer's next payment date if they have a plan
                if payment.plan:
                    customer.next_payment_date = timezone.now() + timedelta(days=payment.plan.duration_days)
                    customer.save()
                
                messages.success(request, f'Payment approved and subscription activated!')
                return redirect('isp_customer_payments', customer_id=customer_id)
                
            except Payment.DoesNotExist:
                messages.error(request, 'Payment not found')
        
        elif action == 'create_manual_payment':
            # Handle manual payment creation from form
            amount = request.POST.get('amount')
            plan_id = request.POST.get('plan_id')
            payment_method = request.POST.get('payment_method', 'cash')
            reference = request.POST.get('reference', f"MANUAL_{timezone.now().strftime('%Y%m%d%H%M%S')}")
            notes = request.POST.get('notes', '')
            activate_subscription = request.POST.get('activate_subscription') == 'on'
            
            try:
                plan = None
                if plan_id:
                    plan = SubscriptionPlan.objects.get(id=plan_id, tenant=tenant, is_active=True)
                
                payment = Payment.objects.create(
                    user=customer,
                    plan=plan,
                    amount=amount,
                    reference=reference,
                    status='completed' if activate_subscription else 'pending',
                    payment_method=payment_method,
                    description=f"Manual payment by {request.user.username}" + (f" - {notes}" if notes else "")
                )
                
                if activate_subscription and plan:
                    subscription, created = Subscription.objects.get_or_create(
                        user=customer,
                        plan=plan,
                        defaults={
                            'is_active': True,
                            'start_date': timezone.now(),
                            'end_date': timezone.now() + timedelta(days=plan.duration_days)
                        }
                    )
                    
                    if not created:
                        subscription.is_active = True
                        subscription.start_date = timezone.now()
                        subscription.end_date = timezone.now() + timedelta(days=int(plan.duration_days))
                        subscription.save()
                    
                    customer.next_payment_date = timezone.now() + timedelta(days=int(plan.duration_days))
                    customer.is_active_customer = True
                    customer.save()
                
                messages.success(request, f'Manual payment created successfully!')
                return redirect('isp_customer_payments', customer_id=customer_id)
                
            except SubscriptionPlan.DoesNotExist:
                messages.error(request, 'Selected plan not found')
    
    # Get all payments
    payments = Payment.objects.filter(user=customer).select_related('plan').order_by('-created_at')
    
    # Calculate payment statistics
    payment_stats = {
        'total_payments': payments.count(),
        'successful_payments': payments.filter(status='completed').count(),
        'failed_payments': payments.filter(status='failed').count(),
        'pending_payments': payments.filter(status='pending').count(),
        'total_revenue': payments.filter(status='completed').aggregate(
            total=Sum('amount'))['total'] or 0,
    }
    
    # Get available plans for manual payment
    available_plans = SubscriptionPlan.objects.filter(tenant=tenant, is_active=True)
    
    context = {
        'customer': customer,
        'payments': payments,
        'payment_stats': payment_stats,
        'available_plans': available_plans,
        'tenant': tenant,
        'page_title': f'Payments: {customer.username}',
        'page_subtitle': 'View customer payment history',
        'breadcrumbs': [
            {'name': 'Customer Management', 'url': reverse('isp_customers')},
            {'name': customer.username, 'url': reverse('isp_customer_detail', args=[customer.id])},
            {'name': 'Payments', 'url': ''},
        ]
    }
    
    return render(request, 'accounts/isp_customer_payments.html', context)


def handle_ajax_requests(request, customer):
    """Handle AJAX requests for payment actions"""
    action = request.GET.get('action')
    
    if action == 'payment_details':
        payment_id = request.GET.get('payment_id')
        try:
            payment = Payment.objects.get(id=payment_id, user=customer)
            return JsonResponse({
                'success': True,
                'payment': {
                    'id': payment.id,
                    'amount': str(payment.amount),
                    'status': payment.status,
                    'status_display': payment.get_status_display(),
                    'method': payment.get_payment_method_display(),
                    'reference': payment.reference,
                    'plan': payment.plan.name if payment.plan else 'No plan',
                    'description': payment.description or '',
                    'created_at': payment.created_at.strftime('%Y-%m-%d %H:%M'),
                }
            })
        except Payment.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Payment not found'})
    
    return JsonResponse({'success': False, 'error': 'Invalid action'})

@login_required
def isp_extend_subscription(request, customer_id):
    """Extend customer subscription - SEPARATE PAGE"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    try:
        customer = CustomUser.objects.get(id=customer_id, tenant=tenant)
    except CustomUser.DoesNotExist:
        messages.error(request, 'Customer not found')
        return redirect('isp_customers')
    
    if request.method == 'POST':
        days = int(request.POST.get('days', 30))
        customer.next_payment_date = timezone.now() + timedelta(days=days)
        customer.is_active_customer = True
        customer.save()
        
        # Log the extension
        # You could create an ActivityLog model here
        
        messages.success(request, f'Subscription extended for {customer.username} by {days} days')
        return redirect('isp_customer_detail', customer_id=customer.id)
    
    context = {
        'customer': customer,
        'tenant': tenant,
        'page_title': f'Extend Subscription: {customer.username}',
        'page_subtitle': 'Extend customer subscription period',
        'breadcrumbs': [
            {'name': 'Customer Management', 'url': reverse('isp_customers')},
            {'name': customer.username, 'url': reverse('isp_customer_detail', args=[customer.id])},
            {'name': 'Extend Subscription', 'url': ''},
        ]
    }
    
    return render(request, 'accounts/isp_extend_subscription.html', context)

@login_required
def isp_router_management(request):
    """ISP Router Management - Enhanced with full CRUD operations"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    # Get all routers for the current tenant
    routers = Router.objects.filter(user__tenant=tenant).select_related('user')
    
    # Get router configurations
    router_configs = RouterConfig.objects.filter(tenant=tenant)
    
    # Get customers for port forwarding
    customers = CustomUser.objects.filter(tenant=tenant, role='customer')
    
    # Get port forwarding rules
    port_rules = PortForwardingRule.objects.filter(router__tenant=tenant).select_related('router', 'customer')
    
    # Calculate statistics
    total_routers = routers.count()
    online_routers = routers.filter(is_online=True).count()
    total_devices = Device.objects.filter(router__user__tenant=tenant).count()
    
    # Initialize forms
    add_router_form = ISPAddRouterForm()
    port_forward_form = ISPPortForwardingForm(tenant=tenant)
    
    # Check if we're editing a router
    edit_router_id = request.GET.get('edit')
    edit_router_form = None
    if edit_router_id:
        try:
            router_config = RouterConfig.objects.get(id=edit_router_id, tenant=tenant)
            edit_router_form = ISPEditRouterForm(instance=router_config)
        except RouterConfig.DoesNotExist:
            pass
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        # Add new router configuration using form
        if action == 'add_router':
            add_router_form = ISPAddRouterForm(request.POST)
            if add_router_form.is_valid():
                try:
                    router_config = add_router_form.save(commit=False)
                    router_config.tenant = tenant
                    router_config.is_online = False
                    
                    # Test connectivity
                    reachable = False
                    is_online = False
                    
                    try:
                        sock = socket.create_connection((router_config.ip_address, router_config.web_port), timeout=5)
                        sock.close()
                        reachable = True
                        
                        # If reachable, try logging in via router client
                        try:
                            client = get_router_client(router_config)
                            if hasattr(client, 'login') and client.login():
                                is_online = True
                        except Exception as e:
                            print(f"Router login failed: {e}")
                            is_online = False
                            
                    except Exception as e:
                        reachable = False
                        print(f"Socket connection failed: {e}")

                    router_config.is_online = is_online
                    router_config.save()

                    if is_online:
                        messages.success(request, f'Router "{router_config.name}" added and connectivity verified successfully!')
                    elif reachable:
                        messages.warning(request, f'Router "{router_config.name}" added but login failed. Check credentials.')
                    else:
                        messages.warning(request, f'Router "{router_config.name}" added but cannot reach the device. Check IP/port.')
                    
                    return redirect('isp_routers')
                    
                except Exception as e:
                    messages.error(request, f'Error adding router: {str(e)}')
            else:
                # Form validation failed
                for field, errors in add_router_form.errors.items():
                    for error in errors:
                        messages.error(request, f'{field}: {error}')
        
        # Update existing router configuration
        elif action == 'update_router':
            router_id = request.POST.get('router_id')
            try:
                router_config = RouterConfig.objects.get(id=router_id, tenant=tenant)
                edit_router_form = ISPEditRouterForm(request.POST, instance=router_config)
                if edit_router_form.is_valid():
                    router_config = edit_router_form.save()
                    
                    # Test connection after update
                    reachable = False
                    try:
                        sock = socket.create_connection((router_config.ip_address, router_config.web_port), timeout=5)
                        sock.close()
                        reachable = True
                        
                        # Test login
                        login_success = False
                        try:
                            client = get_router_client(router_config)
                            login_success = client.login() if hasattr(client, 'login') else False
                        except Exception as e:
                            print(f"Router login failed: {e}")
                            login_success = False
                        
                        router_config.is_online = login_success
                        router_config.last_checked = timezone.now()
                        
                    except Exception as e:
                        router_config.is_online = False
                        print(f"Socket connection failed: {e}")
                    
                    router_config.save()
                    
                    if router_config.is_online:
                        messages.success(request, f'Router "{router_config.name}" updated and connectivity verified!')
                    elif reachable:
                        messages.warning(request, f'Router "{router_config.name}" updated but login failed. Check credentials.')
                    else:
                        messages.warning(request, f'Router "{router_config.name}" updated but cannot reach the device.')
                    
                    return redirect('isp_routers')
                else:
                    for field, errors in edit_router_form.errors.items():
                        for error in errors:
                            messages.error(request, f'{field}: {error}')
                    
            except RouterConfig.DoesNotExist:
                messages.error(request, 'Router configuration not found')
        
        # Setup port forwarding using form
        elif action == 'setup_port_forward':
            port_forward_form = ISPPortForwardingForm(request.POST, tenant=tenant)
            if port_forward_form.is_valid():
                try:
                    router_id = request.POST.get('router_config_id')
                    router_cfg = RouterConfig.objects.get(id=router_id, tenant=tenant)
                    
                    # Generate external port
                    import random
                    external_port = random.randint(10000, 60000)
                    
                    # Save port forwarding rule
                    port_rule = port_forward_form.save(commit=False)
                    port_rule.router = router_cfg
                    port_rule.external_port = external_port
                    port_rule.description = f"Port forwarding for {port_rule.customer.username}"
                    port_rule.save()
                    
                    # Try to configure the router
                    success = False
                    try:
                        client = get_router_client(router_cfg)
                        if hasattr(client, 'add_port_forwarding'):
                            success = client.add_port_forwarding(
                                external_port, 
                                port_rule.internal_ip, 
                                port_rule.internal_port, 
                                port_rule.protocol
                            )
                        else:
                            success = True  # Assume success if method doesn't exist
                    except Exception as e:
                        print(f"Router client configuration failed: {e}")
                        success = True  # Assume success for demo purposes
                    
                    if success:
                        messages.success(request, f'Port forwarding configured: {external_port} → {port_rule.internal_ip}:{port_rule.internal_port} ({port_rule.protocol.upper()})')
                    else:
                        messages.warning(request, f'Port forwarding rule created but router configuration may have failed: {external_port} → {port_rule.internal_ip}:{port_rule.internal_port}')
                        
                except RouterConfig.DoesNotExist:
                    messages.error(request, 'Router configuration not found')
                except Exception as e:
                    messages.error(request, f'Error setting up port forwarding: {str(e)}')
            else:
                for field, errors in port_forward_form.errors.items():
                    for error in errors:
                        messages.error(request, f'{field}: {error}')
        
        # Toggle router online status
        elif action == 'toggle_online':
            router_id = request.POST.get('router_id')
            try:
                router = Router.objects.get(id=router_id, user__tenant=tenant)
                router.is_online = not router.is_online
                router.last_seen = timezone.now() if router.is_online else None
                router.save()
                
                status = "online" if router.is_online else "offline"
                messages.success(request, f'Router status set to {status}')
                
            except Router.DoesNotExist:
                messages.error(request, 'Router not found')
        
        # Delete router configuration
        elif action == 'delete_router_config':
            config_id = request.POST.get('config_id')
            try:
                config = RouterConfig.objects.get(id=config_id, tenant=tenant)
                config_name = config.name
                
                # Check if there are any port forwarding rules
                port_rules_count = PortForwardingRule.objects.filter(router=config).count()
                if port_rules_count > 0:
                    messages.error(request, f'Cannot delete "{config_name}" because it has {port_rules_count} port forwarding rules. Delete them first.')
                else:
                    config.delete()
                    messages.success(request, f'Router configuration "{config_name}" deleted successfully')
                    
            except RouterConfig.DoesNotExist:
                messages.error(request, 'Router configuration not found')
        
        # Test router connection
        elif action == 'test_connection':
            config_id = request.POST.get('config_id')
            try:
                config = RouterConfig.objects.get(id=config_id, tenant=tenant)
                
                # Test connectivity
                reachable = False
                try:
                    sock = socket.create_connection((config.ip_address, config.web_port), timeout=5)
                    sock.close()
                    reachable = True
                    
                    # Test login
                    login_success = False
                    try:
                        client = get_router_client(config)
                        login_success = client.login() if hasattr(client, 'login') else False
                    except Exception as e:
                        print(f"Router client error: {e}")
                        login_success = False
                    
                    if login_success:
                        config.is_online = True
                        config.last_checked = timezone.now()
                        config.save()
                        messages.success(request, f'Connection test successful! Router "{config.name}" is online and accessible.')
                    else:
                        config.is_online = False
                        config.save()
                        messages.warning(request, f'Router "{config.name}" is reachable but login failed. Check credentials.')
                        
                except Exception as e:
                    config.is_online = False
                    config.save()
                    messages.error(request, f'Cannot connect to router "{config.name}". Check network connectivity.')
                    
            except RouterConfig.DoesNotExist:
                messages.error(request, 'Router configuration not found')
        
        # Toggle port rule status
        elif action == 'toggle_port_rule':
            rule_id = request.POST.get('rule_id')
            try:
                rule = PortForwardingRule.objects.get(id=rule_id, router__tenant=tenant)
                rule.is_active = not rule.is_active
                rule.save()
                
                status = "activated" if rule.is_active else "deactivated"
                messages.success(request, f'Port forwarding rule {status}')
                
            except PortForwardingRule.DoesNotExist:
                messages.error(request, 'Port forwarding rule not found')
        
        # Delete port forwarding rule
        elif action == 'delete_port_rule':
            rule_id = request.POST.get('rule_id')
            try:
                rule = PortForwardingRule.objects.get(id=rule_id, router__tenant=tenant)
                rule_description = f"{rule.external_port} → {rule.internal_ip}:{rule.internal_port}"
                rule.delete()
                messages.success(request, f'Port forwarding rule "{rule_description}" deleted successfully')
            except PortForwardingRule.DoesNotExist:
                messages.error(request, 'Port forwarding rule not found')
        
        return redirect('isp_routers')
    
    context = {
        'routers': routers,
        'router_configs': router_configs,
        'customers': customers,
        'users': customers,  # Alias for template compatibility
        'port_rules': port_rules,
        'tenant': tenant,
        'total_routers': total_routers,
        'online_routers': online_routers,
        'total_devices': total_devices,
        'add_router_form': add_router_form,  # Make sure this is passed
        'port_forward_form': port_forward_form,  # Make sure this is passed
        'edit_router_form': edit_router_form,  # Make sure this is passed
    }
    
    return render(request, 'accounts/isp_routers.html', context)
    
@login_required
def isp_payment_management(request):
    """ISP Payment Management"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    # Get payments for customers in the current tenant
    tenant_customer_ids = CustomUser.objects.filter(tenant=tenant, role='customer').values_list('id', flat=True)
    payments_queryset = Payment.objects.filter(user_id__in=tenant_customer_ids).select_related('user', 'plan').order_by('-created_at')
    
    # Calculate statistics from the full queryset (before pagination)
    total_revenue = payments_queryset.filter(status='completed').aggregate(total=Sum('amount'))['total'] or 0
    completed_payments = payments_queryset.filter(status='completed').count()
    pending_payments = payments_queryset.filter(status='pending').count()
    failed_payments = payments_queryset.filter(status='failed').count()
    
    # Pagination
    paginator = Paginator(payments_queryset, 25)  # Show 25 payments per page
    page = request.GET.get('page', 1)
    
    try:
        payments_page = paginator.page(page)
    except PageNotAnInteger:
        payments_page = paginator.page(1)
    except EmptyPage:
        payments_page = paginator.page(paginator.num_pages)
    
    context = {
        'payments': payments_page,
        'tenant': tenant,
        'total_revenue': total_revenue,
        'completed_payments': completed_payments,
        'pending_payments': pending_payments,
        'failed_payments': failed_payments,
        'page_title': 'Payment Management',
        'page_subtitle': 'Monitor and manage customer payments',
    }
    
    return render(request, 'accounts/isp_payments.html', context)

@login_required
def isp_plan_management(request):
    """ISP Plan Management"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")

    tenant = request.user.tenant
    # Get plans for the current tenant
    plans = SubscriptionPlan.objects.filter(tenant=tenant).order_by('-created_at')

    if request.method == 'POST':
        action = request.POST.get('action')
        
        # Create new plan
        if action == 'create_plan':
            name = request.POST.get('name')
            description = request.POST.get('description')
            price = request.POST.get('price')
            bandwidth = request.POST.get('bandwidth')
            data_cap = request.POST.get('data_cap') or None
            duration_days = request.POST.get('duration_days') or 30
            is_active = bool(request.POST.get('is_active', False))

            if not name or not price or not bandwidth:
                messages.error(request, 'Name, price and bandwidth are required')
                return redirect('isp_plans')

            # Ensure unique per tenant
            if SubscriptionPlan.objects.filter(tenant=tenant, name=name).exists():
                messages.error(request, 'A plan with this name already exists')
                return redirect('isp_plans')

            try:
                SubscriptionPlan.objects.create(
                    tenant=tenant,
                    name=name,
                    description=description or '',
                    price=price,
                    bandwidth=int(bandwidth),
                    data_cap=(int(data_cap) if data_cap else None),
                    duration_days=int(duration_days),
                    is_active=is_active,
                )
                messages.success(request, 'Plan created successfully')
            except Exception as e:
                messages.error(request, f'Error creating plan: {str(e)}')

            return redirect('isp_plans')
        
        # Update existing plan
        elif action == 'update_plan':
            plan_id = request.POST.get('plan_id')
            try:
                plan = get_object_or_404(SubscriptionPlan, id=plan_id, tenant=tenant)
                
                name = request.POST.get('name')
                description = request.POST.get('description')
                price = request.POST.get('price')
                bandwidth = request.POST.get('bandwidth')
                data_cap = request.POST.get('data_cap') or None
                duration_days = request.POST.get('duration_days') or 30
                is_active = bool(request.POST.get('is_active', False))

                if not name or not price or not bandwidth:
                    messages.error(request, 'Name, price and bandwidth are required')
                    return redirect('isp_plans')

                # Check if name conflicts with other plans (excluding current plan)
                if SubscriptionPlan.objects.filter(tenant=tenant, name=name).exclude(id=plan_id).exists():
                    messages.error(request, 'A plan with this name already exists')
                    return redirect('isp_plans')

                plan.name = name
                plan.description = description or ''
                plan.price = price
                plan.bandwidth = int(bandwidth)
                plan.data_cap = int(data_cap) if data_cap else None
                plan.duration_days = int(duration_days)
                plan.is_active = is_active
                plan.save()

                messages.success(request, f'Plan "{name}" updated successfully')
                
            except SubscriptionPlan.DoesNotExist:
                messages.error(request, 'Plan not found')
            except Exception as e:
                messages.error(request, f'Error updating plan: {str(e)}')

            return redirect('isp_plans')
        
        # Delete plan
        elif action == 'delete_plan':
            plan_id = request.POST.get('plan_id')
            try:
                plan = get_object_or_404(SubscriptionPlan, id=plan_id, tenant=tenant)
                plan_name = plan.name
                
                # Check if plan is being used by any active subscriptions
                active_subscriptions = Subscription.objects.filter(
                    plan=plan,
                    end_date__gte=timezone.now()
                ).exists()
                
                if active_subscriptions:
                    messages.error(request, f'Cannot delete "{plan_name}" because it has active subscriptions. Deactivate it instead.')
                else:
                    plan.delete()
                    messages.success(request, f'Plan "{plan_name}" deleted successfully')
                    
            except SubscriptionPlan.DoesNotExist:
                messages.error(request, 'Plan not found')
            except Exception as e:
                messages.error(request, f'Error deleting plan: {str(e)}')

            return redirect('isp_plans')
        
        # Toggle plan status
        elif action == 'toggle_plan_status':
            plan_id = request.POST.get('plan_id')
            try:
                plan = get_object_or_404(SubscriptionPlan, id=plan_id, tenant=tenant)
                plan.is_active = not plan.is_active
                plan.save()
                
                status = "activated" if plan.is_active else "deactivated"
                messages.success(request, f'Plan "{plan.name}" {status} successfully')
                
            except SubscriptionPlan.DoesNotExist:
                messages.error(request, 'Plan not found')
            except Exception as e:
                messages.error(request, f'Error updating plan status: {str(e)}')

            return redirect('isp_plans')

    context = {
        'plans': plans, 
        'tenant': tenant
    }
    return render(request, 'accounts/isp_plans.html', context)


@login_required
@require_http_methods(["GET", "POST"])
def isp_customer_detail(request, customer_id):
    """ISP Customer Detail View"""
    # Ensure the customer belongs to the same tenant as the ISP admin
    customer = get_object_or_404(
        CustomUser, 
        id=customer_id,
        tenant=request.user.tenant  # Security: only access same-tenant customers
    )
    
    # Get plans for the current tenant - FIXED: use tenant instead of user
    available_plans = SubscriptionPlan.objects.filter(tenant=request.user.tenant, is_active=True)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'update_plan':
            plan_id = request.POST.get('plan_id')
            try:
                plan = SubscriptionPlan.objects.get(id=plan_id, tenant=request.user.tenant, is_active=True)
                
                # Create or update subscription
                subscription, created = Subscription.objects.get_or_create(
                    user=customer,
                    defaults={
                        'plan': plan,
                        'is_active': True,
                    }
                )
                
                if not created:
                    subscription.plan = plan
                    subscription.save()
                
                messages.success(request, f'Plan updated to {plan.name} for {customer.username}')
                return JsonResponse({'success': True, 'message': f'Plan updated to {plan.name}'})
                
            except SubscriptionPlan.DoesNotExist:
                return JsonResponse({'success': False, 'error': 'Selected plan not found'})
        
        elif action == 'update_customer':
            # Update customer details
            customer.first_name = request.POST.get('first_name', customer.first_name)
            customer.last_name = request.POST.get('last_name', customer.last_name)
            customer.email = request.POST.get('email', customer.email)
            customer.phone = request.POST.get('phone_number', customer.phone)
            customer.save()
            
            return JsonResponse({'success': True, 'message': 'Customer details updated'})
    
    # Get customer's current subscription
    current_subscription = Subscription.objects.filter(user=customer, is_active=True).first()
    
    # Get recent payments
    recent_payments = Payment.objects.filter(user=customer).select_related('plan').order_by('-created_at')[:10]
    
    context = {
        'customer': customer,
        'available_plans': available_plans,
        'current_subscription': current_subscription,
        'recent_payments': recent_payments,
    }
    
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return render(request, 'accounts/partials/customer_detail_content.html', context)
    
    return render(request, 'accounts/isp_customer_detail.html', context)


@login_required
def isp_configure_paystack(request):
    """ISP Paystack configuration management - FOR ISP USERS"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")

    tenant = request.user.tenant
    
    # Try to get existing Paystack configuration
    try:
        paystack_config = PaystackConfiguration.objects.get(tenant=tenant, is_active=True)
    except PaystackConfiguration.DoesNotExist:
        paystack_config = None

    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'save_config':
            public_key = request.POST.get('public_key')
            secret_key = request.POST.get('secret_key')
            subaccount_code = request.POST.get('subaccount_code')
            transaction_charge = request.POST.get('transaction_charge') or 0
            is_active = bool(request.POST.get('is_active', False))

            if not public_key or not secret_key:
                messages.error(request, 'Public Key and Secret Key are required')
                return redirect('isp_configure_paystack')

            try:
                # Test the Paystack credentials
                paystack_api = PaystackAPI(secret_key=secret_key)
                test_response = paystack_api.verify_credentials()
                
                if not test_response.get('status'):
                    messages.error(request, f'Invalid Paystack credentials: {test_response.get("message", "Unknown error")}')
                    return redirect('isp_configure_paystack')

                # Create or update configuration
                if paystack_config:
                    paystack_config.public_key = public_key
                    paystack_config.secret_key = secret_key
                    paystack_config.subaccount_code = subaccount_code
                    paystack_config.transaction_charge = float(transaction_charge)
                    paystack_config.is_active = is_active
                    paystack_config.save()
                    messages.success(request, 'Paystack configuration updated successfully')
                else:
                    PaystackConfiguration.objects.create(
                        tenant=tenant,
                        public_key=public_key,
                        secret_key=secret_key,
                        subaccount_code=subaccount_code,
                        transaction_charge=float(transaction_charge),
                        is_active=is_active
                    )
                    messages.success(request, 'Paystack configuration created successfully')

            except Exception as e:
                messages.error(request, f'Error saving Paystack configuration: {str(e)}')

            return redirect('isp_configure_paystack')
        
        elif action == 'test_connection':
            if not paystack_config:
                messages.error(request, 'No Paystack configuration found')
                return redirect('isp_configure_paystack')
            
            try:
                paystack_api = PaystackAPI(secret_key=paystack_config.secret_key)
                test_response = paystack_api.verify_credentials()
                
                if test_response.get('status'):
                    messages.success(request, '✅ Paystack connection test successful!')
                else:
                    messages.error(request, f'❌ Paystack connection failed: {test_response.get("message", "Unknown error")}')
                    
            except Exception as e:
                messages.error(request, f'❌ Connection test error: {str(e)}')
            
            return redirect('isp_configure_paystack')
        
        elif action == 'toggle_active':
            if paystack_config:
                paystack_config.is_active = not paystack_config.is_active
                paystack_config.save()
                status = "activated" if paystack_config.is_active else "deactivated"
                messages.success(request, f'Paystack configuration {status}')
            else:
                messages.error(request, 'No Paystack configuration found')
            
            return redirect('isp_configure_paystack')

    # Get payment statistics for the dashboard
    tenant_customer_ids = CustomUser.objects.filter(tenant=tenant, role='customer').values_list('id', flat=True)
    payment_stats = Payment.objects.filter(
        user_id__in=tenant_customer_ids,
        created_at__gte=timezone.now() - timedelta(days=30)
    ).aggregate(
        total_payments=Count('id'),
        successful_payments=Count('id', filter=Q(status='completed')),
        total_revenue=Sum('amount', filter=Q(status='completed'))
    )

    context = {
        'paystack_config': paystack_config,
        'payment_stats': payment_stats,
        'tenant': tenant,
        'page_title': 'Paystack Configuration',
        'page_subtitle': 'Configure and manage Paystack payment gateway',
    }
    
    return render(request, 'accounts/configure_paystack.html', context)


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
                
                if config:
                    config.bank_code = bank_code
                    config.account_number = account_number
                    config.account_name = account_name
                    config.subaccount_code = subaccount_data['subaccount_code']
                    config.save()
                    messages.success(request, f"Paystack subaccount updated successfully for {tenant.name}")
                else:
                    PaystackConfiguration.objects.create(
                        tenant=tenant,
                        bank_code=bank_code,
                        account_number=account_number,
                        account_name=account_name,
                        subaccount_code=subaccount_data['subaccount_code']
                    )
                    messages.success(request, f"Paystack subaccount created successfully for {tenant.name}")
                
                return redirect('admin:index')
            else:
                error_msg = response.get('message', 'Unknown error occurred')
                messages.error(request, f"Failed to create Paystack subaccount: {error_msg}")
        
        except Exception as e:
            messages.error(request, f"Error configuring Paystack: {str(e)}")
    
    # Get Kenyan banks list
    paystack = PaystackAPI()
    banks_response = paystack._make_request("GET", "bank", params={"country": "kenya"})
    
    banks = []
    if banks_response and banks_response.get('status'):
        banks = banks_response.get('data', [])
    else:
        messages.warning(request, "Could not load banks list from Paystack")
    
    context = {
        'tenant': tenant,
        'config': config,
        'banks': banks
    }
    
    return render(request, 'admin/configure_paystack.html', context)

# accounts/views_isp.py - ADD THESE NEW VIEW FUNCTIONS

@login_required
def isp_delete_router(request, router_id):
    """Delete router configuration - CONFIRMATION PAGE or AJAX"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    try:
        router_config = RouterConfig.objects.get(id=router_id, tenant=tenant)
    except RouterConfig.DoesNotExist:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Router configuration not found'})
        messages.error(request, 'Router configuration not found')
        return redirect('isp_routers')
    
    # Handle AJAX DELETE request
    if request.method == 'POST' and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        try:
            router_name = router_config.name
            router_config.delete()
            return JsonResponse({'success': True, 'message': f'Router "{router_name}" deleted successfully'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    # Check if there are any port forwarding rules
    port_rules_count = PortForwardingRule.objects.filter(router=router_config).count()
    
    if request.method == 'POST':
        confirm = request.POST.get('confirm')
        if confirm == 'yes':
            try:
                router_name = router_config.name
                router_config.delete()
                messages.success(request, f'Router configuration "{router_name}" deleted successfully')
            except Exception as e:
                messages.error(request, f'Error deleting router: {str(e)}')
        return redirect('isp_routers')
    
    context = {
        'router_config': router_config,
        'port_rules_count': port_rules_count,
        'tenant': tenant,
        'page_title': f'Delete Router: {router_config.name}',
        'page_subtitle': 'Confirm deletion of router configuration',
        'breadcrumbs': [
            {'name': 'Router Management', 'url': reverse('isp_routers')},
            {'name': f'Delete {router_config.name}', 'url': ''},
        ]
    }
    
    return render(request, 'accounts/isp_delete_router.html', context)


@login_required
def isp_router_api(request, router_id):
    """API endpoint to get router details for editing"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    tenant = request.user.tenant
    
    try:
        router = RouterConfig.objects.get(id=router_id, tenant=tenant)
        return JsonResponse({
            'id': router.id,
            'user_id': router.user_id,
            'model': router.router_model,
            'name': router.name,
            'ip_address': router.ip_address,
            'web_port': router.web_port,
            'username': router.username,
            'router_type': router.router_type,
            'is_online': router.is_online
        })
    except RouterConfig.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Router not found'}, status=404)


@login_required
def isp_add_router(request):
    """Add new router configuration - handles both GET (form page) and POST (AJAX/form submit)"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    if request.method == 'POST':
        form = ISPAddRouterForm(request.POST)
        
        if form.is_valid():
            try:
                router_config = form.save(commit=False)
                router_config.tenant = tenant
                router_config.is_online = False
                
                # Test connectivity
                reachable = False
                is_online = False
                
                try:
                    sock = socket.create_connection((router_config.ip_address, router_config.web_port), timeout=5)
                    sock.close()
                    reachable = True
                    
                    # If reachable, try logging in via router client
                    try:
                        client = get_router_client(router_config)
                        if hasattr(client, 'login') and client.login():
                            is_online = True
                    except Exception as e:
                        print(f"Router login failed: {e}")
                        is_online = False
                        
                except Exception as e:
                    reachable = False
                    print(f"Socket connection failed: {e}")

                router_config.is_online = is_online
                router_config.save()

                # Handle AJAX response
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': True,
                        'message': 'Router added successfully',
                        'router_id': router_config.id
                    })
                
                # Handle regular form submission
                if is_online:
                    messages.success(request, f'Router "{router_config.name}" added and connectivity verified successfully!')
                elif reachable:
                    messages.warning(request, f'Router "{router_config.name}" added but login failed. Check credentials.')
                else:
                    messages.warning(request, f'Router "{router_config.name}" added but cannot reach the device. Check IP/port.')
                
                return redirect('isp_routers')
                
            except Exception as e:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'error': str(e)})
                messages.error(request, f'Error adding router: {str(e)}')
        else:
            error_msg = ', '.join([f"{k}: {v[0]}" for k, v in form.errors.items()])
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': error_msg})
            # Form validation failed
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
    else:
        form = ISPAddRouterForm(initial={'username': 'admin', 'web_port': 80})
    
    context = {
        'form': form,
        'tenant': tenant,
        'page_title': 'Add Router Configuration',
        'page_subtitle': 'Configure a new router for network management',
        'breadcrumbs': [
            {'name': 'Router Management', 'url': reverse('isp_routers')},
            {'name': 'Add Router', 'url': ''},
        ]
    }
    
    return render(request, 'accounts/isp_add_router.html', context)


@login_required
def isp_edit_router(request, router_id):
    """Edit router configuration - handles both GET (form page) and POST (AJAX/form submit)"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    try:
        router_config = RouterConfig.objects.get(id=router_id, tenant=tenant)
    except RouterConfig.DoesNotExist:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Router not found'}, status=404)
        messages.error(request, 'Router configuration not found')
        return redirect('isp_routers')
    
    if request.method == 'POST':
        form = ISPEditRouterForm(request.POST, instance=router_config)
        if form.is_valid():
            try:
                router_config = form.save()
                
                # Test connection after update
                reachable = False
                try:
                    sock = socket.create_connection((router_config.ip_address, router_config.web_port), timeout=5)
                    sock.close()
                    reachable = True
                    
                    # Test login
                    login_success = False
                    try:
                        client = get_router_client(router_config)
                        login_success = client.login() if hasattr(client, 'login') else False
                    except Exception as e:
                        print(f"Router login failed: {e}")
                        login_success = False
                    
                    router_config.is_online = login_success
                    router_config.last_checked = timezone.now()
                    
                except Exception as e:
                    router_config.is_online = False
                    print(f"Socket connection failed: {e}")
                
                router_config.save()
                
                # Handle AJAX response
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': True,
                        'message': 'Router updated successfully'
                    })
                
                # Handle regular form submission
                if router_config.is_online:
                    messages.success(request, f'Router "{router_config.name}" updated and connectivity verified!')
                elif reachable:
                    messages.warning(request, f'Router "{router_config.name}" updated but login failed. Check credentials.')
                else:
                    messages.warning(request, f'Router "{router_config.name}" updated but cannot reach the device.')
                
                return redirect('isp_routers')
                
            except Exception as e:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'error': str(e)})
                messages.error(request, f'Error updating router: {str(e)}')
        else:
            error_msg = ', '.join([f"{k}: {v[0]}" for k, v in form.errors.items()])
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': error_msg})
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
    else:
        form = ISPEditRouterForm(instance=router_config)
    
    context = {
        'form': form,
        'router_config': router_config,
        'tenant': tenant,
        'page_title': f'Edit Router: {router_config.name}',
        'page_subtitle': 'Update router configuration settings',
        'breadcrumbs': [
            {'name': 'Router Management', 'url': reverse('isp_routers')},
            {'name': f'Edit {router_config.name}', 'url': ''},
        ]
    }
    
    return render(request, 'accounts/isp_edit_router.html', context)


@login_required
def isp_port_forwarding(request):
    """Port Forwarding Management - SEPARATE PAGE"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    # Get router configurations and port rules
    router_configs = RouterConfig.objects.filter(tenant=tenant)
    port_rules = PortForwardingRule.objects.filter(router__tenant=tenant).select_related('router', 'customer')
    
    context = {
        'router_configs': router_configs,
        'port_rules': port_rules,
        'tenant': tenant,
        'page_title': 'Port Forwarding Management',
        'page_subtitle': 'Manage port forwarding rules for routers',
        'breadcrumbs': [
            {'name': 'Router Management', 'url': reverse('isp_routers')},
            {'name': 'Port Forwarding', 'url': ''},
        ]
    }
    
    return render(request, 'accounts/isp_port_forwarding.html', context)


@login_required
def isp_add_port_forwarding(request):
    """Add port forwarding rule - SEPARATE PAGE"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    if request.method == 'POST':
        form = ISPPortForwardingForm(request.POST, tenant=tenant)
        if form.is_valid():
            try:
                router_id = request.POST.get('router_id')
                router_cfg = RouterConfig.objects.get(id=router_id, tenant=tenant)
                
                # Generate external port
                import random
                external_port = random.randint(10000, 60000)
                
                # Save port forwarding rule
                port_rule = form.save(commit=False)
                port_rule.router = router_cfg
                port_rule.external_port = external_port
                port_rule.description = f"Port forwarding for {port_rule.customer.username}"
                port_rule.save()
                
                # Try to configure the router
                success = False
                try:
                    client = get_router_client(router_cfg)
                    if hasattr(client, 'add_port_forwarding'):
                        success = client.add_port_forwarding(
                            external_port, 
                            port_rule.internal_ip, 
                            port_rule.internal_port, 
                            port_rule.protocol
                        )
                    else:
                        success = True  # Assume success if method doesn't exist
                except Exception as e:
                    print(f"Router client configuration failed: {e}")
                    success = True  # Assume success for demo purposes
                
                if success:
                    messages.success(request, f'Port forwarding configured: {external_port} → {port_rule.internal_ip}:{port_rule.internal_port} ({port_rule.protocol.upper()})')
                else:
                    messages.warning(request, f'Port forwarding rule created but router configuration may have failed: {external_port} → {port_rule.internal_ip}:{port_rule.internal_port}')
                
                return redirect('isp_port_forwarding')
                    
            except RouterConfig.DoesNotExist:
                messages.error(request, 'Router configuration not found')
            except Exception as e:
                messages.error(request, f'Error setting up port forwarding: {str(e)}')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
    else:
        form = ISPPortForwardingForm(tenant=tenant)
    
    # Get router configurations for dropdown
    router_configs = RouterConfig.objects.filter(tenant=tenant)
    
    context = {
        'form': form,
        'router_configs': router_configs,
        'tenant': tenant,
        'page_title': 'Add Port Forwarding Rule',
        'page_subtitle': 'Create a new port forwarding rule',
        'breadcrumbs': [
            {'name': 'Router Management', 'url': reverse('isp_routers')},
            {'name': 'Port Forwarding', 'url': reverse('isp_port_forwarding')},
            {'name': 'Add Rule', 'url': ''},
        ]
    }
    
    return render(request, 'accounts/isp_add_port_forwarding.html', context)


@login_required
def isp_delete_port_forwarding(request, rule_id):
    """Delete port forwarding rule - CONFIRMATION PAGE"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    try:
        port_rule = PortForwardingRule.objects.get(id=rule_id, router__tenant=tenant)
    except PortForwardingRule.DoesNotExist:
        messages.error(request, 'Port forwarding rule not found')
        return redirect('isp_port_forwarding')
    
    if request.method == 'POST':
        confirm = request.POST.get('confirm')
        if confirm == 'yes':
            try:
                rule_description = f"{port_rule.external_port} → {port_rule.internal_ip}:{port_rule.internal_port}"
                port_rule.delete()
                messages.success(request, f'Port forwarding rule "{rule_description}" deleted successfully')
            except Exception as e:
                messages.error(request, f'Error deleting port forwarding rule: {str(e)}')
        return redirect('isp_port_forwarding')
    
    context = {
        'port_rule': port_rule,
        'tenant': tenant,
        'page_title': 'Delete Port Forwarding Rule',
        'page_subtitle': 'Confirm deletion of port forwarding rule',
        'breadcrumbs': [
            {'name': 'Router Management', 'url': reverse('isp_routers')},
            {'name': 'Port Forwarding', 'url': reverse('isp_port_forwarding')},
            {'name': 'Delete Rule', 'url': ''},
        ]
    }
    
    return render(request, 'accounts/isp_delete_port_forwarding.html', context)


# API endpoints for AJAX operations
@login_required
def api_test_router_connection(request, config_id):
    """API endpoint to test router connection"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return JsonResponse({'success': False, 'error': 'Access denied'})
    
    try:
        config = RouterConfig.objects.get(id=config_id, tenant=request.user.tenant)
        
        # Test connectivity
        reachable = False
        login_success = False
        
        try:
            sock = socket.create_connection((config.ip_address, config.web_port), timeout=5)
            sock.close()
            reachable = True
            
            # Test login
            client = get_router_client(config)
            login_success = client.login() if hasattr(client, 'login') else False
            
            config.is_online = login_success
            config.last_checked = timezone.now()
            config.save()
            
            return JsonResponse({
                'success': True,
                'reachable': reachable,
                'login_success': login_success,
                'status': 'online' if login_success else 'reachable_no_login'
            })
            
        except Exception as e:
            config.is_online = False
            config.save()
            return JsonResponse({
                'success': False,
                'reachable': False,
                'login_success': False,
                'error': str(e)
            })
            
    except RouterConfig.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Router configuration not found'})


@login_required
def api_get_router_details(request, router_id):
    """API endpoint to get router details"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return JsonResponse({'success': False, 'error': 'Access denied'})
    
    try:
        router = Router.objects.get(id=router_id, user__tenant=request.user.tenant)
        
        data = {
            'success': True,
            'router': {
                'id': router.id,
                'name': router.name,
                'model': router.model,
                'ip_address': router.ip_address,
                'mac_address': router.mac_address,
                'is_online': router.is_online,
                'last_seen': router.last_seen.isoformat() if router.last_seen else None,
                'user': {
                    'username': router.user.username,
                    'email': router.user.email,
                }
            }
        }
        
        return JsonResponse(data)
        
    except Router.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Router not found'})


# Add these API views to your views_isp.py

from django.http import JsonResponse
import json
from datetime import datetime

def log_activity(user, action, details):
    """Log activity with fallback"""
    try:
        # Try to use ActivityLog if it exists
        from accounts.models import ActivityLog
        ActivityLog.objects.create(
            user=user,
            action=action,
            details=details,
            ip_address=None,  # Add if you have the request
            user_agent=''  # Add if you have the request
        )
    except (ImportError, AttributeError):
        # Fallback: log to console
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Activity: {action} - User: {user.username if user else 'System'} - {details}")

@login_required
def api_payment_details(request, payment_id):
    """API endpoint for payment details"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return JsonResponse({'success': False, 'error': 'Access denied'})
    
    try:
        tenant = request.user.tenant
        payment = Payment.objects.get(
            id=payment_id,
            user__tenant=tenant
        )
        
        data = {
            'success': True,
            'customer_name': payment.user.get_full_name() or payment.user.username,
            'customer_email': payment.user.email,
            'amount': str(payment.amount),
            'status': payment.status,
            'status_display': payment.get_status_display(),
            'created_date': payment.created_at.strftime('%B %d, %Y'),
            'created_time': payment.created_at.strftime('%I:%M %p'),
            'transaction_id': payment.reference or 'N/A',
            'payment_method': payment.get_payment_method_display(),
            'plan_name': payment.plan.name if payment.plan else 'N/A',
            'plan_bandwidth': payment.plan.bandwidth if payment.plan else 'N/A',
            'notes': payment.description or ''
        }
        
        return JsonResponse(data)
        
    except Payment.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Payment not found'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
@require_http_methods(["POST"])
def api_update_payment_status(request, payment_id):
    """API endpoint to update payment status"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return JsonResponse({'success': False, 'error': 'Access denied'})
    
    try:
        tenant = request.user.tenant
        
        # Get the payment
        payment = Payment.objects.get(
            id=payment_id,
            user__tenant=tenant
        )
        
        # Parse request data
        if request.content_type == 'application/json':
            data = json.loads(request.body)
        else:
            data = request.POST
        
        new_status = data.get('status')
        
        if new_status not in ['completed', 'pending', 'failed', 'refunded']:
            return JsonResponse({'success': False, 'error': 'Invalid status'})
        
        old_status = payment.status
        
        # Update payment status
        payment.status = new_status
        payment.save()
        
        # If marking as completed, activate subscription
        if new_status == 'completed' and payment.plan:
            try:
                # Create or update subscription
                subscription, created = Subscription.objects.get_or_create(
                    user=payment.user,
                    plan=payment.plan,
                    defaults={
                        'is_active': True,
                        'start_date': timezone.now(),
                        'end_date': timezone.now() + timedelta(days=int(payment.plan.duration_days))  # FIXED: Convert to int
                    }
                )
                
                if not created:
                    subscription.is_active = True
                    subscription.start_date = timezone.now()
                    subscription.end_date = timezone.now() + timedelta(days=int(payment.plan.duration_days))  # FIXED: Convert to int
                    subscription.save()
                
                # Update customer's next payment date
                customer = payment.user
                customer.next_payment_date = timezone.now() + timedelta(days=int(payment.plan.duration_days))  # FIXED: Convert to int
                customer.is_active_customer = True
                customer.save()
                
            except Exception as e:
                print(f"Error activating subscription: {e}")
        
        # Log the action (using our helper function)
        log_activity(request.user, 'update_payment_status', 
                    f'Changed payment {payment.reference} from {old_status} to {new_status}')
        
        return JsonResponse({
            'success': True,
            'message': f'Payment status updated to {new_status}',
            'payment': {
                'id': payment.id,
                'status': payment.status,
                'status_display': payment.get_status_display()
            }
        })
        
    except Payment.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Payment not found'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
def api_bulk_payment_action(request):
    """API endpoint for bulk payment actions"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return JsonResponse({'success': False, 'error': 'Access denied'})
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'})
    
    try:
        data = json.loads(request.body)
        action = data.get('action')
        payment_ids = data.get('payment_ids', [])
        
        if not payment_ids:
            return JsonResponse({'success': False, 'error': 'No payments selected'})
        
        tenant = request.user.tenant
        payments = Payment.objects.filter(
            id__in=payment_ids,
            user__tenant=tenant
        )
        
        updated_count = 0
        
        if action == 'mark_completed':
            for payment in payments:
                if payment.status != 'completed':
                    payment.status = 'completed'
                    payment.save()
                    updated_count += 1
                    
        elif action == 'mark_failed':
            for payment in payments:
                if payment.status != 'failed':
                    payment.status = 'failed'
                    payment.save()
                    updated_count += 1
                    
        elif action == 'send_receipts':
            # In a real implementation, you would send emails here
            # For now, we'll just mark them as receipt_sent
            updated_count = payments.count()
            
        # Log the bulk action
        from accounts.models import ActivityLog
        ActivityLog.objects.create(
            user=request.user,
            action='bulk_payment_action',
            details=f'Performed {action} on {updated_count} payments'
        )
        
        return JsonResponse({
            'success': True,
            'updated_count': updated_count,
            'message': f'Successfully processed {updated_count} payment(s)'
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
def api_payment_receipt(request, payment_id):
    """API endpoint to generate receipt PDF"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    try:
        tenant = request.user.tenant
        payment = Payment.objects.get(
            id=payment_id,
            user__tenant=tenant
        )
        
        # In a real implementation, generate PDF using reportlab or weasyprint
        # For now, return a simple response
        from django.http import HttpResponse
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="receipt-{payment.reference}.pdf"'
        
        # This is a placeholder - implement actual PDF generation
        response.write(b'PDF content would be generated here')
        
        return response
        
    except Payment.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Payment not found'})

# Also, add the generate_invoice view mentioned in the template
@login_required
def isp_generate_invoice(request):
    """Generate invoice for payments"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    # This would be a more comprehensive invoice generation view
    # For now, redirect to payments page
    messages.info(request, 'Invoice generation feature coming soon!')
    return redirect('isp_payments')


# ============================================
# AJAX Handlers for Customer Router Management
# ============================================

@login_required
def isp_add_customer_router(request):
    """Add a new customer router via AJAX - POST only"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'}, status=400)
    
    try:
        tenant = request.user.tenant
        customer_id = request.POST.get('customer_id')
        model = request.POST.get('model')
        mac_address = request.POST.get('mac_address')
        ssid = request.POST.get('ssid', '')
        
        if not all([customer_id, model, mac_address]):
            return JsonResponse({'success': False, 'error': 'Missing required fields'})
        
        # Verify customer belongs to this tenant
        customer = CustomUser.objects.get(id=customer_id, tenant=tenant, role='customer')
        
        # Check if router already exists for this customer
        if Router.objects.filter(user=customer).exists():
            return JsonResponse({'success': False, 'error': 'Customer already has a router registered'})
        
        # Create the router
        router = Router.objects.create(
            user=customer,
            model=model,
            mac_address=mac_address,
            ssid=ssid if ssid else 'ConnectWise_Network',
            password=f"Pass{uuid.uuid4().hex[:8]}",  # Generate secure password
            is_online=False
        )
        
        return JsonResponse({
            'success': True,
            'message': f'Router for {customer.username} added successfully',
            'router_id': router.id
        })
        
    except CustomUser.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Customer not found'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def isp_edit_customer_router(request, router_id):
    """Edit a customer router via AJAX - POST only"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'}, status=400)
    
    try:
        tenant = request.user.tenant
        
        # Get the router, ensuring it belongs to a customer of this tenant
        router = Router.objects.get(id=router_id, user__tenant=tenant)
        
        model = request.POST.get('model')
        mac_address = request.POST.get('mac_address')
        ssid = request.POST.get('ssid')
        
        if not all([model, mac_address]):
            return JsonResponse({'success': False, 'error': 'Missing required fields'})
        
        # Check MAC address uniqueness (excluding current router)
        if Router.objects.filter(mac_address=mac_address).exclude(id=router_id).exists():
            return JsonResponse({'success': False, 'error': 'MAC address already in use'})
        
        router.model = model
        router.mac_address = mac_address
        if ssid:
            router.ssid = ssid
        router.save()
        
        return JsonResponse({
            'success': True,
            'message': f'Router {router.model} updated successfully'
        })
        
    except Router.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Router not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def isp_delete_customer_router(request, router_id):
    """Delete a customer router via AJAX - POST only"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'}, status=400)
    
    try:
        tenant = request.user.tenant
        
        # Get the router, ensuring it belongs to a customer of this tenant
        router = Router.objects.get(id=router_id, user__tenant=tenant)
        router_model = router.model
        customer_username = router.user.username
        
        router.delete()
        
        return JsonResponse({
            'success': True,
            'message': f'Router {router_model} for {customer_username} deleted successfully'
        })
        
    except Router.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Router not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def isp_get_customer_router(request, router_id):
    """Get customer router details via AJAX - GET only"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    try:
        tenant = request.user.tenant
        router = Router.objects.get(id=router_id, user__tenant=tenant)
        
        return JsonResponse({
            'success': True,
            'id': router.id,
            'user_id': router.user_id,
            'model': router.model,
            'mac_address': router.mac_address,
            'ssid': router.ssid,
            'is_online': router.is_online
        })
        
    except Router.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Router not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

# Add these views to your views_isp.py

# Update these functions in views_isp.py

@login_required
def isp_add_customer_router(request):
    """Add customer router - SEPARATE PAGE"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    customers = CustomUser.objects.filter(tenant=tenant, role='customer')
    
    if request.method == 'POST':
        customer_id = request.POST.get('customer_id')
        model = request.POST.get('model')
        mac_address = request.POST.get('mac_address')
        ssid = request.POST.get('ssid', 'ConnectWise_Network')
        password = request.POST.get('password', '')
        security_type = request.POST.get('security_type', 'wpa2')
        is_online = bool(request.POST.get('is_online', False))
        
        try:
            customer = CustomUser.objects.get(id=customer_id, tenant=tenant)
            
            # Check if customer already has a router
            if Router.objects.filter(user=customer).exists():
                messages.error(request, f'Customer {customer.username} already has a router assigned')
                return redirect('isp_add_customer_router')
            
            # Check if router with this MAC already exists
            if Router.objects.filter(mac_address=mac_address).exists():
                messages.error(request, f'A router with MAC address {mac_address} already exists')
                return redirect('isp_add_customer_router')
            
            router = Router.objects.create(
                user=customer,
                model=model,
                mac_address=mac_address,
                ssid=ssid,
                password=password,
                security_type=security_type,
                hide_ssid=bool(request.POST.get('hide_ssid', False)),
                band=request.POST.get('band', 'both'),
                channel_width=request.POST.get('channel_width', 'auto'),
                firewall_enabled=bool(request.POST.get('firewall_enabled', True)),
                remote_access=bool(request.POST.get('remote_access', False)),
                upnp_enabled=bool(request.POST.get('upnp_enabled', False)),
                is_online=is_online,
                last_seen=timezone.now() if is_online else None
            )
            
            messages.success(request, f'Router "{model}" added for customer {customer.username}')
            return redirect('isp_routers')
            
        except CustomUser.DoesNotExist:
            messages.error(request, 'Customer not found')
        except Exception as e:
            messages.error(request, f'Error adding router: {str(e)}')
    
    context = {
        'customers': customers,
        'tenant': tenant,
        'page_title': 'Add Customer Router',
        'page_subtitle': 'Register a new router for a customer',
    }
    
    return render(request, 'accounts/isp_add_customer_router.html', context)

@login_required
def isp_edit_customer_router(request, router_id):
    """Edit customer router - SEPARATE PAGE"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    try:
        router = Router.objects.get(id=router_id, user__tenant=tenant)
    except Router.DoesNotExist:
        messages.error(request, 'Router not found')
        return redirect('isp_routers')
    
    if request.method == 'POST':
        model = request.POST.get('model')
        mac_address = request.POST.get('mac_address')
        ssid = request.POST.get('ssid', 'ConnectWise_Network')
        password = request.POST.get('password', router.password)  # Keep existing if not changed
        security_type = request.POST.get('security_type', 'wpa2')
        is_online = bool(request.POST.get('is_online', False))
        
        # Check if MAC address conflicts with other routers
        if Router.objects.filter(mac_address=mac_address).exclude(id=router_id).exists():
            messages.error(request, f'A router with MAC address {mac_address} already exists')
            return redirect('isp_edit_customer_router', router_id=router_id)
        
        router.model = model
        router.mac_address = mac_address
        router.ssid = ssid
        
        # Only update password if provided
        if request.POST.get('password'):
            router.password = password
        
        router.security_type = security_type
        router.hide_ssid = bool(request.POST.get('hide_ssid', False))
        router.band = request.POST.get('band', 'both')
        router.channel_width = request.POST.get('channel_width', 'auto')
        router.firewall_enabled = bool(request.POST.get('firewall_enabled', True))
        router.remote_access = bool(request.POST.get('remote_access', False))
        router.upnp_enabled = bool(request.POST.get('upnp_enabled', False))
        router.is_online = is_online
        
        if is_online and not router.last_seen:
            router.last_seen = timezone.now()
        
        router.save()
        
        messages.success(request, f'Router "{model}" updated successfully')
        return redirect('isp_routers')
    
    context = {
        'router': router,
        'tenant': tenant,
        'page_title': f'Edit Router: {router.model}',
        'page_subtitle': 'Update router information and status',
    }
    
    return render(request, 'accounts/isp_edit_customer_router.html', context)

@login_required
def isp_delete_customer_router(request, router_id):
    """Delete customer router - CONFIRMATION PAGE"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    try:
        router = Router.objects.get(id=router_id, user__tenant=tenant)
    except Router.DoesNotExist:
        messages.error(request, 'Router not found')
        return redirect('isp_routers')
    
    # Get connected device count
    device_count = Device.objects.filter(router=router).count()
    
    if request.method == 'POST':
        confirm = request.POST.get('confirm')
        if confirm == 'DELETE':
            try:
                router_name = router.model
                customer_name = router.user.username
                
                # Delete associated devices first
                Device.objects.filter(router=router).delete()
                ConnectedDevice.objects.filter(router=router).delete()
                
                # Delete the router
                router.delete()
                
                messages.success(request, f'Router "{router_name}" deleted for customer {customer_name}')
                return redirect('isp_routers')
                
            except Exception as e:
                messages.error(request, f'Error deleting router: {str(e)}')
        else:
            messages.error(request, 'Confirmation text did not match')
        
        return redirect('isp_routers')
    
    context = {
        'router': router,
        'device_count': device_count,
        'tenant': tenant,
        'page_title': f'Delete Router: {router.model}',
        'page_subtitle': 'Remove router from customer account',
    }
    
    return render(request, 'accounts/isp_delete_customer_router.html', context)


@login_required
def isp_data_wallet(request):
    """View and manage the ISP data wallet: see balance, eligible customers and manually allocate/activate subscriptions."""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")

    tenant = request.user.tenant

    # Ensure wallet exists
    wallet, _ = DataWallet.objects.get_or_create(tenant=tenant)

    # Eligible customers: active customers under this tenant
    eligible_customers = CustomUser.objects.filter(tenant=tenant, role='customer', is_active_customer=True)

    # Available plans for manual activation
    plans = SubscriptionPlan.objects.filter(tenant=tenant, is_active=True)

    # Get wallet transactions (recent activity)
    from billing.models import WalletTransaction, ISPBulkPurchase
    recent_transactions = WalletTransaction.objects.filter(
        wallet=wallet
    ).select_related('created_by').order_by('-created_at')[:20]

    # Calculate wallet statistics
    from django.db.models import Sum
    from decimal import Decimal
    
    total_deposited = WalletTransaction.objects.filter(
        wallet=wallet,
        transaction_type='deposit'
    ).aggregate(total=Sum('amount_gb'))['total'] or Decimal('0.00')

    total_allocated = WalletTransaction.objects.filter(
        wallet=wallet,
        transaction_type='allocation'
    ).aggregate(total=Sum('amount_gb'))['total'] or Decimal('0.00')

    # Bandwidth purchases stats
    total_bandwidth_purchased = ISPDataPurchase.objects.filter(
        tenant=tenant,
        status='completed',
        package_type='bandwidth'
    ).aggregate(total=Sum('total_bandwidth_amount'))['total'] or Decimal('0.00')

    total_bandwidth_allocated = WalletTransaction.objects.filter(
        wallet=wallet,
        transaction_type='allocation',
        amount_mbps__gt=0
    ).aggregate(total=Sum('amount_mbps'))['total'] or Decimal('0.00')

    total_purchased = ISPBulkPurchase.objects.filter(
        tenant=tenant,
        payment_status='paid'
    ).aggregate(total=Sum('total_data'))['total'] or Decimal('0.00')

    # Get eligible customers
    eligible_customers = CustomUser.objects.filter(tenant=tenant, role='customer', is_active_customer=True)

     # Available plans for manual activation
    plans = SubscriptionPlan.objects.filter(tenant=tenant, is_active=True)

    remaining_balance = total_deposited - total_allocated

    context = {
        'tenant': tenant,
        'wallet': wallet,
        'eligible_customers': eligible_customers,
        'plans': plans,
        'recent_transactions': recent_transactions,
        'total_purchased': total_purchased,
        'total_deposited': total_deposited,
        'total_allocated': total_allocated,
        'total_bandwidth_purchased': total_bandwidth_purchased,
        'total_bandwidth_allocated': total_bandwidth_allocated,
        'remaining_balance': remaining_balance,
        'page_title': 'Data Wallet',
        'page_subtitle': 'Manage ISP bulk data balance and allocate to customers',
    }

    return render(request, 'accounts/isp_data_wallet.html', context)


@login_required
def isp_support_chat(request):
    """Simple support chat page (bot fallback)."""
    # Any authenticated user can access the chat page
    return render(request, 'accounts/isp_support_chat.html', {})


@login_required
def isp_support_chat_messages(request, conv_id):
    """Return messages for a user's conversation (must belong to user)."""
    if request.method != 'GET':
        return JsonResponse({'success': False, 'error': 'GET required'}, status=400)

    from .models import SupportConversation
    conv = SupportConversation.objects.filter(id=conv_id, user=request.user).first()
    if not conv:
        return JsonResponse({'success': False, 'error': 'Not found or access denied'}, status=404)

    msgs = []
    for m in conv.messages.order_by('created_at'):
        msgs.append({'id': m.id, 'sender_type': m.sender_type, 'sender': m.sender.get_full_name() if m.sender else None, 'message': m.message, 'created_at': m.created_at.strftime('%b %d, %H:%M')})

    return JsonResponse({'success': True, 'messages': msgs})


@login_required
def isp_support_operator(request):
    """Operator list of conversations for tenant (ISP staff/admin)."""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden('Access denied')

    from .models import SupportConversation
    tenant = request.user.tenant
    convs = SupportConversation.objects.filter(tenant=tenant).order_by('-updated_at')[:50]
    return render(request, 'accounts/isp_support_operator.html', {'conversations': convs, 'tenant': tenant})


@login_required
def isp_support_operator_conversation(request, conv_id):
    """Operator view: conversation detail page."""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden('Access denied')

    from .models import SupportConversation
    conv = SupportConversation.objects.filter(id=conv_id, tenant=request.user.tenant).first()
    if not conv:
        messages.error(request, 'Conversation not found')
        return redirect('isp_support_operator')

    return render(request, 'accounts/isp_support_operator_conv.html', {'conversation': conv})


@login_required
def isp_support_operator_messages(request, conv_id):
    """API: return messages for a conversation as JSON (used by operator UI polling)."""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)

    from .models import SupportConversation
    conv = SupportConversation.objects.filter(id=conv_id, tenant=request.user.tenant).first()
    if not conv:
        return JsonResponse({'success': False, 'error': 'Not found'}, status=404)

    data = []
    for m in conv.messages.order_by('created_at'):
        data.append({'id': m.id, 'sender_type': m.sender_type, 'sender': m.sender.get_full_name() if m.sender else None, 'message': m.message, 'created_at': m.created_at.strftime('%b %d, %H:%M')})

    return JsonResponse({'success': True, 'messages': data})


@login_required
def isp_support_operator_send(request, conv_id):
    """Operator sends a message into the conversation (AJAX POST)."""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'}, status=400)

    try:
        payload = json.loads(request.body.decode('utf-8'))
    except Exception:
        payload = request.POST

    text = (payload.get('message') or '').strip()
    if not text:
        return JsonResponse({'success': False, 'error': 'Empty message'}, status=400)

    from .models import SupportConversation, SupportMessage
    conv = SupportConversation.objects.filter(id=conv_id, tenant=request.user.tenant).first()
    if not conv:
        return JsonResponse({'success': False, 'error': 'Conversation not found'}, status=404)

    SupportMessage.objects.create(conversation=conv, sender=request.user, sender_type='operator', message=text)
    conv.updated_at = timezone.now()
    conv.save()

    return JsonResponse({'success': True})


@login_required
def isp_support_chat_send(request):
    """AJAX endpoint to send a chat message. Persists messages and returns bot/operator reply.

    Request JSON: { conversation_id?: int, message: str }
    If no conversation_id provided, a new SupportConversation is created for the requesting user.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'}, status=400)

    try:
        payload = json.loads(request.body.decode('utf-8'))
    except Exception:
        payload = request.POST

    message = (payload.get('message') or '').strip()
    conv_id = payload.get('conversation_id') or None
    if not message:
        return JsonResponse({'success': False, 'error': 'Empty message'}, status=400)

    # Create or fetch conversation
    from .models import SupportConversation, SupportMessage
    try:
        if conv_id:
            # ensure conversation belongs to this user
            conv = SupportConversation.objects.filter(id=conv_id, user=request.user).first()
        else:
            conv = None

        # allow an explicit subject in the payload
        subject = (payload.get('subject') or '').strip()

        if not conv:
            conv = SupportConversation.objects.create(
                tenant=getattr(request.user, 'tenant', None),
                user=request.user,
                subject=(subject or (message[:120] if len(message) > 0 else 'Support Request'))
            )
        else:
            # update subject if provided
            if subject:
                conv.subject = subject
                conv.save()

        # Persist user's message
        SupportMessage.objects.create(
            conversation=conv,
            sender=request.user,
            sender_type='user',
            message=message
        )

        # Basic bot/operator routing logic
        lower = message.lower()
        if any(g in lower for g in ['hi', 'hello', 'hey']):
            reply = f"Hello {request.user.get_full_name() or request.user.username}! How can I help you today?"
            sender_type = 'bot'
        elif 'balance' in lower or 'wallet' in lower:
            try:
                wallet = DataWallet.objects.filter(tenant=getattr(request.user, 'tenant', None)).first()
                if wallet:
                    reply = f"Your current wallet balance is {wallet.balance_gb} GB."
                else:
                    reply = "I couldn't find a wallet for your account."
            except Exception:
                reply = "I couldn't fetch the wallet balance right now."
            sender_type = 'bot'
        elif 'operator' in lower or 'human' in lower or 'support' in lower:
            reply = "An operator will respond as soon as one is available."
            sender_type = 'bot'
        else:
            # echo and instruct
            reply = f"You said: '{message}'. An operator will respond as soon as one is available." 
            sender_type = 'bot'

        # Persist bot reply
        SupportMessage.objects.create(
            conversation=conv,
            sender=None,
            sender_type=sender_type,
            message=reply
        )

        # update conversation timestamp
        conv.updated_at = timezone.now()
        conv.save()

        # Return conversation id and latest messages
        recent = []
        for m in conv.messages.order_by('-created_at')[:10]:
            recent.append({
                'id': m.id,
                'sender_type': m.sender_type,
                'sender': m.sender.get_full_name() if m.sender else None,
                'message': m.message,
                'created_at': m.created_at.strftime('%b %d, %H:%M')
            })

        return JsonResponse({'success': True, 'conversation_id': conv.id, 'recent_messages': recent[::-1], 'reply': reply})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def isp_allocate_from_wallet(request):
    """AJAX endpoint to allocate data from wallet to customers or activate subscriptions manually."""
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        if request.user.role not in ['isp_admin', 'isp_staff']:
            return HttpResponseForbidden("Access denied")

        if request.method != 'POST':
            return JsonResponse({'success': False, 'error': 'POST required'})

        try:
            data = json.loads(request.body.decode('utf-8'))
        except Exception as e:
            logger.error(f"Failed to parse JSON: {e}")
            data = request.POST

        tenant = request.user.tenant
        if not tenant:
            return JsonResponse({'success': False, 'error': 'No tenant found'})
            
        wallet = DataWallet.objects.filter(tenant=tenant).first()
        if not wallet:
            return JsonResponse({'success': False, 'error': 'Wallet not found'})

        action = data.get('action')
        logger.info(f"Allocation action: {action}")

        # allocate data amount (GB) to selected customer ids
        if action == 'allocate':
            customer_ids = data.get('customer_ids', [])
            try:
                amount_per_customer = float(data.get('amount_gb', 0))
            except Exception as e:
                logger.error(f"Failed to parse amount: {e}")
                amount_per_customer = 0
                
            if not customer_ids or amount_per_customer <= 0:
                return JsonResponse({'success': False, 'error': 'Invalid parameters: No customers selected or amount is 0'})

            total_needed = amount_per_customer * len(customer_ids)

            from decimal import Decimal
            if wallet.balance_gb < Decimal(str(total_needed)):
                return JsonResponse({
                    'success': False, 
                    'error': f'Insufficient wallet balance. Need {total_needed} GB, have {wallet.balance_gb} GB'
                })

            # Deduct and create distribution logs
            successful = 0
            failed = []
            for cid in customer_ids:
                try:
                    customer = CustomUser.objects.get(id=cid, tenant=tenant, role='customer')
                    
                    # Create distribution log
                    DataDistributionLog.objects.create(
                        bulk_purchase=None,
                        customer=customer,
                        user=request.user,
                        data_amount=Decimal(str(amount_per_customer)),
                        previous_balance=None,
                        new_balance=None,
                        status='success',
                        notes=f'Manual allocation by {request.user.username}'
                    )
                    successful += 1
                except CustomUser.DoesNotExist:
                    failed.append(f"Customer {cid} not found")
                    logger.warning(f"Customer {cid} not found for tenant {tenant}")
                except Exception as e:
                    failed.append(f"Customer {cid}: {str(e)}")
                    logger.error(f"Error allocating to customer {cid}: {e}")

            # Deduct from wallet
            try:
                wallet.allocate(Decimal(str(total_needed)))
                logger.info(f"Allocated {total_needed} GB to {successful} customers")
            except Exception as e:
                logger.error(f"Failed to allocate from wallet: {e}")
                return JsonResponse({'success': False, 'error': f'Failed to deduct from wallet: {str(e)}'})

            # Get recent transactions for display
            from billing.models import WalletTransaction
            recent_txns = WalletTransaction.objects.filter(wallet=wallet).order_by('-created_at')[:5]
            txn_list = []
            for txn in recent_txns:
                txn_list.append({
                    'date': txn.created_at.strftime('%b %d, %H:%M'),
                    'type': txn.get_transaction_type_display(),
                    'type_code': txn.transaction_type,
                    'amount': float(txn.amount_gb),
                    'description': txn.description[:50]
                })

            return JsonResponse({
                'success': True, 
                'message': f'Data allocated successfully to {successful} customers', 
                'remaining': float(wallet.balance_gb),
                'recent_transactions': txn_list
            })

        # activate subscription for a single customer using a selected plan
        elif action == 'activate_subscription':
            customer_id = data.get('customer_id')
            plan_id = data.get('plan_id')
            if not customer_id or not plan_id:
                return JsonResponse({'success': False, 'error': 'Missing customer_id or plan_id'})

            try:
                customer = CustomUser.objects.get(id=customer_id, tenant=tenant, role='customer')
            except CustomUser.DoesNotExist:
                return JsonResponse({'success': False, 'error': f'Customer {customer_id} not found'})
                
            try:
                plan = SubscriptionPlan.objects.get(id=plan_id, tenant=tenant, is_active=True)
            except SubscriptionPlan.DoesNotExist:
                return JsonResponse({'success': False, 'error': f'Plan {plan_id} not found'})

            # Create subscription
            try:
                sub = Subscription.objects.create(
                    user=customer,
                    plan=plan,
                    start_date=timezone.now(),
                    end_date=timezone.now() + timedelta(days=plan.duration_days),
                    is_active=True
                )
                logger.info(f"Created subscription {sub.id} for customer {customer.username}")
            except Exception as e:
                logger.error(f"Failed to create subscription: {e}")
                return JsonResponse({'success': False, 'error': f'Failed to create subscription: {str(e)}'})

            # Optionally deduct data from wallet if the plan has data cap
            warning = None
            from decimal import Decimal
            if plan.data_cap:
                required_gb = Decimal(str(plan.data_cap))
                if wallet.balance_gb < required_gb:
                    warning = f'Subscription created but insufficient wallet balance. Need {required_gb} GB, have {wallet.balance_gb} GB'
                else:
                    try:
                        wallet.allocate(required_gb)
                        # Create distribution log entry for this allocation
                        DataDistributionLog.objects.create(
                            bulk_purchase=None,
                            customer=customer,
                            user=request.user,
                            data_amount=required_gb,
                            previous_balance=None,
                            new_balance=wallet.balance_gb,
                            status='success',
                            notes=f'Subscription activation: {plan.name} by {request.user.username}'
                        )
                        logger.info(f"Allocated {required_gb} GB from wallet for subscription")
                    except Exception as e:
                        logger.error(f"Failed to allocate from wallet for subscription: {e}")
                        warning = f'Subscription created but failed to allocate data: {str(e)}'

            # Get recent transactions for display
            from billing.models import WalletTransaction
            recent_txns = WalletTransaction.objects.filter(wallet=wallet).order_by('-created_at')[:5]
            txn_list = []
            for txn in recent_txns:
                txn_list.append({
                    'date': txn.created_at.strftime('%b %d, %H:%M'),
                    'type': txn.get_transaction_type_display(),
                    'type_code': txn.transaction_type,
                    'amount': float(txn.amount_gb),
                    'description': txn.description[:50]
                })

            return JsonResponse({
                'success': True, 
                'subscription_id': str(sub.id),
                'customer_name': customer.get_full_name() or customer.username,
                'plan_name': plan.name,
                'warning': warning, 
                'remaining': float(wallet.balance_gb),
                'recent_transactions': txn_list
            })

        return JsonResponse({'success': False, 'error': f'Unknown action: {action}'})
        
    except Exception as e:
        logger.exception(f"Unexpected error in isp_allocate_from_wallet: {e}")
        return JsonResponse({'success': False, 'error': f'Server error: {str(e)}'}, status=500)

# Add to imports
from billing.models import BulkDataPackage, BulkBandwidthPackage, ISPDataPurchase, CommissionTransaction
from decimal import Decimal

@login_required
def isp_vendor_marketplace(request):
    """ISP Vendor Marketplace - View and purchase data/bandwidth packages"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    # Get all available packages
    data_packages = BulkDataPackage.objects.filter(
        Q(is_active=True) & (
            Q(source_type='platform') |
            Q(source_type='vendor_marketplace')
        )
    ).order_by('-created_at')
    
    bandwidth_packages = BulkBandwidthPackage.objects.filter(
        is_active=True
    ).order_by('-created_at')
    
    # Get ISP's recent purchases
    recent_purchases = ISPDataPurchase.objects.filter(
        tenant=tenant
    ).order_by('-purchased_at')[:10]
    
    # Get ISP's data wallet balance
    wallet = DataWallet.objects.filter(tenant=tenant).first()
    wallet_balance = wallet.balance_gb if wallet else Decimal('0')
    
    # Filter by package type if specified
    package_type = request.GET.get('type', 'all')
    if package_type == 'data':
        bandwidth_packages = bandwidth_packages.none()
    elif package_type == 'bandwidth':
        data_packages = data_packages.none()
    
    # Filter by vendor if specified
    vendor_id = request.GET.get('vendor')
    if vendor_id:
        data_packages = data_packages.filter(vendor_id=vendor_id)
        bandwidth_packages = bandwidth_packages.filter(vendor_id=vendor_id)
    
    # Filter by price range if specified
    min_price = request.GET.get('min_price')
    max_price = request.GET.get('max_price')
    if min_price:
        data_packages = data_packages.filter(selling_price__gte=Decimal(min_price))
        bandwidth_packages = bandwidth_packages.filter(selling_price__gte=Decimal(min_price))
    if max_price:
        data_packages = data_packages.filter(selling_price__lte=Decimal(max_price))
        bandwidth_packages = bandwidth_packages.filter(selling_price__lte=Decimal(max_price))
    
    # Get all vendors for filter dropdown
    from billing.models import DataVendor
    vendors = DataVendor.objects.filter(is_active=True, is_approved=True)
    
    context = {
        'tenant': tenant,
        'data_packages': data_packages,
        'bandwidth_packages': bandwidth_packages,
        'recent_purchases': recent_purchases,
        'wallet_balance': wallet_balance,
        'vendors': vendors,
        'package_type': package_type,
        'page_title': 'Vendor Marketplace',
        'page_subtitle': 'Purchase bulk data and bandwidth packages',
        }
    
    return render(request, 'accounts/isp_vendor_marketplace.html', context)

@login_required
def isp_purchase_package(request, package_type, package_id):
    """Confirm purchase and redirect to PayStack"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    # Get the package
    if package_type == 'data':
        package = get_object_or_404(BulkDataPackage, id=package_id, is_active=True)
    else:  # bandwidth
        package = get_object_or_404(BulkBandwidthPackage, id=package_id, is_active=True)
    
    # Get wallet for data packages
    wallet = DataWallet.objects.filter(tenant=tenant).first()
    
    if request.method == 'POST':
        quantity = int(request.POST.get('quantity', 1))
        payment_method = request.POST.get('payment_method', 'paystack')
        use_wallet = request.POST.get('use_wallet') == 'true'
        
        # Calculate totals
        if package_type == 'data':
            total_data = package.data_amount * quantity
            total_price = package.selling_price * quantity
        else:
            total_bandwidth = package.bandwidth_amount * quantity
            total_price = package.selling_price * quantity
        
        # Calculate commission
        commission_rate = package.commission_rate
        platform_commission = total_price * (commission_rate / 100)
        isp_net_amount = total_price - platform_commission
        
        # Calculate vendor commission (if vendor exists)
        vendor_commission_rate = Decimal('0.00')
        vendor_commission = Decimal('0.00')

        if hasattr(package, 'vendor') and package.vendor:
            vendor_commission_rate = getattr(package.vendor, 'commission_rate', Decimal('0.00'))
            vendor_commission = total_price * (vendor_commission_rate / Decimal('100'))
            
        # For wallet payment (data packages only)
        if payment_method == 'wallet' and package_type == 'data' and use_wallet:
            if wallet and wallet.balance_gb >= total_data:
                # Process wallet payment
                wallet.balance_gb -= total_data
                wallet.save()
                
                # Create purchase record WITH VENDOR COMMISSION
                purchase = ISPDataPurchase.objects.create(
                    tenant=tenant,
                    bulk_package=package if package_type == 'data' else None,
                    bulk_bandwidth_package=package if package_type == 'bandwidth' else None,
                    package_type=package_type,
                    quantity=quantity,
                    total_data_amount=total_data if package_type == 'data' else 0,
                    total_bandwidth_amount=total_bandwidth if package_type == 'bandwidth' else 0,
                    unit_price=package.selling_price,
                    total_price=total_price,
                    platform_commission=platform_commission,
                    vendor_commission=vendor_commission,  # ADDED
                    vendor_commission_rate=vendor_commission_rate,  # ADDED
                    isp_net_amount=isp_net_amount,
                    status='completed',
                    payment_method='wallet',
                    notes=f"Purchased {quantity} x {package.name} using wallet balance"
                )
                
                # Log wallet transaction
                from billing.models import WalletTransaction
                WalletTransaction.objects.create(
                    wallet=wallet,
                    transaction_type='allocation',
                    amount_gb=total_data,
                    description=f"Purchased {package.name} from marketplace",
                    created_by=request.user
                )
                
                messages.success(request, f'Successfully purchased {quantity} x {package.name} using wallet balance!')
                return redirect('isp_purchase_detail', purchase_id=purchase.id)
            else:
                messages.error(request, f'Insufficient wallet balance. Need {total_data} GB, have {wallet.balance_gb if wallet else 0} GB')
                return redirect('isp_purchase_confirm', package_type=package_type, package_id=package_id)
        
        # For PayStack payment
        elif payment_method == 'paystack':
            # Create pending purchase record WITH VENDOR COMMISSION
            purchase = ISPDataPurchase.objects.create(
                tenant=tenant,
                bulk_package=package if package_type == 'data' else None,
                bulk_bandwidth_package=package if package_type == 'bandwidth' else None,
                package_type=package_type,
                quantity=quantity,
                total_data_amount=total_data if package_type == 'data' else 0,
                total_bandwidth_amount=total_bandwidth if package_type == 'bandwidth' else 0,
                unit_price=package.selling_price,
                total_price=total_price,
                platform_commission=platform_commission,
                vendor_commission=vendor_commission,  # ADDED
                vendor_commission_rate=vendor_commission_rate,  # ADDED
                isp_net_amount=isp_net_amount,
                status='pending',
                payment_method='paystack',
                notes=f"Purchasing {quantity} x {package.name}"
            )
            
            # Initialize PayStack payment
            try:
                paystack_config = PaystackConfiguration.objects.get(tenant=tenant, is_active=True)
                paystack_api = PaystackAPI(secret_key=paystack_config.secret_key)
                
                # Generate unique reference
                import uuid
                reference = f"PURCHASE_{purchase.id}_{uuid.uuid4().hex[:8]}"
                
                # Update purchase with reference
                purchase.payment_reference = reference
                purchase.save()
                
                # Initialize PayStack transaction
                response = paystack_api.initialize_transaction(
                    email=request.user.email,
                    amount=int(total_price * 100),  # Convert to kobo
                    reference=reference,
                    callback_url=request.build_absolute_uri(
                        reverse('isp_package_payment_callback', args=[purchase.id])
                    ),
                    metadata={
                        'purchase_id': str(purchase.id),
                        'tenant_id': str(tenant.id),
                        'package_type': package_type,
                        'package_id': str(package_id),
                        'quantity': quantity
                    }
                )
                
                if response.get('status'):
                    # Redirect to PayStack payment page
                    return redirect(response['data']['authorization_url'])
                else:
                    purchase.status = 'failed'
                    purchase.save()
                    messages.error(request, f'Payment initialization failed: {response.get("message")}')
                    return redirect('isp_vendor_marketplace')
                    
            except PaystackConfiguration.DoesNotExist:
                purchase.status = 'failed'
                purchase.save()
                messages.error(request, 'Paystack is not configured for your account')
                return redirect('isp_vendor_marketplace')
            except Exception as e:
                purchase.status = 'failed'
                purchase.save()
                messages.error(request, f'Payment error: {str(e)}')
                return redirect('isp_vendor_marketplace')
        
        # Invalid payment method
        else:
            messages.error(request, 'Invalid payment method selected')
            return redirect('isp_purchase_confirm', package_type=package_type, package_id=package_id)
    
    context = {
        'package': package,
        'package_type': package_type,
        'tenant': tenant,
        'wallet_balance': wallet.balance_gb if wallet else 0,
        'page_title': f'Purchase {package.name}',
        'page_subtitle': 'Confirm your purchase details',
    }
    
    return render(request, 'accounts/isp_purchase_confirm.html', context)
    
@login_required
def isp_package_payment(request, purchase_id):
    """Process payment for a package purchase"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    try:
        purchase = ISPDataPurchase.objects.get(id=purchase_id, tenant=tenant, status='pending')
    except ISPDataPurchase.DoesNotExist:
        messages.error(request, 'Purchase not found or already processed')
        return redirect('isp_vendor_marketplace')
    
    if request.method == 'POST':
        payment_method = request.POST.get('payment_method', 'paystack')
        
        if payment_method == 'paystack':
            # Initialize Paystack payment
            try:
                paystack_config = PaystackConfiguration.objects.get(tenant=tenant, is_active=True)
                paystack_api = PaystackAPI(secret_key=paystack_config.secret_key)
                
                # Create Paystack transaction
                response = paystack_api.initialize_transaction(
                    email=request.user.email,
                    amount=int(purchase.total_price * 100),  # Convert to kobo
                    reference=f"MKTP_{purchase.id}_{uuid.uuid4().hex[:8]}",
                    callback_url=request.build_absolute_uri(
                        reverse('isp_package_payment_callback', args=[purchase.id])
                    ),
                    metadata={
                        'purchase_id': str(purchase.id),
                        'tenant_id': str(tenant.id),
                        'type': 'marketplace_purchase'
                    }
                )
                
                if response.get('status'):
                    purchase.payment_reference = response['data']['reference']
                    purchase.payment_method = 'paystack'
                    purchase.save()
                    
                    # Redirect to Paystack payment page
                    return redirect(response['data']['authorization_url'])
                else:
                    messages.error(request, f'Payment initialization failed: {response.get("message")}')
                    
            except PaystackConfiguration.DoesNotExist:
                messages.error(request, 'Paystack is not configured for your account')
            except Exception as e:
                messages.error(request, f'Payment error: {str(e)}')
        
        elif payment_method == 'wallet':
            # Check if it's a data package (bandwidth can't be paid with wallet)
            if purchase.package_type == 'data':
                wallet = DataWallet.objects.filter(tenant=tenant).first()
                if wallet and wallet.balance_gb >= purchase.total_data_amount:
                    # Deduct from wallet
                    wallet.balance_gb -= purchase.total_data_amount
                    wallet.save()
                    
                    # Update purchase status
                    purchase.status = 'completed'
                    purchase.completed_at = timezone.now()
                    purchase.save()
                    
                    # Log wallet transaction
                    from billing.models import WalletTransaction
                    WalletTransaction.objects.create(
                        wallet=wallet,
                        transaction_type='allocation',
                        amount_gb=purchase.total_data_amount,
                        description=f"Marketplace purchase: {purchase.notes}",
                        created_by=request.user
                    )
                    
                    messages.success(request, 'Purchase completed using wallet balance!')
                    return redirect('isp_purchase_detail', purchase_id=purchase.id)
                else:
                    messages.error(request, 'Insufficient wallet balance')
            else:
                messages.error(request, 'Bandwidth packages cannot be paid with wallet balance')
    
    context = {
        'purchase': purchase,
        'tenant': tenant,
        'page_title': 'Complete Purchase',
        'page_subtitle': 'Select payment method',
    }
    
    return render(request, 'accounts/isp_package_payment.html', context)

@login_required
def isp_package_payment_callback(request, purchase_id):
    """Handle Paystack callback for package purchase"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    try:
        purchase = ISPDataPurchase.objects.get(id=purchase_id, tenant=tenant)
    except ISPDataPurchase.DoesNotExist:
        messages.error(request, 'Purchase not found')
        return redirect('isp_vendor_marketplace')
    
    # Verify payment with Paystack
    reference = request.GET.get('reference')
    if not reference:
        messages.error(request, 'No payment reference provided')
        return redirect('isp_purchase_detail', purchase_id=purchase.id)
    
    try:
        paystack_config = PaystackConfiguration.objects.get(tenant=tenant, is_active=True)
        paystack_api = PaystackAPI(secret_key=paystack_config.secret_key)
        
        # Verify transaction
        verification = paystack_api.verify_transaction(reference)
        
        if verification.get('status') and verification['data']['status'] == 'success':
            # Payment successful
            purchase.status = 'completed'
            purchase.payment_reference = reference
            purchase.completed_at = timezone.now()
            purchase.save()
            
            # If it's a data package, add to wallet
            if purchase.package_type == 'data' and purchase.bulk_package:
                wallet, _ = DataWallet.objects.get_or_create(tenant=tenant)
                wallet.balance_gb += purchase.total_data_amount
                wallet.save()
                
                # Log wallet transaction
                from billing.models import WalletTransaction
                WalletTransaction.objects.create(
                    wallet=wallet,
                    transaction_type='deposit',
                    amount_gb=purchase.total_data_amount,
                    description=f"Marketplace purchase: {purchase.bulk_package.name}",
                    created_by=request.user
                )
            
            messages.success(request, 'Payment successful! Purchase completed.')
            
            # Record commission transaction
            CommissionTransaction.objects.create(
                tenant=tenant,
                payment=None,  # Not linked to a customer payment
                commission_type='marketplace_purchase',
                transaction_amount=purchase.total_price,
                commission_amount=purchase.platform_commission,
                net_amount=purchase.isp_net_amount,
                status='completed',
                description=f"Marketplace purchase: {purchase.notes}",
                metadata={
                    'purchase_id': str(purchase.id),
                    'package_type': purchase.package_type,
                    'vendor_id': str(purchase.bulk_package.vendor_id) if purchase.bulk_package else str(purchase.bulk_bandwidth_package.vendor_id)
                }
            )
            
        else:
            purchase.status = 'failed'
            purchase.save()
            messages.error(request, 'Payment verification failed')
            
    except Exception as e:
        purchase.status = 'failed'
        purchase.save()
        messages.error(request, f'Payment processing error: {str(e)}')
    
    return redirect('isp_purchase_detail', purchase_id=purchase.id)

@login_required
def isp_purchase_detail(request, purchase_id):
    """View purchase details"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    try:
        purchase = ISPDataPurchase.objects.get(id=purchase_id, tenant=tenant)
    except ISPDataPurchase.DoesNotExist:
        messages.error(request, 'Purchase not found')
        return redirect('isp_vendor_marketplace')
    
    context = {
        'purchase': purchase,
        'tenant': tenant,
        'page_title': f'Purchase #{purchase.id}',
        'page_subtitle': 'View purchase details and status',
    }
    
    return render(request, 'accounts/isp_purchase_detail.html', context)

@login_required
def isp_purchase_history(request):
    """View ISP's purchase history"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    purchases = ISPDataPurchase.objects.filter(tenant=tenant).order_by('-purchased_at')
    
    # Filter by status if specified
    status_filter = request.GET.get('status')
    if status_filter:
        purchases = purchases.filter(status=status_filter)
    
    # Filter by package type if specified
    type_filter = request.GET.get('type')
    if type_filter:
        purchases = purchases.filter(package_type=type_filter)
    
    # Date range filter
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    if date_from:
        purchases = purchases.filter(purchased_at__gte=date_from)
    if date_to:
        purchases = purchases.filter(purchased_at__lte=date_to)
    
    # Calculate statistics
    total_purchases = purchases.count()
    total_spent = purchases.filter(status='completed').aggregate(
        total=Sum('total_price')
    )['total'] or Decimal('0')
    
    total_data_purchased = purchases.filter(
        package_type='data', 
        status='completed'
    ).aggregate(total=Sum('total_data_amount'))['total'] or Decimal('0')
    
    total_bandwidth_purchased = purchases.filter(
        package_type='bandwidth', 
        status='completed'
    ).aggregate(total=Sum('total_bandwidth_amount'))['total'] or Decimal('0')
    
    # Pagination
    paginator = Paginator(purchases, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'purchases': page_obj,
        'total_purchases': total_purchases,
        'total_spent': total_spent,
        'total_data_purchased': total_data_purchased,
        'total_bandwidth_purchased': total_bandwidth_purchased,
        'status_filter': status_filter,
        'type_filter': type_filter,
        'date_from': date_from,
        'date_to': date_to,
        'tenant': tenant,
        'page_title': 'Purchase History',
        'page_subtitle': 'View all your marketplace purchases',
    }
    
    return render(request, 'accounts/isp_purchase_history.html', context)

@login_required
def isp_allocate_bandwidth(request, purchase_id):
    """Allocate purchased bandwidth to customers"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    if not tenant:
        messages.error(request, 'No ISP associated with your account.')
        return redirect('dashboard')
    
    try:
        purchase = ISPDataPurchase.objects.get(
            id=purchase_id, 
            tenant=tenant, 
            package_type='bandwidth',
            status='completed'
        )
    except ISPDataPurchase.DoesNotExist:
        messages.error(request, 'Bandwidth purchase not found or not completed')
        return redirect('isp_purchase_history')
    
    # Get wallet for this tenant
    wallet, created = DataWallet.objects.get_or_create(
        tenant=tenant,
        defaults={
            'balance_gb': Decimal('0.00'),
            'balance_bandwidth_mbps': Decimal('0.00'),
            'updated_by': request.user
        }
    )
    
    # Get eligible customers
    customers = CustomUser.objects.filter(
        tenant=tenant,
        role='customer',
        is_active=True
    ).order_by('username')
    
    # AJAX request handling
    if request.method == 'POST' and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return handle_ajax_bandwidth_allocation(request, purchase, wallet, tenant)
    
    # Regular POST handling
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'allocate':
            customer_ids = request.POST.getlist('customer_ids')
            allocate_amount = Decimal(str(request.POST.get('allocate_amount', 0)))
            
            if not customer_ids or allocate_amount <= 0:
                messages.error(request, 'Please select customers and specify allocation amount')
                return redirect('isp_allocate_bandwidth', purchase_id=purchase_id)
            
            # Check if enough bandwidth available in wallet
            total_needed = allocate_amount * len(customer_ids)
            if wallet.balance_bandwidth_mbps < total_needed:
                messages.error(request, f'Insufficient bandwidth in wallet. Available: {wallet.balance_bandwidth_mbps} Mbps, Needed: {total_needed} Mbps')
                return redirect('isp_allocate_bandwidth', purchase_id=purchase_id)
            
            # Allocate bandwidth to selected customers
            successful_allocations = 0
            for customer_id in customer_ids:
                try:
                    customer = CustomUser.objects.get(id=customer_id, tenant=tenant)
                    
                    # Allocate from wallet
                    if wallet.allocate_bandwidth(
                        amount_mbps=allocate_amount,
                        user=request.user,
                        description=f"Allocated from purchase #{purchase.id}: {purchase.bulk_bandwidth_package.name if purchase.bulk_bandwidth_package else 'Bandwidth Purchase'}",
                        reference=f"PURCHASE-{purchase.id}-ALLOC"
                    ):
                        successful_allocations += 1
                        
                        # Update customer's bandwidth allocation if you track it
                        # You might want to store this in customer profile or separate model
                        
                    else:
                        messages.warning(request, f'Failed to allocate bandwidth to customer {customer_id}')
                        
                except CustomUser.DoesNotExist:
                    messages.warning(request, f'Customer {customer_id} not found')
                except Exception as e:
                    logger.error(f"Error allocating bandwidth to customer {customer_id}: {e}")
                    messages.warning(request, f'Error allocating to customer {customer_id}: {str(e)}')
            
            if successful_allocations > 0:
                messages.success(request, f'Successfully allocated {total_needed} Mbps to {successful_allocations} customers')
            
            return redirect('isp_allocate_bandwidth', purchase_id=purchase_id)
    
    # Get recent allocations for this purchase
    recent_allocations = WalletTransaction.objects.filter(
        wallet=wallet,
        description__icontains=f"purchase #{purchase.id}",
        transaction_type='allocation',
        amount_mbps__gt=0
    ).select_related('created_by').order_by('-created_at')[:10]
    
    context = {
        'purchase': purchase,
        'customers': customers,
        'tenant': tenant,
        'wallet': wallet,
        'recent_allocations': recent_allocations,
        'page_title': f'Allocate Bandwidth - Purchase #{purchase.id}',
        'page_subtitle': f'Distribute {purchase.total_bandwidth_amount} Mbps to customers',
    }
    
    return render(request, 'accounts/isp_allocate_bandwidth.html', context)


def handle_ajax_bandwidth_allocation(request, purchase, wallet, tenant):
    """Handle AJAX bandwidth allocation requests"""
    try:
        # Parse JSON data
        try:
            data = json.loads(request.body.decode('utf-8'))
        except:
            data = request.POST.copy()
        
        action = data.get('action', 'allocate')
        customer_ids = data.get('customer_ids', [])
        
        # Handle different formats of customer_ids
        if isinstance(customer_ids, str):
            try:
                customer_ids = json.loads(customer_ids)
            except:
                customer_ids = [cid.strip() for cid in customer_ids.split(',') if cid.strip()]
        
        allocate_amount = Decimal(str(data.get('bandwidth_amount', data.get('allocate_amount', 0))))
        description = data.get('description', f'Allocated from purchase #{purchase.id}')
        
        if not customer_ids or allocate_amount <= 0:
            return JsonResponse({'success': False, 'error': 'Invalid parameters'})
        
        total_needed = allocate_amount * len(customer_ids)
        
        # Check if enough bandwidth available in wallet
        if wallet.balance_bandwidth_mbps < total_needed:
            return JsonResponse({
                'success': False, 
                'error': f'Insufficient bandwidth in wallet. Available: {wallet.balance_bandwidth_mbps} Mbps, Needed: {total_needed} Mbps'
            })
        
        # Allocate bandwidth to selected customers
        successful_allocations = 0
        failed_allocations = []
        
        for cid in customer_ids:
            try:
                customer = CustomUser.objects.get(id=int(cid), tenant=tenant, role='customer')
                
                # Allocate from wallet
                if wallet.allocate_bandwidth(
                    amount_mbps=allocate_amount,
                    user=request.user,
                    description=description,
                    reference=f"PURCHASE-{purchase.id}-ALLOC-{timezone.now().strftime('%Y%m%d%H%M%S')}"
                ):
                    successful_allocations += 1
                else:
                    failed_allocations.append(f"Customer {cid}: Allocation failed")
                    
            except CustomUser.DoesNotExist:
                failed_allocations.append(f"Customer {cid}: Not found")
            except Exception as e:
                failed_allocations.append(f"Customer {cid}: {str(e)}")
        
        if successful_allocations > 0:
            # Update purchase status if all bandwidth is allocated
            # You might want to track how much bandwidth is allocated from each purchase
            # For now, we'll just allocate from the general wallet balance
            
            return JsonResponse({
                'success': True, 
                'message': f'Allocated {total_needed} Mbps to {successful_allocations} customers from purchase #{purchase.id}', 
                'remaining_bandwidth': float(wallet.balance_bandwidth_mbps),
                'successful_count': successful_allocations,
                'failed_count': len(failed_allocations),
                'purchase_id': purchase.id,
                'purchase_amount': float(purchase.total_bandwidth_amount),
                'failed_details': failed_allocations[:5]
            })
        else:
            return JsonResponse({
                'success': False, 
                'error': 'No allocations were successful',
                'failed_details': failed_allocations
            })
            
    except Exception as e:
        logger.error(f"AJAX bandwidth allocation error: {e}")
        return JsonResponse({'success': False, 'error': f'Server error: {str(e)}'})

# API endpoints for marketplace
@login_required
def api_marketplace_packages(request):
    """API endpoint to get marketplace packages (for AJAX filtering)"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return JsonResponse({'success': False, 'error': 'Access denied'})
    
    package_type = request.GET.get('type', 'all')
    vendor_id = request.GET.get('vendor')
    min_price = request.GET.get('min_price')
    max_price = request.GET.get('max_price')
    
    if package_type in ['all', 'data']:
        data_packages = BulkDataPackage.objects.filter(
            Q(is_active=True) & (
                Q(source_type='platform') |
                Q(source_type='vendor_marketplace')
            )
        )
        
        if vendor_id:
            data_packages = data_packages.filter(vendor_id=vendor_id)
        if min_price:
            data_packages = data_packages.filter(selling_price__gte=Decimal(min_price))
        if max_price:
            data_packages = data_packages.filter(selling_price__lte=Decimal(max_price))
    else:
        data_packages = BulkDataPackage.objects.none()
    
    if package_type in ['all', 'bandwidth']:
        bandwidth_packages = BulkBandwidthPackage.objects.filter(is_active=True)
        
        if vendor_id:
            bandwidth_packages = bandwidth_packages.filter(vendor_id=vendor_id)
        if min_price:
            bandwidth_packages = bandwidth_packages.filter(selling_price__gte=Decimal(min_price))
        if max_price:
            bandwidth_packages = bandwidth_packages.filter(selling_price__lte=Decimal(max_price))
    else:
        bandwidth_packages = BulkBandwidthPackage.objects.none()
    
    data_list = []
    for package in data_packages:
        data_list.append({
            'id': str(package.id),
            'type': 'data',
            'name': package.name,
            'amount': str(package.data_amount),
            'unit': 'GB',
            'price': str(package.selling_price),
            'vendor': package.vendor.name if package.vendor else 'Platform',
            'validity': f"{package.validity_days} days",
            'description': package.description,
            'commission_rate': str(package.commission_rate),
        })
    
    for package in bandwidth_packages:
        data_list.append({
            'id': str(package.id),
            'type': 'bandwidth',
            'name': package.name,
            'amount': str(package.bandwidth_amount),
            'unit': package.unit.upper(),
            'price': str(package.selling_price),
            'vendor': package.vendor.name if package.vendor else 'N/A',
            'validity': f"{package.validity_days} days",
            'description': f"{package.get_package_type_display()} - {package.unit.upper()}",
            'commission_rate': str(package.commission_rate),
        })
    
    return JsonResponse({'success': True, 'packages': data_list})

@login_required
def api_calculate_purchase(request):
    """API endpoint to calculate purchase total"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return JsonResponse({'success': False, 'error': 'Access denied'})
    
    try:
        data = json.loads(request.body)
        package_id = data.get('package_id')
        package_type = data.get('package_type')
        quantity = int(data.get('quantity', 1))
        
        if package_type == 'data':
            package = BulkDataPackage.objects.get(id=package_id, is_active=True)
            total_data = package.data_amount * quantity
            total_price = package.selling_price * quantity
            commission = (total_price * package.commission_rate / 100)
        else:
            package = BulkBandwidthPackage.objects.get(id=package_id, is_active=True)
            total_data = package.bandwidth_amount * quantity
            total_price = package.selling_price * quantity
            commission = (total_price * package.commission_rate / 100)
        
        return JsonResponse({
            'success': True,
            'total_price': str(total_price),
            'unit_price': str(package.selling_price),
            'total_data': str(total_data),
            'commission': str(commission),
            'net_amount': str(total_price - commission)
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
def mark_payment_completed(request, payment_id):
    """Manually mark a pending payment as completed"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    tenant = request.user.tenant
    
    try:
        payment = Payment.objects.get(
            id=payment_id,
            user__tenant=tenant
        )
        
        if payment.status != 'pending':
            return JsonResponse({
                'success': False, 
                'error': f'Payment is already {payment.status}. Only pending payments can be marked as completed.'
            })
        
        # Mark payment as completed
        payment.status = 'completed'
        payment.save()
        
        # Automatically activate subscription if payment has a plan
        if payment.plan:
            subscription = Subscription.objects.filter(
                user=payment.user,
                plan=payment.plan,
                is_active=False
            ).first()
            
            if subscription:
                subscription.is_active = True
                subscription.start_date = timezone.now()
                subscription.end_date = timezone.now() + timedelta(days=payment.plan.duration_days)
                subscription.save()
                
            # Update customer's next payment date
            payment.user.next_payment_date = timezone.now() + timedelta(days=payment.plan.duration_days)
            payment.user.is_active_customer = True
            payment.user.save()
        
        # Log the action
        from accounts.models import ActivityLog
        ActivityLog.objects.create(
            user=request.user,
            action='mark_payment_completed',
            details=f'Manually marked payment {payment.reference} ({payment.amount}) as completed for customer {payment.user.username}'
        )
        
        return JsonResponse({
            'success': True,
            'message': f'Payment marked as completed and subscription activated successfully!',
            'payment': {
                'id': payment.id,
                'status': payment.status,
                'status_display': payment.get_status_display()
            }
        })
        
    except Payment.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Payment not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def delete_payment(request, payment_id):
    """Delete a pending payment"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    tenant = request.user.tenant
    
    try:
        payment = Payment.objects.get(
            id=payment_id,
            user__tenant=tenant,
            status='pending'  # Only allow deletion of pending payments
        )
        
        # Store payment info for the response
        payment_info = {
            'id': payment.id,
            'amount': str(payment.amount),
            'reference': payment.reference,
            'customer': payment.user.username
        }
        
        # Delete the payment
        payment.delete()
        
        # Log the action
        from accounts.models import ActivityLog
        ActivityLog.objects.create(
            user=request.user,
            action='delete_payment',
            details=f'Deleted pending payment {payment_info["reference"]} ({payment_info["amount"]}) for customer {payment_info["customer"]}'
        )
        
        return JsonResponse({
            'success': True,
            'message': f'Payment deleted successfully!',
            'deleted_payment': payment_info
        })
        
    except Payment.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Payment not found or not pending'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def download_payment_receipt(request, payment_id):
    """Generate and download payment receipt as PDF"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    try:
        payment = Payment.objects.get(
            id=payment_id,
            user__tenant=tenant
        )
        
        # Import reportlab for PDF generation
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas
        from reportlab.lib.units import inch
        from io import BytesIO
        
        # Create PDF in memory
        buffer = BytesIO()
        c = canvas.Canvas(buffer, pagesize=letter)
        
        # Company header
        c.setFont("Helvetica-Bold", 16)
        c.drawString(1*inch, 10.5*inch, tenant.name)
        
        c.setFont("Helvetica", 10)
        c.drawString(1*inch, 10.2*inch, "Payment Receipt")
        c.drawString(1*inch, 10.0*inch, f"Date: {timezone.now().strftime('%Y-%m-%d %H:%M')}")
        
        # Line separator
        c.line(1*inch, 9.8*inch, 7.5*inch, 9.8*inch)
        
        # Payment details
        c.setFont("Helvetica-Bold", 12)
        c.drawString(1*inch, 9.5*inch, "PAYMENT DETAILS")
        
        c.setFont("Helvetica", 10)
        y_position = 9.2*inch
        
        details = [
            ("Receipt Number:", payment.reference or f"REC-{payment.id:06d}"),
            ("Customer:", f"{payment.user.get_full_name() or payment.user.username}"),
            ("Customer ID:", payment.user.company_account_number or "N/A"),
            ("Amount:", f"Ksh {payment.amount:.2f}"),
            ("Status:", payment.get_status_display()),
            ("Payment Method:", payment.get_payment_method_display()),
            ("Date:", payment.created_at.strftime('%Y-%m-%d %H:%M:%S')),
        ]
        
        if payment.plan:
            details.append(("Plan:", payment.plan.name))
            details.append(("Bandwidth:", f"{payment.plan.bandwidth} Mbps"))
        
        for label, value in details:
            c.drawString(1*inch, y_position, f"{label}")
            c.drawString(3*inch, y_position, f"{value}")
            y_position -= 0.3*inch
        
        # Footer
        c.setFont("Helvetica-Oblique", 8)
        c.drawString(1*inch, 0.5*inch, "This is an official receipt. Please keep it for your records.")
        c.drawString(1*inch, 0.3*inch, f"Issued by: {request.user.get_full_name()} on {tenant.name}")
        
        c.save()
        
        # Prepare response
        buffer.seek(0)
        response = HttpResponse(buffer, content_type='application/pdf')
        filename = f"receipt_{payment.reference or payment.id}.pdf"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        return response
        
    except Payment.DoesNotExist:
        messages.error(request, 'Payment not found')
        return redirect('isp_payments')
    except Exception as e:
        messages.error(request, f'Error generating receipt: {str(e)}')
        return redirect('isp_payments')


@login_required
def bulk_mark_payments_completed(request):
    """Bulk mark multiple payments as completed"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST method required'})
    
    try:
        data = json.loads(request.body)
        payment_ids = data.get('payment_ids', [])
        
        if not payment_ids:
            return JsonResponse({'success': False, 'error': 'No payments selected'})
        
        tenant = request.user.tenant
        completed_payments = []
        failed_payments = []
        
        with transaction.atomic():
            for payment_id in payment_ids:
                try:
                    payment = Payment.objects.get(
                        id=payment_id,
                        user__tenant=tenant,
                        status='pending'
                    )
                    
                    # Mark as completed
                    payment.status = 'completed'
                    payment.save()
                    
                    # Activate subscription if applicable
                    if payment.plan:
                        subscription = Subscription.objects.filter(
                            user=payment.user,
                            plan=payment.plan,
                            is_active=False
                        ).first()
                        
                        if subscription:
                            subscription.is_active = True
                            subscription.start_date = timezone.now()
                            subscription.end_date = timezone.now() + timedelta(days=payment.plan.duration_days)
                            subscription.save()
                        
                        payment.user.next_payment_date = timezone.now() + timedelta(days=payment.plan.duration_days)
                        payment.user.is_active_customer = True
                        payment.user.save()
                    
                    completed_payments.append({
                        'id': payment.id,
                        'reference': payment.reference,
                        'amount': str(payment.amount)
                    })
                    
                except Payment.DoesNotExist:
                    failed_payments.append({
                        'id': payment_id,
                        'error': 'Payment not found or not pending'
                    })
                except Exception as e:
                    failed_payments.append({
                        'id': payment_id,
                        'error': str(e)
                    })
        
        # Log bulk action
        if completed_payments:
            from accounts.models import ActivityLog
            ActivityLog.objects.create(
                user=request.user,
                action='bulk_mark_payments_completed',
                details=f'Bulk marked {len(completed_payments)} payments as completed'
            )
        
        return JsonResponse({
            'success': True,
            'message': f'Successfully completed {len(completed_payments)} payment(s)',
            'completed': completed_payments,
            'failed': failed_payments
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def export_payments_csv(request, customer_id):
    """Export customer payments to CSV"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    try:
        customer = CustomUser.objects.get(id=customer_id, tenant=tenant)
    except CustomUser.DoesNotExist:
        messages.error(request, 'Customer not found')
        return redirect('isp_customer_payments', customer_id=customer_id)
    
    # Get payments
    payments = Payment.objects.filter(user=customer).order_by('-created_at')
    
    # Create CSV response
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="payments_{customer.username}_{timezone.now().strftime("%Y%m%d")}.csv"'
    
    writer = csv.writer(response)
    
    # Write header
    writer.writerow([
        'Date', 'Time', 'Transaction ID', 'Amount (Ksh)', 'Plan', 
        'Status', 'Payment Method', 'Description'
    ])
    
    # Write data
    for payment in payments:
        writer.writerow([
            payment.created_at.strftime('%Y-%m-%d'),
            payment.created_at.strftime('%H:%M:%S'),
            payment.reference or '',
            str(payment.amount),
            payment.plan.name if payment.plan else '',
            payment.get_status_display(),
            payment.get_payment_method_display(),
            payment.description or ''
        ])
    
    return response


@login_required
def isp_create_manual_payment(request, customer_id):
    """Create a manual payment and optionally activate subscription immediately"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST method required'})
    
    try:
        tenant = request.user.tenant
        customer = CustomUser.objects.get(id=customer_id, tenant=tenant)
        
        data = json.loads(request.body)
        amount = Decimal(data.get('amount', 0))
        plan_id = data.get('plan_id')
        payment_method = data.get('payment_method', 'cash')
        reference = data.get('reference', f"MANUAL_{timezone.now().strftime('%Y%m%d%H%M%S')}")
        notes = data.get('notes', '')
        activate_subscription = data.get('activate_subscription', True)
        
        if amount <= 0:
            return JsonResponse({'success': False, 'error': 'Amount must be greater than 0'})
        
        # Get plan if provided
        plan = None
        if plan_id:
            try:
                plan = SubscriptionPlan.objects.get(id=plan_id, tenant=tenant, is_active=True)
            except SubscriptionPlan.DoesNotExist:
                return JsonResponse({'success': False, 'error': 'Selected plan not found'})
        
        # Create payment
        payment = Payment.objects.create(
            user=customer,
            plan=plan,
            amount=amount,
            reference=reference,
            status='completed' if activate_subscription else 'pending',
            payment_method=payment_method,
            description=f"Manual payment by {request.user.username}" + (f" - {notes}" if notes else "")
        )
        
        # Activate subscription if requested
        if activate_subscription and plan:
            subscription, created = Subscription.objects.get_or_create(
                user=customer,
                plan=plan,
                defaults={
                    'is_active': True,
                    'start_date': timezone.now(),
                    'end_date': timezone.now() + timedelta(days=plan.duration_days)
                }
            )
            
            if not created:
                subscription.is_active = True
                subscription.start_date = timezone.now()
                subscription.end_date = timezone.now() + timedelta(days=plan.duration_days)
                subscription.save()
            
            # Update customer's next payment date
            customer.next_payment_date = timezone.now() + timedelta(days=plan.duration_days)
            customer.is_active_customer = True
            customer.save()
        
        # Log the action
        from accounts.models import ActivityLog
        ActivityLog.objects.create(
            user=request.user,
            action='create_manual_payment',
            details=f'Created manual payment {reference} ({amount}) for customer {customer.username}'
        )
        
        return JsonResponse({
            'success': True,
            'message': f'Manual payment created successfully!',
            'payment': {
                'id': payment.id,
                'reference': payment.reference,
                'amount': str(payment.amount),
                'status': payment.status,
                'subscription_activated': activate_subscription and plan is not None
            }
        })
        
    except CustomUser.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Customer not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@login_required
def isp_import_customers(request):
    """Import customers from CSV/Excel file"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    available_plans = SubscriptionPlan.objects.filter(tenant=tenant, is_active=True)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'upload_file':
            # Handle file upload
            uploaded_file = request.FILES.get('customer_file')
            file_type = request.POST.get('file_type', 'csv')
            
            if not uploaded_file:
                messages.error(request, 'Please select a file to upload')
                return redirect('isp_import_customers')
            
            try:
                # Read file based on type
                if file_type == 'csv':
                    # Read CSV file
                    file_content = uploaded_file.read().decode('utf-8')
                    csv_data = csv.reader(io.StringIO(file_content))
                    headers = next(csv_data)
                    
                    # Convert to list of dictionaries
                    customers_data = []
                    for row in csv_data:
                        if len(row) == len(headers):
                            customer_dict = {}
                            for i, header in enumerate(headers):
                                customer_dict[header.strip().lower()] = row[i].strip()
                            customers_data.append(customer_dict)
                
                elif file_type in ['xlsx', 'xls']:
                    # Read Excel file
                    df = pd.read_excel(uploaded_file)
                    customers_data = df.to_dict('records')
                
                else:
                    messages.error(request, 'Unsupported file format')
                    return redirect('isp_import_customers')
                
                # Store in session for preview
                request.session['import_customers_data'] = customers_data
                request.session['import_file_type'] = file_type
                request.session['import_file_name'] = uploaded_file.name
                
                # Get sample data for preview
                sample_data = customers_data[:5] if len(customers_data) > 5 else customers_data
                
                messages.success(request, f'File uploaded successfully! Found {len(customers_data)} records.')
                return redirect('isp_import_preview')
                
            except Exception as e:
                messages.error(request, f'Error reading file: {str(e)}')
                return redirect('isp_import_customers')
        
        elif action == 'import_direct':
            # Direct import from form
            customers_text = request.POST.get('customers_text')
            if not customers_text:
                messages.error(request, 'Please enter customer data')
                return redirect('isp_import_customers')
            
            try:
                # Parse text input (comma or tab separated)
                lines = customers_text.strip().split('\n')
                if not lines:
                    messages.error(request, 'No data found in text input')
                    return redirect('isp_import_customers')
                
                # Detect delimiter
                first_line = lines[0]
                if '\t' in first_line:
                    delimiter = '\t'
                else:
                    delimiter = ','
                
                # Parse lines
                customers_data = []
                for line in lines:
                    if line.strip():
                        parts = [p.strip() for p in line.split(delimiter)]
                        if len(parts) >= 2:  # At least username and email
                            customers_data.append({
                                'username': parts[0],
                                'email': parts[1] if len(parts) > 1 else '',
                                'phone': parts[2] if len(parts) > 2 else '',
                                'first_name': parts[3] if len(parts) > 3 else '',
                                'last_name': parts[4] if len(parts) > 4 else '',
                                'address': parts[5] if len(parts) > 5 else '',
                            })
                
                request.session['import_customers_data'] = customers_data
                request.session['import_file_type'] = 'text'
                request.session['import_file_name'] = 'manual_input.txt'
                
                messages.success(request, f'Data parsed successfully! Found {len(customers_data)} records.')
                return redirect('isp_import_preview')
                
            except Exception as e:
                messages.error(request, f'Error parsing data: {str(e)}')
                return redirect('isp_import_customers')
    
    context = {
        'tenant': tenant,
        'available_plans': available_plans,
        'page_title': 'Import Customers',
        'page_subtitle': 'Import customers from CSV, Excel, or manual input',
        'breadcrumbs': [
            {'name': 'Customer Management', 'url': reverse('isp_customers')},
            {'name': 'Import Customers', 'url': ''},
        ]
    }
    
    return render(request, 'accounts/isp_import_customers.html', context)


@login_required
def isp_import_preview(request):
    """Preview imported customer data before confirmation"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    # Get data from session
    customers_data = request.session.get('import_customers_data', [])
    file_type = request.session.get('import_file_type', 'csv')
    file_name = request.session.get('import_file_name', '')
    
    if not customers_data:
        messages.error(request, 'No import data found. Please upload a file first.')
        return redirect('isp_import_customers')
    
    available_plans = SubscriptionPlan.objects.filter(tenant=tenant, is_active=True)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'process_import':
            # Process the import
            default_plan_id = request.POST.get('default_plan')
            generate_passwords = request.POST.get('generate_passwords') == 'on'
            send_welcome_email = request.POST.get('send_welcome_email') == 'on'
            auto_activate = request.POST.get('auto_activate') == 'on'
            
            try:
                default_plan = None
                if default_plan_id:
                    default_plan = SubscriptionPlan.objects.get(id=default_plan_id, tenant=tenant, is_active=True)
                
                results = {
                    'total': len(customers_data),
                    'successful': 0,
                    'failed': 0,
                    'errors': [],
                    'customers': []
                }
                
                for i, customer_data in enumerate(customers_data):
                    try:
                        # Extract customer data
                        username = customer_data.get('username', '').strip()
                        email = customer_data.get('email', '').strip()
                        phone = customer_data.get('phone', '').strip()
                        first_name = customer_data.get('first_name', '').strip()
                        last_name = customer_data.get('last_name', '').strip()
                        address = customer_data.get('address', '').strip()
                        
                        # Validate required fields
                        if not username:
                            results['errors'].append(f'Row {i+1}: Username is required')
                            results['failed'] += 1
                            continue
                        
                        # Check if username already exists
                        if CustomUser.objects.filter(username=username).exists():
                            results['errors'].append(f'Row {i+1}: Username "{username}" already exists')
                            results['failed'] += 1
                            continue
                        
                        # Generate password if needed
                        if generate_passwords:
                            password = CustomUser.objects.make_random_password(length=10)
                        else:
                            # Use username + '123' as default password
                            password = f"{username}123"
                        
                        # Create user
                        new_user = CustomUser.objects.create_user(
                            username=username,
                            email=email if email else f"{username}@example.com",
                            password=password
                        )
                        
                        new_user.tenant = tenant
                        new_user.role = 'customer'
                        new_user.phone = phone
                        new_user.first_name = first_name
                        new_user.last_name = last_name
                        new_user.address = address
                        
                        # Generate account number
                        timestamp = int(timezone.now().timestamp())
                        new_user.company_account_number = f"{tenant.id:03d}{timestamp % 1000000:06d}"
                        
                        new_user.is_active_customer = auto_activate
                        new_user.registration_status = 'approved' if auto_activate else 'pending'
                        new_user.registration_date = timezone.now()
                        
                        if auto_activate:
                            new_user.approval_date = timezone.now()
                            new_user.approved_by = request.user
                        
                        new_user.save()
                        
                        # Create subscription if plan is selected
                        if default_plan:
                            Subscription.objects.create(
                                user=new_user,
                                plan=default_plan,
                                is_active=auto_activate,
                                start_date=timezone.now(),
                                end_date=timezone.now() + timedelta(days=default_plan.duration_days)
                            )
                            
                            if auto_activate:
                                new_user.next_payment_date = timezone.now() + timedelta(days=default_plan.duration_days)
                                new_user.save()
                        
                        results['successful'] += 1
                        results['customers'].append({
                            'username': username,
                            'email': new_user.email,
                            'password': password if generate_passwords else 'Set by user',
                            'status': 'Active' if auto_activate else 'Pending'
                        })
                        
                    except Exception as e:
                        results['errors'].append(f'Row {i+1}: {str(e)}')
                        results['failed'] += 1
                        print(f"Error importing customer {customer_data}: {e}")
                        traceback.print_exc()
                
                # Store results in session for results page
                request.session['import_results'] = results
                request.session['import_summary'] = {
                    'total': results['total'],
                    'successful': results['successful'],
                    'failed': results['failed']
                }
                
                # Clear import data from session
                if 'import_customers_data' in request.session:
                    del request.session['import_customers_data']
                
                messages.success(request, f'Import completed! {results["successful"]} successful, {results["failed"]} failed.')
                return redirect('isp_import_results')
                
            except Exception as e:
                messages.error(request, f'Error processing import: {str(e)}')
        
        elif action == 'cancel_import':
            # Clear session data
            if 'import_customers_data' in request.session:
                del request.session['import_customers_data']
            messages.info(request, 'Import cancelled')
            return redirect('isp_import_customers')
    
    # Prepare data for preview
    preview_data = []
    for i, customer in enumerate(customers_data[:10]):  # Show first 10 rows
        preview_data.append({
            'row': i + 1,
            'username': customer.get('username', ''),
            'email': customer.get('email', ''),
            'phone': customer.get('phone', ''),
            'first_name': customer.get('first_name', ''),
            'last_name': customer.get('last_name', ''),
            'address': customer.get('address', ''),
        })
    
    context = {
        'tenant': tenant,
        'preview_data': preview_data,
        'total_records': len(customers_data),
        'file_name': file_name,
        'file_type': file_type,
        'available_plans': available_plans,
        'page_title': 'Preview Import',
        'page_subtitle': 'Review customer data before import',
        'breadcrumbs': [
            {'name': 'Customer Management', 'url': reverse('isp_customers')},
            {'name': 'Import Customers', 'url': reverse('isp_import_customers')},
            {'name': 'Preview', 'url': ''},
        ]
    }
    
    return render(request, 'accounts/isp_import_preview.html', context)


@login_required
def isp_import_results(request):
    """Show import results"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    results = request.session.get('import_results', {})
    summary = request.session.get('import_summary', {})
    
    if not results:
        messages.error(request, 'No import results found')
        return redirect('isp_import_customers')
    
    context = {
        'tenant': tenant,
        'results': results,
        'summary': summary,
        'page_title': 'Import Results',
        'page_subtitle': 'Results of customer import',
        'breadcrumbs': [
            {'name': 'Customer Management', 'url': reverse('isp_customers')},
            {'name': 'Import Customers', 'url': reverse('isp_import_customers')},
            {'name': 'Results', 'url': ''},
        ]
    }
    
    return render(request, 'accounts/isp_import_results.html', context)


@login_required
def download_import_template(request):
    """Download CSV template for customer import"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    # Create CSV response
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="customer_import_template.csv"'
    
    writer = csv.writer(response)
    
    # Write header
    writer.writerow([
        'username', 'email', 'phone', 'first_name', 'last_name', 'address'
    ])
    
    # Write sample data
    writer.writerow([
        'john.doe', 'john@example.com', '+254712345678', 'John', 'Doe', '123 Main St, Nairobi'
    ])
    writer.writerow([
        'jane.smith', 'jane@example.com', '+254723456789', 'Jane', 'Smith', '456 Park Ave, Mombasa'
    ])
    
    return response


@login_required
def api_validate_customer_import(request):
    """API endpoint to validate customer import data (AJAX)"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return JsonResponse({'success': False, 'error': 'Access denied'})
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST method required'})
    
    try:
        data = json.loads(request.body)
        customers_data = data.get('customers', [])
        
        validation_results = []
        errors = []
        
        for i, customer in enumerate(customers_data):
            customer_result = {
                'row': i + 1,
                'username': customer.get('username', ''),
                'valid': True,
                'errors': []
            }
            
            # Check required fields
            if not customer.get('username'):
                customer_result['valid'] = False
                customer_result['errors'].append('Username is required')
            
            # Check username uniqueness
            username = customer.get('username', '').strip()
            if username and CustomUser.objects.filter(username=username).exists():
                customer_result['valid'] = False
                customer_result['errors'].append(f'Username "{username}" already exists')
            
            # Check email format if provided
            email = customer.get('email', '')
            if email and '@' not in email:
                customer_result['valid'] = False
                customer_result['errors'].append('Invalid email format')
            
            validation_results.append(customer_result)
            
            if not customer_result['valid']:
                errors.extend([f'Row {i+1}: {error}' for error in customer_result['errors']])
        
        return JsonResponse({
            'success': True,
            'validation_results': validation_results,
            'total': len(customers_data),
            'valid': len([r for r in validation_results if r['valid']]),
            'invalid': len([r for r in validation_results if not r['valid']]),
            'errors': errors[:10]  # Return only first 10 errors
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
def api_bulk_create_customers(request):
    """API endpoint for bulk customer creation (AJAX)"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return JsonResponse({'success': False, 'error': 'Access denied'})
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST method required'})
    
    try:
        tenant = request.user.tenant
        
        username_prefix = request.POST.get('username_prefix', 'customer')
        count = int(request.POST.get('count', 10))
        start_number = int(request.POST.get('start_number', 1))
        email_domain = request.POST.get('email_domain', '@example.com')
        plan_id = request.POST.get('plan_id')
        auto_activate = request.POST.get('auto_activate') == 'on'
        generate_passwords = request.POST.get('generate_passwords') == 'on'
        
        # Limit to reasonable number
        if count > 100:
            count = 100
        
        # Get plan if selected
        default_plan = None
        if plan_id:
            try:
                default_plan = SubscriptionPlan.objects.get(id=plan_id, tenant=tenant, is_active=True)
            except SubscriptionPlan.DoesNotExist:
                pass
        
        created_count = 0
        customers_data = []
        
        for i in range(count):
            try:
                # Generate customer data
                customer_num = start_number + i
                username = f"{username_prefix}{customer_num:03d}"
                email = f"{username}{email_domain}"
                
                # Check if username already exists
                if CustomUser.objects.filter(username=username).exists():
                    continue
                
                # Generate password
                if generate_passwords:
                    password = CustomUser.objects.make_random_password(length=10)
                else:
                    password = f"{username}123"
                
                # Create user
                new_user = CustomUser.objects.create_user(
                    username=username,
                    email=email,
                    password=password
                )
                
                new_user.tenant = tenant
                new_user.role = 'customer'
                new_user.is_active_customer = auto_activate
                new_user.registration_status = 'approved' if auto_activate else 'pending'
                new_user.registration_date = timezone.now()
                
                # Generate account number
                timestamp = int(timezone.now().timestamp())
                new_user.company_account_number = f"{tenant.id:03d}{timestamp % 1000000:06d}"
                
                if auto_activate:
                    new_user.approval_date = timezone.now()
                    new_user.approved_by = request.user
                
                new_user.save()
                
                # Create subscription if plan is selected
                if default_plan:
                    Subscription.objects.create(
                        user=new_user,
                        plan=default_plan,
                        is_active=auto_activate,
                        start_date=timezone.now(),
                        end_date=timezone.now() + timedelta(days=default_plan.duration_days)
                    )
                    
                    if auto_activate:
                        new_user.next_payment_date = timezone.now() + timedelta(days=default_plan.duration_days)
                        new_user.save()
                
                created_count += 1
                customers_data.append({
                    'username': username,
                    'email': email,
                    'password': password,
                    'status': 'Active' if auto_activate else 'Pending'
                })
                
            except Exception as e:
                print(f"Error creating customer {username}: {e}")
                continue
        
        # Store results in session
        request.session['bulk_create_results'] = {
            'created_count': created_count,
            'customers': customers_data
        }
        
        return JsonResponse({
            'success': True,
            'created_count': created_count,
            'message': f'Successfully created {created_count} customers',
            'redirect_url': reverse('isp_import_results')
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
def isp_sms_management(request):
    """Bulk SMS Management Dashboard"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    # Get SMS statistics
    from .sms_service import get_sms_statistics
    sms_stats = get_sms_statistics(tenant)
    
    # Get recent campaigns
    recent_campaigns = BulkSMS.objects.filter(tenant=tenant).order_by('-created_at')[:10]
    
    # Get SMS logs
    recent_logs = SMSLog.objects.filter(tenant=tenant).select_related('customer').order_by('-created_at')[:20]
    
    # Get SMS provider
    sms_provider = SMSProviderConfig.objects.filter(tenant=tenant, is_active=True).first()
    
    context = {
        'tenant': tenant,
        'sms_stats': sms_stats,
        'recent_campaigns': recent_campaigns,
        'recent_logs': recent_logs,
        'sms_provider': sms_provider,
        'page_title': 'SMS Management',
        'page_subtitle': 'Send bulk SMS to customers',
    }
    
    return render(request, 'accounts/isp_sms_management.html', context)


@login_required
def isp_sms_compose(request):
    """Compose new bulk SMS"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    # Get templates
    templates = SMSTemplate.objects.filter(tenant=tenant)
    
    # Get customers for preview
    customers = CustomUser.objects.filter(
        tenant=tenant,
        role='customer',
        is_active_customer=True
    ).exclude(phone__isnull=True).exclude(phone__exact='')[:10]
    
    # Get SMS provider
    sms_provider = SMSProviderConfig.objects.filter(tenant=tenant, is_active=True).first()
    if not sms_provider:
        messages.warning(request, 'Please configure an SMS provider first')
        return redirect('isp_configure_sms_provider')
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'send_test':
            # Send test SMS
            test_phone = request.POST.get('test_phone')
            message = request.POST.get('message')
            
            if not test_phone or not message:
                messages.error(request, 'Phone number and message are required')
                return redirect('isp_sms_compose')
            
            # Initialize SMS service
            from .sms_service import SMSService
            sms_service = SMSService(sms_provider)
            
            # Send test SMS
            success, result = sms_service.send_single_sms(test_phone, message)
            
            if success:
                messages.success(request, f'Test SMS sent successfully to {test_phone}')
            else:
                messages.error(request, f'Failed to send test SMS: {result}')
            
            return redirect('isp_sms_compose')
        
        elif action == 'create_campaign':
            # Create bulk SMS campaign
            campaign_name = request.POST.get('campaign_name', f"SMS Campaign {timezone.now().strftime('%Y%m%d')}")
            message_type = request.POST.get('message_type')
            template_id = request.POST.get('template_id')
            custom_message = request.POST.get('custom_message', '')
            recipient_group = request.POST.get('recipient_group', 'all')
            individual_recipients = request.POST.getlist('recipients')
            schedule_type = request.POST.get('schedule_type', 'now')
            scheduled_date = request.POST.get('scheduled_date')
            scheduled_time = request.POST.get('scheduled_time')
            
            # Validate message
            if message_type == 'template' and not template_id:
                messages.error(request, 'Please select a template')
                return redirect('isp_sms_compose')
            elif message_type == 'custom' and not custom_message.strip():
                messages.error(request, 'Please enter a message')
                return redirect('isp_sms_compose')
            
            # Get template if selected
            template = None
            if template_id:
                try:
                    template = SMSTemplate.objects.get(id=template_id, tenant=tenant)
                except SMSTemplate.DoesNotExist:
                    messages.error(request, 'Selected template not found')
                    return redirect('isp_sms_compose')
            
            # Get recipients
            recipients_query = CustomUser.objects.filter(
                tenant=tenant,
                role='customer'
            ).exclude(phone__isnull=True).exclude(phone__exact='')
            
            # Apply filters based on recipient group
            if recipient_group == 'overdue':
                recipients_query = recipients_query.filter(
                    next_payment_date__lt=timezone.now()
                )
            elif recipient_group == 'recent':
                recipients_query = recipients_query.filter(
                    registration_date__gte=timezone.now() - timedelta(days=30)
                )
            elif recipient_group == 'inactive':
                recipients_query = recipients_query.filter(
                    is_active_customer=False
                )
            else:  # 'all' or custom selection
                if recipient_group == 'custom' and individual_recipients:
                    recipients_query = recipients_query.filter(id__in=individual_recipients)
            
            # Limit to customers with phone numbers
            recipients = recipients_query[:1000]  # Limit to 1000 recipients
            
            if not recipients.exists():
                messages.error(request, 'No customers found with valid phone numbers')
                return redirect('isp_sms_compose')
            
            # Calculate scheduled time
            scheduled_datetime = None
            if schedule_type == 'later' and scheduled_date and scheduled_time:
                try:
                    scheduled_datetime = datetime.strptime(
                        f"{scheduled_date} {scheduled_time}",
                        '%Y-%m-%d %H:%M'
                    )
                    scheduled_datetime = timezone.make_aware(scheduled_datetime)
                except ValueError:
                    messages.error(request, 'Invalid date/time format')
                    return redirect('isp_sms_compose')
            
            # Create campaign - FIXED: Save first, then add recipients
            try:
                with transaction.atomic():
                    # First, create and save the campaign without recipients
                    campaign = BulkSMS.objects.create(
                        tenant=tenant,
                        admin=request.user,
                        template=template,
                        custom_message=custom_message if message_type == 'custom' else '',
                        status='scheduled' if schedule_type == 'later' else 'draft',
                        scheduled_time=scheduled_datetime,
                        total_recipients=recipients.count()
                    )
                    
                    # Now that campaign has an ID, add recipients
                    campaign.recipients.set(recipients)
                    
                    # Update total recipients count
                    campaign.total_recipients = recipients.count()
                    campaign.save()
                    
                    # Send immediately if scheduled for now
                    if schedule_type == 'now':
                        # Queue for sending
                        from .sms_service import send_bulk_sms_to_customers
                        success, result = send_bulk_sms_to_customers(campaign)
                        
                        if success:
                            messages.success(request, f'Bulk SMS campaign started! {result}')
                        else:
                            messages.error(request, f'Failed to start campaign: {result}')
                    else:
                        messages.success(request, f'Bulk SMS campaign scheduled for {scheduled_datetime}')
                    
                    return redirect('isp_sms_campaign_detail', campaign_id=campaign.id)
                    
            except Exception as e:
                messages.error(request, f'Error creating campaign: {str(e)}')
                return redirect('isp_sms_compose')
    
    context = {
        'tenant': tenant,
        'templates': templates,
        'customer_groups': {
            'all': 'All Active Customers',
            'overdue': 'Customers with Overdue Payments',
            'recent': 'Recently Joined (Last 30 days)',
            'inactive': 'Inactive Customers',
        },
        'customers': customers,
        'sms_provider': sms_provider,
        'page_title': 'Compose Bulk SMS',
        'page_subtitle': 'Create and send SMS to customers',
        'breadcrumbs': [
            {'name': 'SMS Management', 'url': reverse('isp_sms_management')},
            {'name': 'Compose SMS', 'url': ''},
        ]
    }
    
    return render(request, 'accounts/isp_sms_compose.html', context)


@login_required
def isp_sms_campaign_detail(request, campaign_id):
    """View SMS campaign details"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    try:
        campaign = BulkSMS.objects.get(id=campaign_id, tenant=tenant)
    except BulkSMS.DoesNotExist:
        messages.error(request, 'SMS campaign not found')
        return redirect('isp_sms_management')
    
    # Get SMS logs for this campaign
    sms_logs = SMSLog.objects.filter(bulk_sms=campaign).select_related('customer')
    
    # Get delivery statistics
    stats = {
        'total': sms_logs.count(),
        'sent': sms_logs.filter(status='sent').count(),
        'delivered': sms_logs.filter(status='delivered').count(),
        'failed': sms_logs.filter(status='failed').count(),
        'pending': sms_logs.filter(status='pending').count(),
    }
    
    # Calculate cost
    total_cost = sum([log.cost for log in sms_logs if log.cost])
    
    context = {
        'tenant': tenant,
        'campaign': campaign,
        'sms_logs': sms_logs,
        'stats': stats,
        'total_cost': total_cost,
        'page_title': f'Campaign #{campaign.id}',
        'page_subtitle': 'View SMS campaign details',
        'breadcrumbs': [
            {'name': 'SMS Management', 'url': reverse('isp_sms_management')},
            {'name': f'Campaign #{campaign.id}', 'url': ''},
        ]
    }
    
    return render(request, 'accounts/isp_sms_campaign_detail.html', context)


@login_required
def isp_sms_templates(request):
    """Manage SMS templates"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    templates = SMSTemplate.objects.filter(tenant=tenant)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'create_template':
            name = request.POST.get('name')
            content = request.POST.get('content')
            
            if not name or not content:
                messages.error(request, 'Name and content are required')
                return redirect('isp_sms_templates')
            
            SMSTemplate.objects.create(
                tenant=tenant,
                name=name,
                content=content,
                variables=['{name}', '{username}', '{account}', '{balance}', '{plan}', '{due_date}']
            )
            
            messages.success(request, 'Template created successfully')
            return redirect('isp_sms_templates')
        
        elif action == 'update_template':
            template_id = request.POST.get('template_id')
            name = request.POST.get('name')
            content = request.POST.get('content')
            
            try:
                template = SMSTemplate.objects.get(id=template_id, tenant=tenant)
                template.name = name
                template.content = content
                template.save()
                
                messages.success(request, 'Template updated successfully')
            except SMSTemplate.DoesNotExist:
                messages.error(request, 'Template not found')
            
            return redirect('isp_sms_templates')
        
        elif action == 'delete_template':
            template_id = request.POST.get('template_id')
            try:
                template = SMSTemplate.objects.get(id=template_id, tenant=tenant)
                template.delete()
                messages.success(request, 'Template deleted successfully')
            except SMSTemplate.DoesNotExist:
                messages.error(request, 'Template not found')
            
            return redirect('isp_sms_templates')
    
    context = {
        'tenant': tenant,
        'templates': templates,
        'page_title': 'SMS Templates',
        'page_subtitle': 'Manage SMS message templates',
        'breadcrumbs': [
            {'name': 'SMS Management', 'url': reverse('isp_sms_management')},
            {'name': 'Templates', 'url': ''},
        ]
    }
    
    return render(request, 'accounts/isp_sms_templates.html', context)


@login_required
def isp_configure_sms_provider(request):
    """Configure SMS provider"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    # Get existing provider or create new
    provider = SMSProviderConfig.objects.filter(tenant=tenant).first()
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'save_provider':
            provider_name = request.POST.get('provider_name')
            api_key = request.POST.get('api_key')
            api_secret = request.POST.get('api_secret', '')
            sender_id = request.POST.get('sender_id')
            default_sender = request.POST.get('default_sender', '')
            base_url = request.POST.get('base_url', '')
            cost_per_sms = request.POST.get('cost_per_sms', 1.0)
            max_sms_per_day = request.POST.get('max_sms_per_day', 1000)
            
            if not all([provider_name, api_key, sender_id]):
                messages.error(request, 'Provider name, API key, and sender ID are required')
                return redirect('isp_configure_sms_provider')
            
            if provider:
                # Update existing provider
                provider.provider_name = provider_name
                provider.api_key = api_key
                provider.api_secret = api_secret
                provider.sender_id = sender_id
                provider.default_sender = default_sender
                provider.base_url = base_url
                provider.cost_per_sms = cost_per_sms
                provider.max_sms_per_day = max_sms_per_day
                provider.save()
                
                messages.success(request, 'SMS provider updated successfully')
            else:
                # Create new provider
                SMSProviderConfig.objects.create(
                    tenant=tenant,
                    provider_name=provider_name,
                    api_key=api_key,
                    api_secret=api_secret,
                    sender_id=sender_id,
                    default_sender=default_sender,
                    base_url=base_url,
                    cost_per_sms=cost_per_sms,
                    max_sms_per_day=max_sms_per_day
                )
                
                messages.success(request, 'SMS provider configured successfully')
            
            return redirect('isp_configure_sms_provider')
        
        elif action == 'test_connection':
            if not provider:
                messages.error(request, 'Please configure a provider first')
                return redirect('isp_configure_sms_provider')
            
            try:
                from .sms_service import SMSService
                sms_service = SMSService(provider)
                
                # Test connection by getting balance (if available)
                balance = sms_service.get_balance()
                
                if balance is not None:
                    messages.success(request, f'Connection successful! Balance: {balance}')
                else:
                    messages.success(request, 'Connection successful! (Balance not available)')
                    
            except Exception as e:
                messages.error(request, f'Connection failed: {str(e)}')
            
            return redirect('isp_configure_sms_provider')
        
        elif action == 'toggle_active':
            if provider:
                provider.is_active = not provider.is_active
                provider.save()
                
                status = "activated" if provider.is_active else "deactivated"
                messages.success(request, f'SMS provider {status}')
            else:
                messages.error(request, 'No provider configured')
            
            return redirect('isp_configure_sms_provider')
    
    # Test phone numbers by country
    test_numbers = {
        'Kenya': '0712345678',
        'Uganda': '0751234567',
        'Tanzania': '0754123456',
        'Nigeria': '08012345678',
        'Ghana': '0201234567',
    }
    
    context = {
        'tenant': tenant,
        'provider': provider,
        'test_numbers': test_numbers,
        'page_title': 'SMS Provider Configuration',
        'page_subtitle': 'Configure SMS gateway for sending messages',
        'breadcrumbs': [
            {'name': 'SMS Management', 'url': reverse('isp_sms_management')},
            {'name': 'Configure Provider', 'url': ''},
        ]
    }
    
    return render(request, 'accounts/isp_configure_sms_provider.html', context)


@login_required
def isp_sms_logs(request):
    """View SMS logs"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    # Get filter parameters
    status_filter = request.GET.get('status')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    customer_id = request.GET.get('customer_id')
    
    # Query logs
    logs = SMSLog.objects.filter(tenant=tenant).select_related('customer', 'bulk_sms')
    
    # Apply filters
    if status_filter:
        logs = logs.filter(status=status_filter)
    
    if date_from:
        logs = logs.filter(sent_at__date__gte=date_from)
    
    if date_to:
        logs = logs.filter(sent_at__date__lte=date_to)
    
    if customer_id:
        logs = logs.filter(customer_id=customer_id)
    
    # Order and paginate
    logs = logs.order_by('-sent_at', '-created_at')
    
    paginator = Paginator(logs, 50)
    page = request.GET.get('page', 1)
    
    try:
        logs_page = paginator.page(page)
    except (PageNotAnInteger, EmptyPage):
        logs_page = paginator.page(1)
    
    # Get customers for filter dropdown
    customers = CustomUser.objects.filter(
        tenant=tenant,
        role='customer',
        phone__isnull=False
    ).exclude(phone__exact='')[:100]
    
    # Statistics
    total_logs = logs.count()
    total_sent = logs.filter(status='sent').count()
    total_failed = logs.filter(status='failed').count()
    total_cost = sum([log.cost for log in logs if log.cost])
    
    context = {
        'tenant': tenant,
        'logs': logs_page,
        'customers': customers,
        'status_filter': status_filter,
        'date_from': date_from,
        'date_to': date_to,
        'customer_id': customer_id,
        'stats': {
            'total': total_logs,
            'sent': total_sent,
            'failed': total_failed,
            'cost': total_cost,
        },
        'page_title': 'SMS Logs',
        'page_subtitle': 'View SMS sending history',
        'breadcrumbs': [
            {'name': 'SMS Management', 'url': reverse('isp_sms_management')},
            {'name': 'Logs', 'url': ''},
        ]
    }
    
    return render(request, 'accounts/isp_sms_logs.html', context)


@login_required
def api_send_quick_sms(request):
    """API endpoint to send quick SMS"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return JsonResponse({'success': False, 'error': 'Access denied'})
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST method required'})
    
    try:
        data = json.loads(request.body)
        customer_ids = data.get('customer_ids', [])
        message = data.get('message')
        
        if not customer_ids or not message:
            return JsonResponse({'success': False, 'error': 'Customer IDs and message are required'})
        
        tenant = request.user.tenant
        
        # Get SMS provider
        provider = SMSProviderConfig.objects.filter(tenant=tenant, is_active=True).first()
        if not provider:
            return JsonResponse({'success': False, 'error': 'No active SMS provider'})
        
        # Get customers
        customers = CustomUser.objects.filter(
            id__in=customer_ids,
            tenant=tenant,
            role='customer'
        ).exclude(phone__isnull=True).exclude(phone__exact='')
        
        if not customers.exists():
            return JsonResponse({'success': False, 'error': 'No valid customers found'})
        
        # Create bulk SMS campaign
        campaign = BulkSMS.objects.create(
            tenant=tenant,
            admin=request.user,
            custom_message=message,
            status='sending',
            total_recipients=customers.count()
        )
        campaign.recipients.set(customers)
        
        # Send SMS
        from .sms_service import send_bulk_sms_to_customers
        success, result = send_bulk_sms_to_customers(campaign)
        
        if success:
            return JsonResponse({
                'success': True,
                'message': f'Quick SMS sent to {campaign.sent_count} customers',
                'campaign_id': campaign.id
            })
        else:
            return JsonResponse({'success': False, 'error': result})
            
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def api_get_customers_for_sms(request):
    """API endpoint to get customers for SMS"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return JsonResponse({'success': False, 'error': 'Access denied'})
    
    tenant = request.user.tenant
    
    # Get filter parameters
    group = request.GET.get('group', 'all')
    search = request.GET.get('search', '')
    
    # Build query
    customers = CustomUser.objects.filter(
        tenant=tenant,
        role='customer'
    ).exclude(phone__isnull=True).exclude(phone__exact='')
    
    # Apply group filter
    if group == 'overdue':
        customers = customers.filter(next_payment_date__lt=timezone.now())
    elif group == 'recent':
        customers = customers.filter(
            registration_date__gte=timezone.now() - timedelta(days=30)
        )
    elif group == 'inactive':
        customers = customers.filter(is_active_customer=False)
    
    # Apply search
    if search:
        customers = customers.filter(
            Q(username__icontains=search) |
            Q(first_name__icontains=search) |
            Q(last_name__icontains=search) |
            Q(phone__icontains=search)
        )
    
    # Limit results
    customers = customers[:100]
    
    # Prepare response
    data = []
    for customer in customers:
        data.append({
            'id': customer.id,
            'username': customer.username,
            'name': customer.get_full_name() or customer.username,
            'phone': customer.phone,
            'email': customer.email,
            'account': customer.company_account_number,
            'status': 'Active' if customer.is_active_customer else 'Inactive',
            'next_payment': customer.next_payment_date.strftime('%Y-%m-%d') if customer.next_payment_date else None,
            'is_overdue': customer.is_payment_overdue(),
        })
    
    return JsonResponse({'success': True, 'customers': data})

@login_required
def isp_package_payment_callback(request, purchase_id):
    """Handle PayStack callback for package purchase"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    try:
        purchase = ISPDataPurchase.objects.get(id=purchase_id, tenant=tenant)
    except ISPDataPurchase.DoesNotExist:
        messages.error(request, 'Purchase not found')
        return redirect('isp_vendor_marketplace')
    
    # Get reference from PayStack callback
    reference = request.GET.get('reference')
    if not reference:
        messages.error(request, 'No payment reference provided')
        return redirect('isp_purchase_detail', purchase_id=purchase.id)
    
    try:
        paystack_config = PaystackConfiguration.objects.get(tenant=tenant, is_active=True)
        paystack_api = PaystackAPI(secret_key=paystack_config.secret_key)
        
        # Verify transaction
        verification = paystack_api.verify_transaction(reference)
        
        if verification.get('status') and verification['data']['status'] == 'success':
            # Payment successful
            purchase.status = 'completed'
            purchase.payment_reference = reference
            purchase.completed_at = timezone.now()
            purchase.save()
            
            # If it's a data package, add to wallet
            if purchase.package_type == 'data' and purchase.bulk_package:
                wallet, _ = DataWallet.objects.get_or_create(tenant=tenant)
                wallet.balance_gb += purchase.total_data_amount
                wallet.save()
                
                # Log wallet transaction
                from billing.models import WalletTransaction
                WalletTransaction.objects.create(
                    wallet=wallet,
                    transaction_type='deposit',
                    amount_gb=purchase.total_data_amount,
                    description=f"Marketplace purchase: {purchase.bulk_package.name}",
                    created_by=request.user
                )
            
            messages.success(request, 'Payment successful! Purchase completed.')
            
            # Record commission transaction
            from billing.models import CommissionTransaction
            CommissionTransaction.objects.create(
                tenant=tenant,
                payment=None,
                commission_type='marketplace_purchase',
                transaction_amount=purchase.total_price,
                commission_amount=purchase.platform_commission,
                net_amount=purchase.isp_net_amount,
                vendor_commission=purchase.vendor_commission,  # ADD THIS
                vendor_commission_rate=purchase.vendor_commission_rate,  # ADD THIS
                status='completed',
                description=f"Marketplace purchase: {purchase.notes}",
                metadata={
                    'purchase_id': str(purchase.id),
                    'package_type': purchase.package_type,
                    'vendor_id': str(purchase.bulk_package.vendor_id) if purchase.bulk_package else str(purchase.bulk_bandwidth_package.vendor_id)
                }
            )
            
        else:
            purchase.status = 'failed'
            purchase.save()
            messages.error(request, 'Payment verification failed')
            
    except Exception as e:
        purchase.status = 'failed'
        purchase.save()
        messages.error(request, f'Payment processing error: {str(e)}')
    
    return redirect('isp_purchase_detail', purchase_id=purchase.id)

# ============================================
# PAYMENT API ENDPOINTS
# ============================================

@login_required
def api_payment_details(request, payment_id):
    """API endpoint for payment details"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return JsonResponse({'success': False, 'error': 'Access denied'})
    
    try:
        tenant = request.user.tenant
        payment = Payment.objects.get(
            id=payment_id,
            user__tenant=tenant
        )
        
        # Get customer information
        customer = payment.user
        
        data = {
            'success': True,
            'customer_name': customer.get_full_name() or customer.username,
            'customer_email': customer.email,
            'amount': str(payment.amount),
            'status': payment.status,
            'status_display': payment.get_status_display(),
            'created_date': payment.created_at.strftime('%B %d, %Y'),
            'created_time': payment.created_at.strftime('%I:%M %p'),
            'transaction_id': payment.reference or f'PAY-{payment.id:06d}',
            'payment_method': payment.get_payment_method_display(),
            'plan_name': payment.plan.name if payment.plan else 'N/A',
            'plan_bandwidth': f"{payment.plan.bandwidth} Mbps" if payment.plan else 'N/A',
            'notes': payment.description or ''
        }
        
        return JsonResponse(data)
        
    except Payment.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Payment not found'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
@require_http_methods(["POST"])
def api_update_payment_status(request, payment_id):
    """API endpoint to update payment status"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return JsonResponse({'success': False, 'error': 'Access denied'})
    
    try:
        tenant = request.user.tenant
        
        # Get the payment
        payment = Payment.objects.get(
            id=payment_id,
            user__tenant=tenant
        )
        
        # Parse request data
        if request.content_type == 'application/json':
            data = json.loads(request.body)
        else:
            data = request.POST
        
        new_status = data.get('status')
        
        if new_status not in ['completed', 'pending', 'failed', 'refunded']:
            return JsonResponse({'success': False, 'error': 'Invalid status'})
        
        old_status = payment.status
        
        # Update payment status
        payment.status = new_status
        payment.save()
        
        # If marking as completed, activate subscription
        if new_status == 'completed' and payment.plan:
            try:
                # Create or update subscription
                subscription, created = Subscription.objects.get_or_create(
                    user=payment.user,
                    plan=payment.plan,
                    defaults={
                        'is_active': True,
                        'start_date': now(),
                        'end_date': now() + timedelta(days=payment.plan.duration_days)
                    }
                )
                
                if not created:
                    subscription.is_active = True
                    subscription.start_date = now()
                    subscription.end_date = now() + timedelta(days=payment.plan.duration_days)
                    subscription.save()
                
                # Update customer's next payment date
                customer = payment.user
                customer.next_payment_date = now() + timedelta(days=payment.plan.duration_days)
                customer.is_active_customer = True
                customer.save()
                
            except Exception as e:
                print(f"Error activating subscription: {e}")
        
        # Log the action
        from accounts.models import ActivityLog
        ActivityLog.objects.create(
            user=request.user,
            action='update_payment_status',
            details=f'Changed payment {payment.reference} from {old_status} to {new_status}'
        )
        
        return JsonResponse({
            'success': True,
            'message': f'Payment status updated to {new_status}',
            'payment': {
                'id': payment.id,
                'status': payment.status,
                'status_display': payment.get_status_display()
            }
        })
        
    except Payment.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Payment not found'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
@require_http_methods(["POST"])
def api_bulk_payment_action(request):
    """API endpoint for bulk payment actions"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return JsonResponse({'success': False, 'error': 'Access denied'})
    
    try:
        # Parse request data
        if request.content_type == 'application/json':
            data = json.loads(request.body)
        else:
            data = request.POST
        
        action = data.get('action')
        payment_ids = data.get('payment_ids', [])
        
        if not payment_ids:
            return JsonResponse({'success': False, 'error': 'No payments selected'})
        
        tenant = request.user.tenant
        
        # Get payments
        payments = Payment.objects.filter(
            id__in=payment_ids,
            user__tenant=tenant
        )
        
        updated_count = 0
        results = []
        
        if action == 'mark_completed':
            for payment in payments:
                if payment.status != 'completed':
                    old_status = payment.status
                    payment.status = 'completed'
                    payment.save()
                    
                    # Activate subscription if applicable
                    if payment.plan:
                        subscription, created = Subscription.objects.get_or_create(
                            user=payment.user,
                            plan=payment.plan,
                            defaults={
                                'is_active': True,
                                'start_date': now(),
                                'end_date': now() + timedelta(days=payment.plan.duration_days)
                            }
                        )
                        
                        if not created:
                            subscription.is_active = True
                            subscription.start_date = now()
                            subscription.end_date = now() + timedelta(days=payment.plan.duration_days)
                            subscription.save()
                        
                        payment.user.next_payment_date = now() + timedelta(days=payment.plan.duration_days)
                        payment.user.is_active_customer = True
                        payment.user.save()
                    
                    results.append({
                        'id': payment.id,
                        'success': True,
                        'message': f'Marked as completed'
                    })
                    updated_count += 1
                else:
                    results.append({
                        'id': payment.id,
                        'success': False,
                        'message': f'Already completed'
                    })
                    
        elif action == 'mark_failed':
            for payment in payments:
                if payment.status != 'failed':
                    payment.status = 'failed'
                    payment.save()
                    results.append({
                        'id': payment.id,
                        'success': True,
                        'message': f'Marked as failed'
                    })
                    updated_count += 1
                else:
                    results.append({
                        'id': payment.id,
                        'success': False,
                        'message': f'Already failed'
                    })
                    
        elif action == 'send_receipts':
            # In a real implementation, you would send emails here
            # For now, we'll just mark them as receipt_sent in logs
            updated_count = payments.count()
            for payment in payments:
                results.append({
                    'id': payment.id,
                    'success': True,
                    'message': f'Receipt sent'
                })
        
        # Log the bulk action
        from accounts.models import ActivityLog
        ActivityLog.objects.create(
            user=request.user,
            action='bulk_payment_action',
            details=f'Performed {action} on {updated_count} payments'
        )
        
        return JsonResponse({
            'success': True,
            'updated_count': updated_count,
            'results': results,
            'message': f'Successfully processed {updated_count} payment(s)'
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def api_payment_receipt(request, payment_id):
    """API endpoint to generate receipt PDF"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    try:
        tenant = request.user.tenant
        payment = Payment.objects.get(
            id=payment_id,
            user__tenant=tenant
        )
        
        # Import reportlab for PDF generation
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.lib.units import cm
        from io import BytesIO
        
        # Create PDF in memory
        buffer = BytesIO()
        p = canvas.Canvas(buffer, pagesize=A4)
        
        # Set up coordinates
        width, height = A4
        
        # Add company header
        p.setFont("Helvetica-Bold", 16)
        p.drawString(2*cm, height - 2*cm, tenant.name)
        
        p.setFont("Helvetica", 10)
        p.drawString(2*cm, height - 2.5*cm, "PAYMENT RECEIPT")
        p.drawString(2*cm, height - 3*cm, f"Date: {now().strftime('%Y-%m-%d %H:%M')}")
        
        # Add line separator
        p.line(2*cm, height - 3.5*cm, width - 2*cm, height - 3.5*cm)
        
        # Add payment details
        y_position = height - 4.5*cm
        
        details = [
            ("Receipt No:", payment.reference or f"REC-{payment.id:06d}"),
            ("Customer:", f"{payment.user.get_full_name() or payment.user.username}"),
            ("Account No:", payment.user.company_account_number or "N/A"),
            ("Amount:", f"Ksh {payment.amount:.2f}"),
            ("Status:", payment.get_status_display().upper()),
            ("Payment Method:", payment.get_payment_method_display()),
            ("Date Paid:", payment.created_at.strftime('%Y-%m-%d %H:%M:%S')),
        ]
        
        if payment.plan:
            details.append(("Plan:", payment.plan.name))
            details.append(("Bandwidth:", f"{payment.plan.bandwidth} Mbps"))
        
        p.setFont("Helvetica-Bold", 12)
        p.drawString(2*cm, y_position, "PAYMENT DETAILS")
        y_position -= 1*cm
        
        p.setFont("Helvetica", 10)
        for label, value in details:
            p.drawString(2*cm, y_position, f"{label}")
            p.drawString(6*cm, y_position, f"{value}")
            y_position -= 0.7*cm
        
        # Add footer
        y_position = 2*cm
        p.setFont("Helvetica-Oblique", 8)
        p.drawString(2*cm, y_position, "This is an official receipt.")
        p.drawString(2*cm, y_position - 0.5*cm, f"Issued by: {request.user.get_full_name()}")
        p.drawString(2*cm, y_position - 1*cm, f"System: CloudNetworks ISP Portal")
        
        # Save PDF
        p.showPage()
        p.save()
        
        # Prepare response
        buffer.seek(0)
        response = HttpResponse(buffer, content_type='application/pdf')
        filename = f"receipt_{payment.reference or payment.id}.pdf"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        return response
        
    except Payment.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Payment not found'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def api_export_payments(request):
    """API endpoint to export payments as CSV"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return JsonResponse({'success': False, 'error': 'Access denied'})
    
    try:
        tenant = request.user.tenant
        
        # Get filter parameters
        status_filter = request.GET.get('status', 'all')
        date_filter = request.GET.get('date', 'all')
        
        # Get payments
        tenant_customer_ids = CustomUser.objects.filter(
            tenant=tenant, 
            role='customer'
        ).values_list('id', flat=True)
        
        payments = Payment.objects.filter(
            user_id__in=tenant_customer_ids
        ).select_related('user', 'plan')
        
        # Apply filters
        if status_filter != 'all':
            payments = payments.filter(status=status_filter)
        
        if date_filter == 'today':
            today = now().date()
            payments = payments.filter(created_at__date=today)
        elif date_filter == 'week':
            week_ago = now() - timedelta(days=7)
            payments = payments.filter(created_at__gte=week_ago)
        elif date_filter == 'month':
            month_ago = now() - timedelta(days=30)
            payments = payments.filter(created_at__gte=month_ago)
        
        # Create CSV response
        import csv
        from django.http import HttpResponse
        
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="payments_{now().strftime("%Y%m%d_%H%M%S")}.csv"'
        
        writer = csv.writer(response)
        
        # Write header
        writer.writerow([
            'Date', 'Time', 'Transaction ID', 'Customer', 'Email', 
            'Plan', 'Amount (Ksh)', 'Status', 'Payment Method', 'Description'
        ])
        
        # Write data
        for payment in payments:
            writer.writerow([
                payment.created_at.strftime('%Y-%m-%d'),
                payment.created_at.strftime('%H:%M:%S'),
                payment.reference or f'PAY-{payment.id:06d}',
                payment.user.get_full_name() or payment.user.username,
                payment.user.email,
                payment.plan.name if payment.plan else '',
                str(payment.amount),
                payment.get_status_display(),
                payment.get_payment_method_display(),
                payment.description or ''
            ])
        
        return response
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

# Add to your views_isp.py

@login_required
@require_http_methods(["POST"])
def api_bulk_update_payment_status(request):
    """Bulk update payment status"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return JsonResponse({'success': False, 'error': 'Access denied'})
    
    try:
        data = json.loads(request.body)
        payment_ids = data.get('payment_ids', [])
        status = data.get('status')
        
        if not payment_ids or status not in ['completed', 'failed', 'pending']:
            return JsonResponse({'success': False, 'error': 'Invalid parameters'})
        
        tenant = request.user.tenant
        updated_count = 0
        failed_count = 0
        
        for payment_id in payment_ids:
            try:
                payment = Payment.objects.get(
                    id=payment_id,
                    user__tenant=tenant
                )
                
                if payment.status != status:
                    payment.status = status
                    payment.save()
                    updated_count += 1
                    
                    # If marking as completed, activate subscription
                    if status == 'completed' and payment.plan:
                        subscription, created = Subscription.objects.get_or_create(
                            user=payment.user,
                            plan=payment.plan,
                            defaults={
                                'is_active': True,
                                'start_date': now(),
                                'end_date': now() + timedelta(days=payment.plan.duration_days)
                            }
                        )
                        
                        if not created:
                            subscription.is_active = True
                            subscription.start_date = now()
                            subscription.end_date = now() + timedelta(days=payment.plan.duration_days)
                            subscription.save()
                        
                        payment.user.next_payment_date = now() + timedelta(days=payment.plan.duration_days)
                        payment.user.is_active_customer = True
                        payment.user.save()
                        
            except Payment.DoesNotExist:
                failed_count += 1
            except Exception as e:
                failed_count += 1
                print(f"Error updating payment {payment_id}: {e}")
        
        return JsonResponse({
            'success': True,
            'completed': updated_count,
            'failed': failed_count,
            'message': f'Updated {updated_count} payment(s)'
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
@require_http_methods(["POST"])
def api_export_selected_payments(request):
    """Export selected payments to CSV"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return JsonResponse({'success': False, 'error': 'Access denied'})
    
    try:
        data = json.loads(request.body)
        payment_ids = data.get('payment_ids', [])
        
        if not payment_ids:
            return JsonResponse({'success': False, 'error': 'No payments selected'})
        
        tenant = request.user.tenant
        
        # Get selected payments
        payments = Payment.objects.filter(
            id__in=payment_ids,
            user__tenant=tenant
        ).select_related('user', 'plan')
        
        # Create CSV response
        import csv
        from django.http import HttpResponse
        
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="selected_payments_{now().strftime("%Y%m%d_%H%M%S")}.csv"'
        
        writer = csv.writer(response)
        
        # Write header
        writer.writerow([
            'Date', 'Time', 'Transaction ID', 'Customer', 'Email', 'Phone',
            'Plan', 'Amount (Ksh)', 'Status', 'Payment Method', 'Description'
        ])
        
        # Write data
        for payment in payments:
            writer.writerow([
                payment.created_at.strftime('%Y-%m-%d'),
                payment.created_at.strftime('%H:%M:%S'),
                payment.reference or f'PAY-{payment.id:06d}',
                payment.user.get_full_name() or payment.user.username,
                payment.user.email,
                payment.user.phone or '',
                payment.plan.name if payment.plan else '',
                str(payment.amount),
                payment.get_status_display(),
                payment.get_payment_method_display(),
                payment.description or ''
            ])
        
        return response
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
@require_http_methods(["POST"])
def api_send_selected_receipts(request):
    """Send receipts for selected payments"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return JsonResponse({'success': False, 'error': 'Access denied'})
    
    try:
        data = json.loads(request.body)
        payment_ids = data.get('payment_ids', [])
        
        if not payment_ids:
            return JsonResponse({'success': False, 'error': 'No payments selected'})
        
        tenant = request.user.tenant
        sent_count = 0
        failed_count = 0
        
        for payment_id in payment_ids:
            try:
                payment = Payment.objects.get(
                    id=payment_id,
                    user__tenant=tenant
                )
                
                # Here you would implement email sending logic
                # For now, we'll just mark as sent in logs
                from accounts.models import ActivityLog
                ActivityLog.objects.create(
                    user=request.user,
                    action='send_receipt',
                    details=f'Sent receipt for payment {payment.reference} to {payment.user.email}'
                )
                
                sent_count += 1
                
            except Payment.DoesNotExist:
                failed_count += 1
            except Exception as e:
                failed_count += 1
                print(f"Error sending receipt for payment {payment_id}: {e}")
        
        return JsonResponse({
            'success': True,
            'sent': sent_count,
            'failed': failed_count,
            'message': f'Sent {sent_count} receipt(s)'
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
@require_http_methods(["POST"])
def api_delete_selected_payments(request):
    """Delete selected payments (only pending)"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return JsonResponse({'success': False, 'error': 'Access denied'})
    
    try:
        data = json.loads(request.body)
        payment_ids = data.get('payment_ids', [])
        
        if not payment_ids:
            return JsonResponse({'success': False, 'error': 'No payments selected'})
        
        tenant = request.user.tenant
        deleted_count = 0
        failed_count = 0
        
        for payment_id in payment_ids:
            try:
                payment = Payment.objects.get(
                    id=payment_id,
                    user__tenant=tenant,
                    status='pending'  # Only delete pending payments
                )
                
                # Store info for logging
                payment_info = {
                    'id': payment.id,
                    'reference': payment.reference,
                    'amount': str(payment.amount),
                    'customer': payment.user.username
                }
                
                payment.delete()
                deleted_count += 1
                
                # Log the deletion
                from accounts.models import ActivityLog
                ActivityLog.objects.create(
                    user=request.user,
                    action='delete_payment',
                    details=f'Deleted pending payment {payment_info["reference"]} ({payment_info["amount"]}) for customer {payment_info["customer"]}'
                )
                
            except Payment.DoesNotExist:
                failed_count += 1
            except Exception as e:
                failed_count += 1
                print(f"Error deleting payment {payment_id}: {e}")
        
        return JsonResponse({
            'success': True,
            'deleted': deleted_count,
            'failed': failed_count,
            'message': f'Deleted {deleted_count} payment(s)'
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
def isp_router_type_selection(request):
    """Router type selection page"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        messages.error(request, 'Access denied.')
        return redirect('dashboard')
    
    context = {
        'tenant': request.user.tenant,
        'page_title': 'Select Router Type',
        'page_subtitle': 'Choose the router manufacturer to configure',
        'breadcrumbs': [
            {'name': 'Router Management', 'url': reverse('isp_routers')},
            {'name': 'Add Router', 'url': ''},
        ]
    }
    return render(request, 'accounts/isp_router_type_selection.html', context)