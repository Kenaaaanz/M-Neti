from decimal import Decimal
from multiprocessing.sharedctypes import Value
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.forms import DecimalField
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse, HttpResponseForbidden, HttpResponse
from django.contrib import messages
from django.utils import timezone
from datetime import timedelta, datetime
from django.db.models import Count, Sum, Q, F, Case, When, Avg
from django.db.models.functions import ExtractYear, ExtractMonth
import json
import requests
from django.conf import settings
from django.urls import reverse
from accounts import models
from accounts.models import AdminLog, AdminLog, Tenant, CustomUser, LoginActivity, VerificationLog
from router_manager.models import Router, Device
from billing.models import Payment, SubscriptionPlan, Subscription, PaystackConfiguration
from django.db.models import Value, Case, When, DecimalField, Avg  # CORRECT
from django.core.paginator import Paginator
import csv

# Add these new views after existing ones:


@staff_member_required
def superadmin_dashboard(request):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    # Platform statistics
    total_tenants = Tenant.objects.count()
    active_tenants = Tenant.objects.filter(is_active=True).count()
    inactive_tenants = total_tenants - active_tenants
    total_users = CustomUser.objects.count()
    active_users = CustomUser.objects.filter(is_active=True).count()
    total_customers = CustomUser.objects.filter(role='customer').count()
    total_routers = Router.objects.count()
    total_devices = Device.objects.count()
    
    # Add pending approvals count
    pending_approvals = CustomUser.objects.filter(registration_status='pending').count()
    
    # Revenue calculations - Fixed relationship
    total_revenue = Payment.objects.filter(status='completed').aggregate(
        total=Sum('amount')
    )['total'] or 0
    
    monthly_revenue = Payment.objects.filter(
        status='completed',
        created_at__gte=timezone.now() - timedelta(days=30)
    ).aggregate(total=Sum('amount'))['total'] or 0
    
    # Recent activity - Fixed relationships
    recent_tenants = Tenant.objects.all().order_by('-created_at')[:5]
    recent_payments = Payment.objects.select_related('user', 'plan').order_by('-created_at')[:10]
    recent_logins = LoginActivity.objects.select_related('user', 'tenant').order_by('-timestamp')[:10]
    
    # Chart data - Plan distribution
    plan_distribution = {
        'labels': ['Starter', 'Professional', 'Enterprise'],
        'data': [
            Tenant.objects.filter(subscription_plan='starter').count(),
            Tenant.objects.filter(subscription_plan='professional').count(),
            Tenant.objects.filter(subscription_plan='enterprise').count(),
        ]
    }
    
    # User growth (last 7 days)
    user_growth_data = []
    user_growth_labels = []
    for i in range(6, -1, -1):
        date = timezone.now() - timedelta(days=i)
        count = CustomUser.objects.filter(
            date_joined__date=date.date()
        ).count()
        user_growth_data.append(count)
        user_growth_labels.append(date.strftime('%a'))
    
    user_growth = {
        'labels': user_growth_labels,
        'data': user_growth_data
    }
    
    # Revenue by month (last 6 months) - Fixed
    revenue_months = []
    revenue_data = []
    for i in range(5, -1, -1):
        month_start = timezone.now().replace(day=1) - timedelta(days=30*i)
        month_name = month_start.strftime('%b')
        
        month_revenue = Payment.objects.filter(
            status='completed',
            created_at__year=month_start.year,
            created_at__month=month_start.month
        ).aggregate(total=Sum('amount'))['total'] or 0
        
        revenue_months.append(month_name)
        revenue_data.append(float(month_revenue))
    
    # System metrics
    online_routers = Router.objects.filter(is_online=True).count()
    online_devices = Device.objects.filter(is_online=True).count()
    
    # FIXED: Critical alerts calculation - Use date-based filtering instead of is_active field
    now = timezone.now()
    overdue_subscriptions = Subscription.objects.filter(
        end_date__lt=now
    ).count()
    
    low_balance_tenants = Tenant.objects.filter(
        subscription_end__lt=now + timedelta(days=7)
    ).count()
    
    critical_alerts = overdue_subscriptions + low_balance_tenants
    
    context = {
        # Core statistics
        'total_tenants': total_tenants,
        'active_tenants': active_tenants,
        'inactive_tenants': inactive_tenants,
        'total_users': total_users,
        'active_users': active_users,
        'total_customers': total_customers,
        'total_routers': total_routers,
        'online_routers': online_routers,
        'total_devices': total_devices,
        'online_devices': online_devices,
        'pending_approvals': pending_approvals,  # Add this
        
        # Financial data
        'total_revenue': total_revenue,
        'monthly_revenue': monthly_revenue,
        
        # Recent activity
        'recent_tenants': recent_tenants,
        'recent_payments': recent_payments,
        'recent_logins': recent_logins,
        
        # Chart data
        'plan_distribution': json.dumps(plan_distribution),
        'user_growth': json.dumps(user_growth),
        'revenue_months': json.dumps(revenue_months),
        'revenue_data': json.dumps(revenue_data),
        
        # System health
        'system_uptime': 99.8,
        'critical_alerts': critical_alerts,
        'pending_tenants_count': 0,
        
        # Additional context
        'overdue_subscriptions': overdue_subscriptions,
        'low_balance_tenants': low_balance_tenants,
    }
    
    # Bulk Data Statistics
    bulk_data_stats = {
        'total_packages': BulkDataPackage.objects.count(),
        'active_packages': BulkDataPackage.objects.filter(is_active=True).count(),
        'total_bulk_revenue': ISPBulkPurchase.objects.filter(
            payment_status='completed'
        ).aggregate(total=Sum('total_price'))['total'] or Decimal('0'),
        'platform_commission': CommissionTransaction.objects.aggregate(
            total=Sum('commission_amount')
        )['total'] or Decimal('0'),
    }

    # Add to context
    context.update({
        'bulk_data_stats': bulk_data_stats,
    })
    
    return render(request, 'admin/superadmin_dashboard.html', context)

@staff_member_required
def superadmin_users(request):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    users = CustomUser.objects.select_related('tenant').order_by('-date_joined')
    tenants = Tenant.objects.all()  # Add this for the tenant filter
    
    # Statistics
    total_users = users.count()
    superadmins = users.filter(role='superadmin').count()
    isp_admins = users.filter(role='isp_admin').count()
    isp_staff = users.filter(role='isp_staff').count()
    customers = users.filter(role='customer').count()
    pending_approvals = users.filter(registration_status='pending').count()
    
    context = {
        'users': users,
        'tenants': tenants,
        'total_users': total_users,
        'superadmins': superadmins,
        'isp_admins': isp_admins,
        'isp_staff': isp_staff,
        'customers': customers,
        'pending_approvals': pending_approvals,
        'page_title': 'User Management',
        'page_subtitle': 'Manage all platform users',
    }
    
    return render(request, 'admin/superadmin_users.html', context)

@staff_member_required
def superadmin_view_user_details(request, user_id):
    """View user details"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    user = get_object_or_404(CustomUser, id=user_id)
    context = {
        'user': user,
        'page_title': f'User Details: {user.get_full_name()}',
    }
    return render(request, 'admin/superadmin_user_detail.html', context)

@staff_member_required
def superadmin_edit_user(request, user_id):
    """Edit user details"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    user = get_object_or_404(CustomUser, id=user_id)
    
    if request.method == 'POST':
        user.first_name = request.POST.get('first_name', user.first_name)
        user.last_name = request.POST.get('last_name', user.last_name)
        user.email = request.POST.get('email', user.email)
        user.phone = request.POST.get('phone', user.phone)
        user.role = request.POST.get('role', user.role)
        user.save()
        messages.success(request, f'User {user.username} updated successfully')
        return redirect('superadmin_users')
    
    context = {
        'user': user,
        'page_title': f'Edit User: {user.get_full_name()}',
    }
    return render(request, 'admin/superadmin_edit_user.html', context)

@staff_member_required
def superadmin_export_users(request):
    """Export users as CSV"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="users_export.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['ID', 'Username', 'Email', 'First Name', 'Last Name', 'Role', 'Tenant', 'Status', 'Registration Status'])
    
    users = CustomUser.objects.select_related('tenant').all()
    for user in users:
        writer.writerow([
            user.id,
            user.username,
            user.email,
            user.first_name,
            user.last_name,
            user.get_role_display(),
            user.tenant.name if user.tenant else 'N/A',
            'Active' if user.is_active else 'Inactive',
            user.get_registration_status_display(),
        ])
    
    return response

# Update the verification views to return user data
@staff_member_required

@require_http_methods(["POST"])
def approve_user(request, user_id):
    """Approve a user account"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    try:
        user = get_object_or_404(CustomUser, id=user_id)
        
        # Get request data
        data = json.loads(request.body) if request.body else {}
        send_email = data.get('send_email', True)
        notes = data.get('notes', '')
        
        # Update user status
        user.registration_status = 'approved'
        user.is_active_customer = True
        user.approval_date = timezone.now()
        user.approved_by = request.user
        user.save()
        
        # TODO: Send approval email if requested
        if send_email:
            # Implement email sending logic here
            print(f"Would send approval email to {user.email}")
        
        return JsonResponse({
            'status': 'success',
            'message': f'User {user.username} approved successfully',
            'user_data': {
                'id': str(user.id),
                'registration_status': user.registration_status,
                'is_active_customer': user.is_active_customer,
                'approval_date': user.approval_date.isoformat() if user.approval_date else None,
            }
        })
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': f'Error approving user: {str(e)}'
        }, status=400)

@staff_member_required
@require_http_methods(["POST"])
def reject_user(request, user_id):
    """Reject a user account"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    try:
        user = get_object_or_404(CustomUser, id=user_id)
        
        # Get request data
        data = json.loads(request.body) if request.body else {}
        send_email = data.get('send_email', True)
        notes = data.get('notes', '')
        
        # Update user status
        user.registration_status = 'rejected'
        user.is_active_customer = False
        user.save()
        
        # TODO: Send rejection email if requested
        if send_email:
            # Implement email sending logic here
            print(f"Would send rejection email to {user.email}")
        
        return JsonResponse({
            'status': 'success',
            'message': f'User {user.username} rejected successfully',
            'user_data': {
                'id': str(user.id),
                'registration_status': user.registration_status,
                'is_active_customer': user.is_active_customer,
            }
        })
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': f'Error rejecting user: {str(e)}'
        }, status=400)

@staff_member_required
@require_http_methods(["POST"])
def revoke_approval(request, user_id):
    """Revoke user approval"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    try:
        user = get_object_or_404(CustomUser, id=user_id)
        
        # Only revoke if currently approved
        if user.registration_status == 'approved':
            user.registration_status = 'pending'
            user.is_active_customer = False
            user.approval_date = None
            user.approved_by = None
            user.save()
            
            return JsonResponse({
                'status': 'success',
                'message': f'Approval revoked for {user.username}',
                'user_data': {
                    'id': str(user.id),
                    'registration_status': user.registration_status,
                    'is_active_customer': user.is_active_customer,
                    'approval_date': None,
                }
            })
        else:
            return JsonResponse({
                'status': 'error',
                'message': 'User is not currently approved'
            }, status=400)
            
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': f'Error revoking approval: {str(e)}'
        }, status=400)

@staff_member_required
@require_http_methods(["POST"])
def bulk_approve_users(request):
    """Bulk approve multiple users"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    try:
        data = json.loads(request.body) if request.body else {}
        user_ids = data.get('user_ids', [])
        
        if not user_ids:
            return JsonResponse({
                'status': 'error',
                'message': 'No users selected'
            }, status=400)
        
        approved_users = []
        approved_count = 0
        for user_id in user_ids:
            try:
                user = CustomUser.objects.get(id=user_id, registration_status='pending')
                user.registration_status = 'approved'
                user.is_active_customer = True
                user.approval_date = timezone.now()
                user.approved_by = request.user
                user.save()
                approved_count += 1
                approved_users.append(str(user.id))
            except CustomUser.DoesNotExist:
                continue
        
        return JsonResponse({
            'status': 'success',
            'message': f'Approved {approved_count} user(s) successfully',
            'approved_users': approved_users,
            'approved_count': approved_count
        })
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': f'Error in bulk approval: {str(e)}'
        }, status=400)

@staff_member_required
@require_http_methods(["POST"])
def bulk_reject_users(request):
    """Bulk reject multiple users"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    try:
        data = json.loads(request.body) if request.body else {}
        user_ids = data.get('user_ids', [])
        
        if not user_ids:
            return JsonResponse({
                'status': 'error',
                'message': 'No users selected'
            }, status=400)
        
        rejected_users = []
        rejected_count = 0
        for user_id in user_ids:
            try:
                user = CustomUser.objects.get(id=user_id, registration_status='pending')
                user.registration_status = 'rejected'
                user.is_active_customer = False
                user.save()
                rejected_count += 1
                rejected_users.append(str(user.id))
            except CustomUser.DoesNotExist:
                continue
        
        return JsonResponse({
            'status': 'success',
            'message': f'Rejected {rejected_count} user(s) successfully',
            'rejected_users': rejected_users,
            'rejected_count': rejected_count
        })
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': f'Error in bulk rejection: {str(e)}'
        }, status=400)

@staff_member_required
@require_http_methods(["POST"])
def toggle_user_status(request, user_id):
    """Toggle user active status"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    try:
        user = get_object_or_404(CustomUser, id=user_id)
        
        # Don't allow deactivating yourself
        if user.id == request.user.id:
            return JsonResponse({
                'status': 'error',
                'message': 'You cannot deactivate your own account'
            }, status=400)
        
        user.is_active = not user.is_active
        user.save()
        
        status = "activated" if user.is_active else "deactivated"
        
        return JsonResponse({
            'status': 'success',
            'message': f'User {status} successfully',
            'user_data': {
                'id': str(user.id),
                'is_active': user.is_active,
            }
        })
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': f'Error toggling user status: {str(e)}'
        }, status=400)
    

    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=400)

@staff_member_required
def delete_user(request, user_id):
    """Delete a user account"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    if request.method == 'POST':
        try:
            user = get_object_or_404(CustomUser, id=user_id)
            
            # Don't allow deleting yourself
            if user.id == request.user.id:
                return JsonResponse({
                    'status': 'error',
                    'message': 'You cannot delete your own account'
                }, status=400)
            
            username = user.username
            user.delete()
            
            messages.success(request, f"User {username} has been deleted.")
            
            return JsonResponse({
                'status': 'success',
                'message': f'User {username} deleted successfully'
            })
            
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': f'Error deleting user: {str(e)}'
            }, status=400)
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=400)

# Keep your existing views below (they remain the same)
@staff_member_required
@staff_member_required
def superadmin_tenants(request):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    tenants = Tenant.objects.all().order_by('-created_at')
    
    # Add statistics for each tenant
    for tenant in tenants:
        tenant.customer_count = CustomUser.objects.filter(
            tenant=tenant, role='customer'
        ).count()
        
        tenant.total_revenue = Payment.objects.filter(
            user__tenant=tenant,
            status='completed'
        ).aggregate(total=Sum('amount'))['total'] or 0
        
        # Monthly revenue
        month_start = timezone.now().replace(day=1)
        tenant.monthly_revenue = Payment.objects.filter(
            user__tenant=tenant,
            status='completed',
            created_at__gte=month_start
        ).aggregate(total=Sum('amount'))['total'] or 0
    
    # Add statistics
    total_tenants = tenants.count()
    active_tenants = tenants.filter(is_active=True).count()
    
    # Calculate total customers across all tenants
    total_customers = CustomUser.objects.filter(role='customer').count()
    
    if request.method == 'POST':
        action = request.POST.get('action')
        tenant_id = request.POST.get('tenant_id')
        
        try:
            tenant = Tenant.objects.get(id=tenant_id)
            
            if action == 'toggle_active':
                tenant.is_active = not tenant.is_active
                tenant.save()
                status = "activated" if tenant.is_active else "deactivated"
                messages.success(request, f"Tenant {tenant.name} {status} successfully!")
                
            elif action == 'delete':
                tenant_name = tenant.name
                # Check if tenant has users before deleting
                user_count = CustomUser.objects.filter(tenant=tenant).count()
                if user_count > 0:
                    messages.error(request, f"Cannot delete {tenant_name}. There are {user_count} users associated with this tenant.")
                else:
                    tenant.delete()
                    messages.success(request, f"Tenant {tenant_name} deleted successfully!")
                    
        except Tenant.DoesNotExist:
            messages.error(request, "Tenant not found")
        
        return redirect('superadmin_tenants')
    
    # Pagination
    paginator = Paginator(tenants, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'tenants': page_obj,
        'total_tenants': total_tenants,
        'active_tenants': active_tenants,
        'inactive_tenants': total_tenants - active_tenants,
        'total_customers': total_customers,
        'page_obj': page_obj,
        'page_title': 'ISP Management',
        'page_subtitle': 'Manage all Internet Service Providers',
    }
    
    return render(request, 'admin/superadmin_tenants.html', context)

@staff_member_required
def superadmin_create_tenant(request):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    if request.method == 'POST':
        name = request.POST.get('name')
        company_name = request.POST.get('company_name')
        subdomain = request.POST.get('subdomain')
        contact_email = request.POST.get('contact_email')
        contact_phone = request.POST.get('contact_phone')
        subscription_plan = request.POST.get('subscription_plan', 'starter')
        
        # Additional fields from the enhanced form
        primary_color = request.POST.get('primary_color', '#4361ee')
        secondary_color = request.POST.get('secondary_color', '#3a0ca3')
        bandwidth_limit = request.POST.get('bandwidth_limit', 1000)
        client_limit = request.POST.get('client_limit', 1000)
        auto_disconnect_enabled = request.POST.get('auto_disconnect_enabled') == 'on'
        
        try:
            # Validate subdomain uniqueness
            if Tenant.objects.filter(subdomain=subdomain.lower()).exists():
                messages.error(request, f"Subdomain '{subdomain}' is already taken. Please choose a different one.")
                return redirect('superadmin_create_tenant')
            
            # Create tenant with all fields
            tenant = Tenant.objects.create(
                name=name,
                company_name=company_name,
                subdomain=subdomain.lower(),
                contact_email=contact_email,
                contact_phone=contact_phone,
                subscription_plan=subscription_plan,
                subscription_end=timezone.now() + timedelta(days=30),
                
                # Additional fields
                primary_color=primary_color,
                secondary_color=secondary_color,
                bandwidth_limit=int(bandwidth_limit),
                client_limit=int(client_limit),
                auto_disconnect_enabled=auto_disconnect_enabled,
            )
            
            # Create default subscription plans for the tenant
            plans_data = [
                {"name": "Basic", "price": 29.99, "bandwidth": 100, "duration_days": 30},
                {"name": "Premium", "price": 49.99, "bandwidth": 250, "duration_days": 30},
                {"name": "Ultimate", "price": 79.99, "bandwidth": 500, "duration_days": 30},
            ]
            
            for plan_data in plans_data:
                SubscriptionPlan.objects.create(
                    tenant=tenant,
                    **plan_data
                )
            
            messages.success(request, f"✅ Tenant '{name}' created successfully!")
            messages.info(request, f"🌐 Dashboard URL: https://{tenant.primary_domain}/isp/dashboard/")
            messages.info(request, f"👤 Default login: {contact_email} (password will be set separately)")
            
            return redirect('superadmin_tenants')
            
        except Exception as e:
            messages.error(request, f"❌ Error creating tenant: {str(e)}")
    
    context = {
        'page_title': 'Create New ISP',
        'page_subtitle': 'Add a new Internet Service Provider to the platform',
    }
    
    return render(request, 'admin/superadmin_create_tenant.html', context)

@staff_member_required
def superadmin_kill_switch(request):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    tenants = Tenant.objects.all()
    
    if request.method == 'POST':
        action = request.POST.get('action')
        tenant_id = request.POST.get('tenant_id')
        
        if action == 'disable_platform':
            # Disable all tenants and customers
            Tenant.objects.update(is_active=False)
            CustomUser.objects.filter(role='customer').update(is_active_customer=False)
            
            # Block all online devices
            Device.objects.filter(is_online=True).update(is_blocked=True)
            
            messages.warning(request, "🚨 PLATFORM DISABLED - All services stopped")
            
        elif action == 'enable_platform':
            # Re-enable platform
            Tenant.objects.update(is_active=True)
            CustomUser.objects.filter(role='customer').update(is_active_customer=True)
            Device.objects.update(is_blocked=False)
            
            messages.success(request, "✅ Platform enabled - All services restored")
            
        elif action == 'disable_tenant':
            if tenant_id:
                tenant = get_object_or_404(Tenant, id=tenant_id)
                tenant.is_active = False
                tenant.save()
                
                # Disable all customers of this tenant
                CustomUser.objects.filter(tenant=tenant, role='customer').update(is_active_customer=False)
                
                # Block devices for this tenant
                Device.objects.filter(user__tenant=tenant, is_online=True).update(is_blocked=True)
                
                messages.warning(request, f"🚨 Tenant '{tenant.name}' disabled")
            else:
                messages.error(request, "No tenant selected")
        
        return redirect('superadmin_kill_switch')
    
    context = {
        'tenants': tenants,
        'total_tenants': tenants.count(),
        'active_tenants': tenants.filter(is_active=True).count(),
        'page_title': 'Emergency Kill Switch',
        'page_subtitle': 'Platform-wide emergency controls',
    }
    
    return render(request, 'admin/superadmin_kill_switch.html', context)

@staff_member_required
def superadmin_analytics(request):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    # Fixed: Get top tenants by revenue - use the correct relationship
    # Since Payment has a user field, and user has a tenant field
    from django.db.models import Sum, Count, Q
    from django.utils import timezone
    from datetime import timedelta
    
    # Get tenants with their total revenue
    tenant_revenues = []
    for tenant in Tenant.objects.all():
        # Calculate revenue for this tenant through users
        tenant_revenue = Payment.objects.filter(
            user__tenant=tenant,
            status='completed'
        ).aggregate(total=Sum('amount'))['total'] or 0
        
        if tenant_revenue > 0:
            tenant_revenues.append({
                'tenant': tenant,
                'total_revenue': tenant_revenue
            })
    
    # Sort by revenue and get top 10
    top_tenants_by_revenue = sorted(tenant_revenues, key=lambda x: x['total_revenue'], reverse=True)[:10]
    
    # User growth in last 30 days
    user_growth_30d = CustomUser.objects.filter(
        date_joined__gte=timezone.now() - timedelta(days=30)
    ).count()
    
    # Payment success rate
    payment_stats = Payment.objects.aggregate(
        total=Count('id'),
        successful=Count('id', filter=Q(status='completed')),
        failed=Count('id', filter=Q(status='failed'))
    )
    
    if payment_stats['total'] > 0:
        success_rate = (payment_stats['successful'] / payment_stats['total']) * 100
    else:
        success_rate = 0
    
    # Additional analytics data
    active_tenants_count = Tenant.objects.filter(is_active=True).count()
    total_customers = CustomUser.objects.filter(role='customer').count()
    active_customers = CustomUser.objects.filter(role='customer', is_active_customer=True).count()
    
    # Revenue by plan type
    revenue_by_plan = Payment.objects.filter(status='completed').values(
        'plan__name'
    ).annotate(
        total_revenue=Sum('amount'),
        payment_count=Count('id')
    ).order_by('-total_revenue')
    
    # Monthly growth data
    monthly_growth = []
    for i in range(5, -1, -1):
        month_start = timezone.now().replace(day=1) - timedelta(days=30*i)
        month_name = month_start.strftime('%b %Y')
        
        # New users this month
        new_users = CustomUser.objects.filter(
            date_joined__year=month_start.year,
            date_joined__month=month_start.month
        ).count()
        
        # Revenue this month
        month_revenue = Payment.objects.filter(
            status='completed',
            created_at__year=month_start.year,
            created_at__month=month_start.month
        ).aggregate(total=Sum('amount'))['total'] or 0
        
        monthly_growth.append({
            'month': month_name,
            'new_users': new_users,
            'revenue': month_revenue
        })
    
    context = {
        'top_tenants_by_revenue': top_tenants_by_revenue,
        'user_growth_30d': user_growth_30d,
        'payment_success_rate': round(success_rate, 1),
        'active_tenants_count': active_tenants_count,
        'total_customers': total_customers,
        'active_customers': active_customers,
        'revenue_by_plan': revenue_by_plan,
        'monthly_growth': monthly_growth,
        'payment_stats': payment_stats,
        'page_title': 'Platform Analytics',
        'page_subtitle': 'Detailed platform insights and metrics',
    }
    
    return render(request, 'admin/superadmin_analytics.html', context)

@staff_member_required
def superadmin_settings(request):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    context = {
        'page_title': 'System Settings',
        'page_subtitle': 'Platform configuration and settings',
    }
    
    return render(request, 'admin/superadmin_settings.html', context)


@staff_member_required
def superadmin_tenant_detail(request, tenant_id):
    """Detailed view for a specific ISP"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    tenant = get_object_or_404(Tenant, id=tenant_id)
    
    # Calculate statistics
    customer_count = CustomUser.objects.filter(tenant=tenant, role='customer').count()
    staff_count = CustomUser.objects.filter(tenant=tenant, role__in=['isp_admin', 'isp_staff']).count()
    
    # Get revenue data
    total_revenue = Payment.objects.filter(
        user__tenant=tenant,
        status='completed'
    ).aggregate(total=Sum('amount'))['total'] or 0
    
    # Get active subscriptions count
    active_subscriptions = Subscription.objects.filter(
        user__tenant=tenant,
        is_active=True
    ).count()
    
    # Calculate payment success rate
    payment_stats = Payment.objects.filter(user__tenant=tenant).aggregate(
        total=Count('id'),
        successful=Count('id', filter=Q(status='completed'))
    )
    
    payment_success_rate = 0
    if payment_stats['total'] > 0:
        payment_success_rate = round((payment_stats['successful'] / payment_stats['total']) * 100, 1)
    
    # Get recent payments
    recent_payments = Payment.objects.filter(
        user__tenant=tenant
    ).select_related('plan', 'user').order_by('-created_at')[:5]
    
    # Get staff members
    staff_members = CustomUser.objects.filter(
        tenant=tenant,
        role__in=['isp_admin', 'isp_staff']
    ).order_by('-date_joined')[:5]
    
    # Get recent customers
    recent_customers = CustomUser.objects.filter(
        tenant=tenant,
        role='customer'
    ).order_by('-date_joined')[:5]
    
    context = {
        'tenant': tenant,
        'customer_count': customer_count,
        'staff_count': staff_count,
        'total_revenue': total_revenue,
        'active_subscriptions': active_subscriptions,
        'payment_success_rate': payment_success_rate,
        'recent_payments': recent_payments,
        'staff_members': staff_members,
        'recent_customers': recent_customers,
        'page_title': f'ISP Details: {tenant.name}',
        'page_subtitle': 'Detailed ISP information and statistics',
    }
    
    return render(request, 'admin/superadmin_tenant_detail.html', context)

@staff_member_required
def superadmin_tenant_verify(request, tenant_id):
    """Verify an ISP with documentation review"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    tenant = get_object_or_404(Tenant, id=tenant_id)
    
    # For AJAX requests (from JavaScript fetch calls)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.content_type == 'application/json':
        return handle_ajax_verification_request(request, tenant)
    
    # For regular POST requests (form submissions)
    if request.method == 'POST':
        return handle_post_verification_request(request, tenant)
    
    # GET request - show verification page
    return render_verification_page(request, tenant)

def handle_ajax_verification_request(request, tenant):
    """Handle AJAX verification requests from JavaScript"""
    try:
        data = json.loads(request.body) if request.body else {}
        action = data.get('action', 'verify')
        status = data.get('status', 'verified')
        notes = data.get('notes', '')
        
        if action == 'verify':
            return handle_verify_action(tenant, notes, request.user)
        elif action == 'unverify':
            return handle_unverify_action(tenant, notes, request.user)
        elif action == 'update_status':
            return handle_update_status_action(tenant, status, notes, request.user)
        elif action == 'request_document':
            return handle_request_document_action(tenant, data.get('document_type'), request.user)
        else:
            return JsonResponse({
                'success': False,
                'message': 'Invalid action'
            }, status=400)
            
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'message': 'Invalid JSON data'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error: {str(e)}'
        }, status=500)

def handle_post_verification_request(request, tenant):
    """Handle regular form POST requests"""
    action = request.POST.get('action')
    notes = request.POST.get('notes', '')
    
    if action == 'verify':
        tenant.is_verified = True
        tenant.verification_date = timezone.now()
        tenant.verification_notes = notes
        tenant.save()
        messages.success(request, f'ISP {tenant.name} verified successfully!')
        
    elif action == 'unverify':
        tenant.is_verified = False
        tenant.verification_notes = notes
        tenant.save()
        messages.warning(request, f'ISP {tenant.name} unverified!')
        
    elif action == 'request_document':
        document_type = request.POST.get('document_type')
        document_names = {
            'business_registration': 'Business Registration Certificate',
            'tax_certificate': 'Tax Compliance Certificate',
            'id_document': 'Director ID Document'
        }
        document_name = document_names.get(document_type, document_type)
        messages.info(request, f'{document_name} request sent to {tenant.name}')
        
    return redirect('superadmin_tenant_verify', tenant_id=tenant.id)

def render_verification_page(request, tenant):
    """Render the verification page with all necessary data"""
    # Get verification history from AdminLog or create placeholder
    from accounts.models import AdminLog
    
    try:
        action_logs = AdminLog.objects.filter(
            tenant=tenant,
            action__in=['verify_tenant', 'unverify_tenant', 'update_verification_status']
        ).order_by('-timestamp')[:10]
        
        verification_history = []
        for log in action_logs:
            verification_history.append({
                'status': log.details.get('status', 'unknown') if log.details else 'unknown',
                'timestamp': log.timestamp,
                'notes': log.details.get('notes', '') if log.details else '',
                'admin': log.admin.username if log.admin else 'System'
            })
    except Exception:
        # Fallback if AdminLog doesn't exist
        verification_history = []
        action_logs = []
    
    context = {
        'tenant': tenant,
        'verification_history': verification_history,
        'action_logs': action_logs,
        'page_title': f'Verify ISP: {tenant.name}',
        'page_subtitle': 'Review and verify ISP documentation',
    }
    
    return render(request, 'admin/superadmin_tenant_verify.html', context)

# Helper functions for AJAX responses
def handle_verify_action(tenant, notes, admin_user):
    """Handle verify action"""
    tenant.is_verified = True
    tenant.verification_date = timezone.now()
    tenant.verification_notes = notes
    tenant.save()
    
    # Log the action
    log_admin_action(tenant, admin_user, 'verify_tenant', 
                    f"Verified ISP: {tenant.name}",
                    {'status': 'verified', 'notes': notes})
    
    return JsonResponse({
        'success': True,
        'message': f'ISP {tenant.name} verified successfully',
        'is_verified': True,
        'verification_date': tenant.verification_date.isoformat() if tenant.verification_date else None
    })

def handle_unverify_action(tenant, notes, admin_user):
    """Handle unverify action"""
    tenant.is_verified = False
    tenant.verification_notes = notes
    tenant.save()
    
    # Log the action
    log_admin_action(tenant, admin_user, 'unverify_tenant',
                    f"Unverified ISP: {tenant.name}",
                    {'status': 'pending', 'notes': notes})
    
    return JsonResponse({
        'success': True,
        'message': f'ISP {tenant.name} unverified',
        'is_verified': False
    })

def handle_update_status_action(tenant, status, notes, admin_user):
    """Handle status update action"""
    if status == 'verified':
        tenant.is_verified = True
        tenant.verification_date = timezone.now()
    elif status in ['pending', 'rejected']:
        tenant.is_verified = False
    
    tenant.verification_notes = notes
    tenant.save()
    
    # Log the action
    log_admin_action(tenant, admin_user, 'update_verification_status',
                    f"Updated verification status for {tenant.name} to {status}",
                    {'status': status, 'notes': notes})
    
    return JsonResponse({
        'success': True,
        'message': f'ISP {tenant.name} status updated to {status}',
        'status': status,
        'is_verified': status == 'verified',
        'verification_date': tenant.verification_date.isoformat() if tenant.verification_date else None
    })

def handle_request_document_action(tenant, document_type, admin_user):
    """Handle document request action"""
    document_names = {
        'business_registration': 'Business Registration Certificate',
        'tax_certificate': 'Tax Compliance Certificate',
        'id_document': 'Director ID Document'
    }
    
    if document_type not in document_names:
        return JsonResponse({
            'success': False,
            'message': 'Invalid document type'
        }, status=400)
    
    document_name = document_names[document_type]
    
    # Log the request
    log_admin_action(tenant, admin_user, 'request_document',
                    f"Requested {document_name} from {tenant.name}",
                    {'document_type': document_type, 'document_name': document_name})
    
    # TODO: Implement actual email sending
    # send_document_request_email(tenant, document_name)
    
    return JsonResponse({
        'success': True,
        'message': f'{document_name} request sent to {tenant.name}',
        'document_type': document_type
    })

def log_admin_action(tenant, admin_user, action, description, details):
    """Log admin action to AdminLog model"""
    try:
        from accounts.models import AdminLog
        AdminLog.objects.create(
            tenant=tenant,
            admin=admin_user,
            action=action,
            description=description,
            details=details
        )
    except Exception as e:
        print(f"Failed to log admin action: {e}")
        # Continue even if logging fails

@staff_member_required
def superadmin_tenant_analytics(request, tenant_id):
    """Detailed analytics for an ISP"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    tenant = get_object_or_404(Tenant, id=tenant_id)
    
    # Get date range (default: last 30 days)
    days = int(request.GET.get('days', 30))
    end_date = timezone.now()
    start_date = end_date - timedelta(days=days)
    
    # Revenue trends
    revenue_data = []
    for i in range(days, 0, -1):
        date = end_date - timedelta(days=i)
        daily_revenue = Payment.objects.filter(
            user__tenant=tenant,
            status='completed',
            created_at__date=date.date()
        ).aggregate(total=Sum('amount'))['total'] or 0
        
        revenue_data.append({
            'date': date.strftime('%Y-%m-%d'),
            'revenue': float(daily_revenue)
        })
    
    # Customer growth
    customer_growth = []
    total_customers = 0
    for i in range(days, 0, -7):  # Weekly intervals
        date = end_date - timedelta(days=i)
        new_customers = CustomUser.objects.filter(
            tenant=tenant,
            role='customer',
            date_joined__date__lte=date.date()
        ).count()
        total_customers = new_customers
        
        customer_growth.append({
            'date': date.strftime('%Y-%m-%d'),
            'customers': new_customers
        })
    
    # Top plans by revenue
    # Top plans by revenue
    top_plans = Payment.objects.filter(
        user__tenant=tenant,
        status='completed'
    ).values(
        'plan__name'
    ).annotate(
        total_revenue=Sum('amount'),
        subscription_count=Count('id'),
        avg_revenue=Avg('amount'),
        success_rate=Avg(
            Case(
                When(status='completed', then=Value(100)),
                default=Value(0),
                output_field=DecimalField(max_digits=5, decimal_places=2)
            )
        )
    ).order_by('-total_revenue')[:10]

    # Payment success rate
    payment_stats = Payment.objects.filter(user__tenant=tenant).aggregate(
        total=Count('id'),
        successful=Count('id', filter=Q(status='completed')),
        failed=Count('id', filter=Q(status='failed')),
        pending=Count('id', filter=Q(status='pending'))
    )
    
    # Active vs inactive customers
    customer_stats = {
        'active': CustomUser.objects.filter(
            tenant=tenant,
            role='customer',
            is_active_customer=True
        ).count(),
        'inactive': CustomUser.objects.filter(
            tenant=tenant,
            role='customer',
            is_active_customer=False
        ).count()
    }
    
    context = {
        'tenant': tenant,
        'days': days,
        'revenue_data': json.dumps(revenue_data),
        'customer_growth': json.dumps(customer_growth),
        'top_plans': top_plans,
        'payment_stats': payment_stats,
        'customer_stats': customer_stats,
        'total_customers': total_customers,
        'page_title': f'ISP Analytics: {tenant.name}',
        'page_subtitle': f'Detailed performance metrics (Last {days} days)',
    }
    
    return render(request, 'admin/superadmin_tenant_analytics.html', context)

@staff_member_required
def superadmin_tenant_customers(request, tenant_id):
    """View all customers for an ISP"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    tenant = get_object_or_404(Tenant, id=tenant_id)
    
    customers = CustomUser.objects.filter(
        tenant=tenant,
        role='customer'
    ).order_by('-date_joined')
    
    # Pagination
    paginator = Paginator(customers, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Statistics
    customer_stats = {
        'total': customers.count(),
        'active': customers.filter(is_active_customer=True).count(),
        'pending': customers.filter(registration_status='pending').count(),
        'approved': customers.filter(registration_status='approved').count(),
        'rejected': customers.filter(registration_status='rejected').count(),
    }
    
    context = {
        'tenant': tenant,
        'customers': page_obj,
        'customer_stats': customer_stats,
        'page_obj': page_obj,
        'page_title': f'ISP Customers: {tenant.name}',
        'page_subtitle': f'Manage {customer_stats["total"]} customers',
    }
    
    return render(request, 'admin/superadmin_tenant_customers.html', context)

@staff_member_required
def superadmin_export_tenants(request):
    """Export ISP data"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    format_type = request.GET.get('format', 'csv')
    tenants = Tenant.objects.all()
    
    if format_type == 'json':
        data = list(tenants.values(
            'id', 'name', 'company_name', 'subdomain', 'contact_email',
            'contact_phone', 'is_active', 'is_verified', 'subscription_plan',
            'subscription_end', 'created_at'
        ))
        
        for tenant_data in data:
            tenant = Tenant.objects.get(id=tenant_data['id'])
            tenant_data['customer_count'] = CustomUser.objects.filter(
                tenant=tenant, role='customer'
            ).count()
            tenant_data['total_revenue'] = float(Payment.objects.filter(
                user__tenant=tenant, status='completed'
            ).aggregate(total=Sum('amount'))['total'] or 0)
        
        response = JsonResponse(data, safe=False)
        response['Content-Disposition'] = 'attachment; filename="isps_export.json"'
        return response
    
    else:  # CSV format
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="isps_export.csv"'
        
        writer = csv.writer(response)
        writer.writerow([
            'ISP ID', 'Name', 'Company', 'Domain', 'Contact Email',
            'Contact Phone', 'Status', 'Verified', 'Plan', 'Customers',
            'Total Revenue', 'Created Date'
        ])
        
        for tenant in tenants:
            customer_count = CustomUser.objects.filter(
                tenant=tenant, role='customer'
            ).count()
            
            total_revenue = Payment.objects.filter(
                user__tenant=tenant, status='completed'
            ).aggregate(total=Sum('amount'))['total'] or 0
            
            writer.writerow([
                tenant.id,
                tenant.name,
                tenant.company_name,
                tenant.primary_domain,
                tenant.contact_email,
                tenant.contact_phone or '',
                'Active' if tenant.is_active else 'Inactive',
                'Yes' if tenant.is_verified else 'No',
                tenant.get_subscription_plan_display(),
                customer_count,
                total_revenue,
                tenant.created_at.strftime('%Y-%m-%d')
            ])
        
        return response

@staff_member_required
def superadmin_tenant_analytics(request, tenant_id):
    """Detailed analytics for a specific ISP"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    tenant = get_object_or_404(Tenant, id=tenant_id)
    days = int(request.GET.get('days', 30))
    
    # Date range calculations
    end_date = timezone.now()
    start_date = end_date - timedelta(days=days)
    
    # Revenue calculations
    total_revenue = Payment.objects.filter(
        user__tenant=tenant,
        status='completed'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
    
    period_revenue = Payment.objects.filter(
        user__tenant=tenant,
        status='completed',
        created_at__gte=start_date
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
    
    # Customer statistics
    active_customers = CustomUser.objects.filter(
        tenant=tenant,
        role='customer',
        is_active_customer=True
    ).count()
    
    new_customers = CustomUser.objects.filter(
        tenant=tenant,
        role='customer',
        date_joined__gte=start_date
    ).count()
    
    total_customers = CustomUser.objects.filter(
        tenant=tenant,
        role='customer'
    ).count()
    
    # Payment statistics
    payment_stats_query = Payment.objects.filter(user__tenant=tenant).aggregate(
        total=Count('id'),
        successful=Count('id', filter=Q(status='completed')),
        failed=Count('id', filter=Q(status='failed')),
        pending=Count('id', filter=Q(status='pending'))
    )
    
    success_rate = 0
    if payment_stats_query['total'] > 0:
        success_rate = round((payment_stats_query['successful'] / payment_stats_query['total']) * 100, 1)
    
    # Enhanced payment stats
    payment_stats = {
        'total': payment_stats_query['total'],
        'successful': payment_stats_query['successful'],
        'failed': payment_stats_query['failed'],
        'pending': payment_stats_query['pending'],
        'success_rate': success_rate
    }
    
    # Average revenue per customer
    avg_revenue_per_customer = Decimal('0')
    if total_customers > 0:
        avg_revenue_per_customer = total_revenue / Decimal(str(total_customers))
    
    # Revenue growth calculation
    previous_period_end = start_date - timedelta(days=1)
    previous_period_start = previous_period_end - timedelta(days=days)
    
    previous_revenue = Payment.objects.filter(
        user__tenant=tenant,
        status='completed',
        created_at__gte=previous_period_start,
        created_at__lte=previous_period_end
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
    
    revenue_growth = Decimal('0')
    if previous_revenue > 0:
        revenue_growth = round(((period_revenue - previous_revenue) / previous_revenue) * 100, 1)
    
    # Revenue trend data (daily)
    revenue_data = []
    for i in range(days, 0, -1):
        date = end_date - timedelta(days=i)
        daily_revenue = Payment.objects.filter(
            user__tenant=tenant,
            status='completed',
            created_at__date=date.date()
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
        
        revenue_data.append({
            'date': date.strftime('%Y-%m-%d'),
            'revenue': float(daily_revenue)
        })
    
    # Customer growth data
    customer_data = []
    cumulative_customers = 0
    for i in range(days, 0, -1):
        date = end_date - timedelta(days=i)
        # Get total customers up to this date
        customers_up_to_date = CustomUser.objects.filter(
            tenant=tenant,
            role='customer',
            date_joined__date__lte=date.date()
        ).count()
        
        customer_data.append({
            'date': date.strftime('%Y-%m-%d'),
            'customers': customers_up_to_date
        })
    
    # Top plans by revenue
    top_plans = Payment.objects.filter(
        user__tenant=tenant,
        status='completed'
    ).values(
        'plan__name'
    ).annotate(
        total_revenue=Sum('amount'),
        subscription_count=Count('id'),
        avg_revenue=Avg('amount'),
        success_rate=Avg(
            Case(
                When(status='completed', then=Value(100)),
                default=Value(0),
                output_field=DecimalField()
            )
        )
    ).order_by('-total_revenue')[:10]
    
    # Add trend data to plans
    for plan in top_plans:
        plan_start = end_date - timedelta(days=days)
        plan_end = end_date
        
        # Current period revenue
        current_revenue = Payment.objects.filter(
            user__tenant=tenant,
            plan__name=plan['plan__name'],
            status='completed',
            created_at__gte=plan_start
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
        
        # Previous period revenue
        previous_period_start = plan_start - timedelta(days=days)
        previous_period_end = plan_start
        
        previous_revenue = Payment.objects.filter(
            user__tenant=tenant,
            plan__name=plan['plan__name'],
            status='completed',
            created_at__gte=previous_period_start,
            created_at__lte=previous_period_end
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
        
        # Calculate trend
        if previous_revenue > 0:
            plan['trend'] = round(((current_revenue - previous_revenue) / previous_revenue) * 100, 1)
        else:
            plan['trend'] = 100.0 if current_revenue > 0 else 0.0
    
    # Monthly performance
    monthly_performance = []
    for i in range(5, -1, -1):
        month_start = end_date.replace(day=1) - timedelta(days=30*i)
        month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        
        month_revenue = Payment.objects.filter(
            user__tenant=tenant,
            status='completed',
            created_at__gte=month_start,
            created_at__lte=month_end
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
        
        month_customers = CustomUser.objects.filter(
            tenant=tenant,
            role='customer',
            date_joined__gte=month_start,
            date_joined__lte=month_end
        ).count()
        
        # Previous month for growth calculation
        prev_month_start = month_start - timedelta(days=30)
        prev_month_end = month_start - timedelta(days=1)
        
        prev_month_revenue = Payment.objects.filter(
            user__tenant=tenant,
            status='completed',
            created_at__gte=prev_month_start,
            created_at__lte=prev_month_end
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
        
        growth = Decimal('0')
        if prev_month_revenue > 0:
            growth = round(((month_revenue - prev_month_revenue) / prev_month_revenue) * 100, 1)
        
        # Calculate percentage for chart (relative to max revenue month)
        monthly_performance.append({
            'month': month_start.strftime('%b %Y'),
            'revenue': float(month_revenue),
            'customers': month_customers,
            'growth': growth,
            'percentage': 0  # Will be calculated below
        })
    
    # Calculate percentages for monthly performance chart
    if monthly_performance:
        max_revenue = max([m['revenue'] for m in monthly_performance])
        if max_revenue > 0:
            for month in monthly_performance:
                month['percentage'] = (month['revenue'] / max_revenue) * 100
    
    # Customer analytics
    customer_stats = {
        'total': total_customers,
        'active': active_customers,
        'inactive': total_customers - active_customers,
        'pending': CustomUser.objects.filter(
            tenant=tenant,
            role='customer',
            registration_status='pending'
        ).count(),
        'active_percentage': round((active_customers / total_customers * 100), 1) if total_customers > 0 else 0,
        'inactive_percentage': round(((total_customers - active_customers) / total_customers * 100), 1) if total_customers > 0 else 0,
        'pending_percentage': 0
    }
    
    if total_customers > 0:
        customer_stats['pending_percentage'] = round((customer_stats['pending'] / total_customers * 100), 1)
    
    # Registration trend
    today = timezone.now().date()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)
    year_ago = today - timedelta(days=365)
    
    registration_trend = {
        'today': CustomUser.objects.filter(
            tenant=tenant,
            role='customer',
            date_joined__date=today
        ).count(),
        'week': CustomUser.objects.filter(
            tenant=tenant,
            role='customer',
            date_joined__gte=week_ago
        ).count(),
        'month': CustomUser.objects.filter(
            tenant=tenant,
            role='customer',
            date_joined__gte=month_ago
        ).count(),
        'year': CustomUser.objects.filter(
            tenant=tenant,
            role='customer',
            date_joined__gte=year_ago
        ).count()
    }
    
    # Customer value metrics (simplified)
    # In a real system, you'd calculate these from actual data
    customer_value = {
        'avg_lifetime': 180,  # days
        'churn_rate': 15.5,   # percentage
        'retention_rate': 84.5,  # percentage
        'ltv': float(avg_revenue_per_customer * Decimal('12'))  # Annual LTV
    }
    
    context = {
        'tenant': tenant,
        'days': days,
        
        # Financial metrics
        'total_revenue': total_revenue,
        'period_revenue': period_revenue,
        'avg_revenue_per_customer': avg_revenue_per_customer,
        'revenue_growth': revenue_growth,
        
        # Customer metrics
        'total_customers': total_customers,
        'active_customers': active_customers,
        'new_customers': new_customers,
        'customer_stats': customer_stats,
        
        # Payment metrics
        'payment_stats': payment_stats,
        
        # Chart data
        'revenue_data': json.dumps(revenue_data),
        'customer_data': json.dumps(customer_data),
        
        # Performance data
        'top_plans': top_plans,
        'monthly_performance': monthly_performance,
        
        # Trend data
        'registration_trend': registration_trend,
        'customer_value': customer_value,
        
        'page_title': f'ISP Analytics: {tenant.name}',
        'page_subtitle': f'Performance insights (Last {days} days)',
    }
    
    return render(request, 'admin/superadmin_tenant_analytics.html', context)

@staff_member_required
def superadmin_tenant_payments(request, tenant_id):
    """View and manage payments for a specific ISP"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    tenant = get_object_or_404(Tenant, id=tenant_id)
    
    # Get payments with related data
    payments = Payment.objects.filter(
        user__tenant=tenant
    ).select_related('user', 'plan').order_by('-created_at')
    
    # Statistics
    total_revenue = payments.filter(status='completed').aggregate(
        total=Sum('amount')
    )['total'] or Decimal('0')
    
    payment_stats = payments.aggregate(
        total=Count('id'),
        successful=Count('id', filter=Q(status='completed')),
        failed=Count('id', filter=Q(status='failed')),
        pending=Count('id', filter=Q(status='pending'))
    )
    
    # Monthly revenue breakdown
    monthly_revenue = []
    for i in range(5, -1, -1):
        month_start = timezone.now().replace(day=1) - timedelta(days=30*i)
        month_name = month_start.strftime('%b %Y')
        
        month_data = payments.filter(
            status='completed',
            created_at__year=month_start.year,
            created_at__month=month_start.month
        ).aggregate(
            revenue=Sum('amount'),
            count=Count('id')
        )
        
        monthly_revenue.append({
            'month': month_name,
            'revenue': month_data['revenue'] or Decimal('0'),
            'count': month_data['count'] or 0
        })
    
    # Payment methods distribution (simplified)
    payment_methods = [
        {'method': 'paystack', 'count': payments.filter(status='completed').count(), 'amount': total_revenue},
        {'method': 'mpesa', 'count': 0, 'amount': Decimal('0')},  # Add actual data if available
        {'method': 'bank', 'count': 0, 'amount': Decimal('0')},   # Add actual data if available
    ]
    
    # Recent failed payments
    failed_payments = payments.filter(
        status='failed',
        created_at__gte=timezone.now() - timedelta(days=7)
    )[:5]
    
    failed_payments_count = payments.filter(status='failed').count()
    
    # Pagination
    paginator = Paginator(payments, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'tenant': tenant,
        'payments': page_obj,
        
        # Statistics
        'total_revenue': total_revenue,
        'payment_stats': payment_stats,
        'payment_count': payments.count(),
        
        # Additional data
        'monthly_revenue': monthly_revenue,
        'payment_methods': payment_methods,
        'failed_payments': failed_payments,
        'failed_payments_count': failed_payments_count,
        
        'page_title': f'ISP Payments: {tenant.name}',
        'page_subtitle': f'Payment management for {tenant.company_name}',
    }
    
    return render(request, 'admin/superadmin_tenant_payments.html', context)

@staff_member_required
def superadmin_tenant_edit(request, tenant_id):
    """Edit ISP details"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    tenant = get_object_or_404(Tenant, id=tenant_id)
    
    if request.method == 'POST':
        try:
            # Update basic information
            tenant.name = request.POST.get('name')
            tenant.company_name = request.POST.get('company_name')
            tenant.subdomain = request.POST.get('subdomain').lower()
            tenant.custom_domain = request.POST.get('custom_domain', '').strip()
            tenant.description = request.POST.get('description', '')
            
            # Contact information
            tenant.contact_email = request.POST.get('contact_email')
            tenant.contact_phone = request.POST.get('contact_phone', '')
            tenant.address = request.POST.get('address', '')
            
            # Branding
            if 'logo' in request.FILES:
                tenant.logo = request.FILES['logo']
            elif 'remove_logo' in request.POST:
                tenant.logo = None
            
            if 'favicon' in request.FILES:
                tenant.favicon = request.FILES['favicon']
            elif 'remove_favicon' in request.POST:
                tenant.favicon = None
            
            # Colors
            tenant.primary_color = request.POST.get('primary_color', '#4361ee')
            tenant.secondary_color = request.POST.get('secondary_color', '#3a0ca3')
            
            # Subscription
            tenant.subscription_plan = request.POST.get('subscription_plan')
            tenant.monthly_rate = Decimal(request.POST.get('monthly_rate', '0'))
            
            subscription_end = request.POST.get('subscription_end')
            if subscription_end:
                tenant.subscription_end = datetime.strptime(subscription_end, '%Y-%m-%d').date()
            
            tenant.auto_renew = 'auto_renew' in request.POST
            
            # ISP Settings
            tenant.bandwidth_limit = int(request.POST.get('bandwidth_limit', 1000))
            tenant.client_limit = int(request.POST.get('client_limit', 1000))
            tenant.auto_disconnect_enabled = 'auto_disconnect_enabled' in request.POST
            tenant.auto_disconnect_threshold = int(request.POST.get('auto_disconnect_threshold', 80))
            
            # Status
            tenant.is_active = request.POST.get('is_active') == 'true'
            tenant.is_verified = 'is_verified' in request.POST
            tenant.verification_notes = request.POST.get('verification_notes', '')
            
            tenant.save()
            
            messages.success(request, f'ISP {tenant.name} updated successfully!')
            return redirect('superadmin_tenant_detail', tenant_id=tenant.id)
            
        except Exception as e:
            messages.error(request, f'Error updating ISP: {str(e)}')
    
    # Get statistics for context
    customer_count = CustomUser.objects.filter(tenant=tenant, role='customer').count()
    staff_count = CustomUser.objects.filter(tenant=tenant, role__in=['isp_admin', 'isp_staff']).count()
    
    total_revenue = Payment.objects.filter(
        user__tenant=tenant,
        status='completed'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
    
    last_payment = Payment.objects.filter(
        user__tenant=tenant,
        status='completed'
    ).order_by('-created_at').first()
    
    last_payment_date = last_payment.created_at if last_payment else None
    
    context = {
        'tenant': tenant,
        'customer_count': customer_count,
        'staff_count': staff_count,
        'total_revenue': total_revenue,
        'last_payment_date': last_payment_date,
        'page_title': f'Edit ISP: {tenant.name}',
        'page_subtitle': 'Update ISP configuration',
    }
    
    return render(request, 'admin/superadmin_tenant_edit.html', context)

@staff_member_required
def superadmin_tenant_delete(request, tenant_id):
    """Delete ISP confirmation and execution"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    tenant = get_object_or_404(Tenant, id=tenant_id)
    
    if request.method == 'POST':
        try:
            # Get data before deletion for logging
            tenant_name = tenant.name
            customer_count = CustomUser.objects.filter(tenant=tenant, role='customer').count()
            staff_count = CustomUser.objects.filter(tenant=tenant, role__in=['isp_admin', 'isp_staff']).count()
            payment_count = Payment.objects.filter(user__tenant=tenant).count()
            total_revenue = Payment.objects.filter(user__tenant=tenant, status='completed').aggregate(
                total=Sum('amount')
            )['total'] or Decimal('0')
            
            # Get deletion reason
            deletion_reason = request.POST.get('deletion_reason', 'unknown')
            deletion_notes = request.POST.get('deletion_notes', '')
            
            # Log deletion (you might want to create a DeletionLog model)
            # For now, we'll just print to console
            print(f"ISP Deleted: {tenant_name}")
            print(f"Reason: {deletion_reason}")
            print(f"Notes: {deletion_notes}")
            print(f"Impact: {customer_count} customers, {staff_count} staff, {payment_count} payments")
            print(f"Total Revenue: {total_revenue}")
            
            # Actually delete the tenant
            tenant.delete()
            
            messages.success(request, f'ISP {tenant_name} has been permanently deleted.')
            return redirect('superadmin_tenants')
            
        except Exception as e:
            messages.error(request, f'Error deleting ISP: {str(e)}')
            return redirect('superadmin_tenant_delete', tenant_id=tenant_id)
    
    # GET request - show confirmation page
    customer_count = CustomUser.objects.filter(tenant=tenant, role='customer').count()
    staff_count = CustomUser.objects.filter(tenant=tenant, role__in=['isp_admin', 'isp_staff']).count()
    payment_count = Payment.objects.filter(user__tenant=tenant).count()
    total_revenue = Payment.objects.filter(user__tenant=tenant, status='completed').aggregate(
        total=Sum('amount')
    )['total'] or Decimal('0')
    
    # Get deletion history (simplified - you might want to implement a proper model)
    deletion_history = []
    
    context = {
        'tenant': tenant,
        'customer_count': customer_count,
        'staff_count': staff_count,
        'payment_count': payment_count,
        'total_revenue': total_revenue,
        'deletion_history': deletion_history,
        'page_title': f'Delete ISP: {tenant.name}',
        'page_subtitle': '⚠️ This action cannot be undone',
    }
    
    return render(request, 'admin/superadmin_tenant_delete.html', context)

from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.contrib.auth.hashers import make_password
import json
from datetime import datetime, timedelta
from django.http import JsonResponse

@staff_member_required
def superadmin_tenant_admins(request, tenant_id):
    """View and manage ISP administrators"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    tenant = get_object_or_404(Tenant, id=tenant_id)
    
    # Get all admins for this tenant
    admins = CustomUser.objects.filter(
        tenant=tenant,
        role__in=['isp_admin', 'isp_staff', 'support']
    ).order_by('-date_joined')
    
    # Statistics
    admin_count = admins.count()
    active_admin_count = admins.filter(is_active=True).count()
    
    # Get recent admins (last 30 days)
    recent_admins = admins.filter(
        date_joined__gte=timezone.now() - timedelta(days=30)
    ).count()
    
    # Get pending invites (you might need an Invite model)
    pending_invites_count = 0  # Placeholder
    pending_invites = []  # Placeholder
    
    # Get recent activity (you might need an ActivityLog model)
    recent_activity = []  # Placeholder
    
    # Pagination
    paginator = Paginator(admins, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'tenant': tenant,
        'admins': page_obj,
        
        # Statistics
        'admin_count': admin_count,
        'active_admin_count': active_admin_count,
        'pending_invites_count': pending_invites_count,
        'recent_admins_count': recent_admins,
        
        # Additional data
        'pending_invites': pending_invites,
        'recent_activity': recent_activity,
        
        'page_title': f'ISP Admins: {tenant.name}',
        'page_subtitle': f'Manage administrators for {tenant.company_name}',
    }
    
    return render(request, 'admin/superadmin_tenant_admins.html', context)

@staff_member_required
def superadmin_create_tenant_admin(request, tenant_id):
    """Create a new ISP admin for a tenant"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    tenant = get_object_or_404(Tenant, id=tenant_id)
    
    if request.method == 'POST':
        try:
            # Extract form data
            first_name = request.POST.get('first_name', '').strip()
            last_name = request.POST.get('last_name', '').strip()
            username = request.POST.get('username', '').strip()
            email = request.POST.get('email', '').strip()
            password = request.POST.get('password', '').strip()
            role = request.POST.get('role', 'isp_admin')
            phone = request.POST.get('phone', '').strip()
            company_account_number = request.POST.get('company_account_number', '').strip()
            is_staff = request.POST.get('is_staff') == 'on'
            send_welcome_email = request.POST.get('send_welcome_email') == 'on'
            auto_approve = request.POST.get('auto_approve') == 'on'
            force_password_change = request.POST.get('force_password_change') == 'on'
            notes = request.POST.get('notes', '').strip()
            
            # Validate required fields
            if not all([first_name, last_name, username, email, password]):
                return JsonResponse({
                    'success': False,
                    'message': 'All required fields must be filled'
                })
            
            # Check if username already exists
            if CustomUser.objects.filter(username=username).exists():
                return JsonResponse({
                    'success': False,
                    'message': f"Username '{username}' is already taken"
                })
            
            # Check if email already exists
            if CustomUser.objects.filter(email=email).exists():
                return JsonResponse({
                    'success': False,
                    'message': f"Email '{email}' is already registered"
                })
            
            # Check company account number uniqueness if provided
            if company_account_number and CustomUser.objects.filter(company_account_number=company_account_number).exists():
                return JsonResponse({
                    'success': False,
                    'message': f"Company account number '{company_account_number}' is already in use"
                })
            
            # Create the user
            user = CustomUser.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
                phone=phone or None,
                company_account_number=company_account_number or None
            )
            
            # Set tenant and role
            user.tenant = tenant
            user.role = role
            user.is_staff = is_staff
            
            # Set registration status
            if auto_approve:
                user.registration_status = 'approved'
                user.is_active_customer = True
                user.approval_date = timezone.now()
                # approved_by should be a CustomUser instance, not a string
                user.approved_by = request.user
            else:
                user.registration_status = 'pending'
                user.is_active_customer = False
            
            # Force password change flag
            if force_password_change:
                # You might want to set a flag or store in a separate model
                user.force_password_change = True
            
            # Save additional permissions from custom checkboxes
            permissions = {
                'can_manage_customers': request.POST.get('can_manage_customers') == 'on',
                'can_manage_payments': request.POST.get('can_manage_payments') == 'on',
                'can_manage_routers': request.POST.get('can_manage_routers') == 'on',
                'can_view_reports': request.POST.get('can_view_reports') == 'on',
                'can_manage_staff': request.POST.get('can_manage_staff') == 'on',
                'can_configure_settings': request.POST.get('can_configure_settings') == 'on',
            }
            
            # Store permissions in user's metadata or a separate model
            user.metadata = json.dumps(permissions)
            
            # Save the user
            user.save()
            
            # Create admin log entry
            AdminLog.objects.create(
                tenant=tenant,
                admin=request.user,
                action='create_admin',
                description=f"Created new {role.replace('_', ' ').title()} for {tenant.name}: {user.get_full_name()}",
                details=json.dumps({
                    'admin_id': str(user.id),
                    'admin_email': user.email,
                    'role': role,
                    'permissions': permissions,
                    'notes': notes
                })
            )
            
            # Send welcome email if requested
            if send_welcome_email and email:
                try:
                    # You would implement your email sending logic here
                    send_welcome_email_to_admin(user, password, tenant)
                except Exception as e:
                    print(f"Failed to send welcome email: {e}")
                    # Don't fail the whole operation if email fails
            
            # Return success response
            return JsonResponse({
                'success': True,
                'message': f'Admin created successfully!',
                'admin_id': str(user.id),
                'admin_name': user.get_full_name(),
                'admin_email': user.email,
                'redirect_url': reverse('superadmin_tenant_admins', args=[tenant.id])
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Error creating admin: {str(e)}'
            })
    
    # GET request - show form
    current_admin_count = CustomUser.objects.filter(
        tenant=tenant,
        role__in=['isp_admin', 'isp_staff', 'support']
    ).count()
    
    context = {
        'tenant': tenant,
        'current_admin_count': current_admin_count,
        'page_title': f'Create ISP Admin for {tenant.name}',
        'page_subtitle': f'Set up a new administrator for {tenant.company_name}',
    }
    
    return render(request, 'admin/superadmin_create_tenant_admin.html', context)


@staff_member_required
def superadmin_create_user(request):
    """Create a user from the SuperAdmin users page (AJAX POST)."""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")

    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=400)

    # Support both form-encoded and JSON payloads
    data = {}
    try:
        if request.content_type == 'application/json' and request.body:
            data = json.loads(request.body)
        else:
            data = request.POST
    except Exception:
        data = request.POST

    first_name = data.get('first_name', '').strip()
    last_name = data.get('last_name', '').strip()
    username = data.get('username', '').strip()
    email = data.get('email', '').strip()
    password = data.get('password', '').strip()
    role = data.get('role', 'customer')
    tenant_id = data.get('tenant') or None
    auto_approve = data.get('auto_approve') in [True, 'true', 'True', 'on', '1']
    force_password_change = data.get('force_password_change') in [True, 'true', 'True', 'on', '1']
    send_welcome_email = data.get('send_welcome_email') in [True, 'true', 'True', 'on', '1']
    company_account_number = data.get('company_account_number') or None
    phone = data.get('phone') or None

    if not all([first_name, last_name, username, email, password]):
        return JsonResponse({'success': False, 'message': 'All required fields must be filled'}, status=400)

    if CustomUser.objects.filter(username=username).exists():
        return JsonResponse({'success': False, 'message': f"Username '{username}' is already taken"}, status=400)

    if CustomUser.objects.filter(email=email).exists():
        return JsonResponse({'success': False, 'message': f"Email '{email}' is already registered"}, status=400)

    try:
        tenant = None
        if tenant_id:
            try:
                tenant = Tenant.objects.get(id=tenant_id)
            except Exception:
                tenant = None

        user = CustomUser.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            company_account_number=company_account_number
        )

        user.role = role
        user.tenant = tenant
        user.is_staff = role in ['isp_admin', 'isp_staff', 'superadmin']

        if auto_approve:
            user.registration_status = 'approved'
            user.is_active_customer = True
            user.approval_date = timezone.now()
            user.approved_by = request.user
        else:
            user.registration_status = 'pending'
            user.is_active_customer = False

        if force_password_change:
            try:
                user.force_password_change = True
            except Exception:
                pass

        user.save()

        # Log admin creation
        try:
            AdminLog.objects.create(
                tenant=tenant or (user.tenant if user.tenant else None),
                admin=request.user,
                action='create_admin',
                description=f"Created user {user.get_full_name()} ({user.username})",
                details={'user_id': str(user.id), 'role': role}
            )
        except Exception:
            pass

        # Optionally send welcome email (omitted here)

        return JsonResponse({'success': True, 'message': 'User created successfully', 'user_id': str(user.id)})
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Error creating user: {str(e)}'}, status=400)

@staff_member_required
def toggle_admin_status(request, tenant_id, admin_id):
    """Toggle admin active status"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    if request.method == 'POST':
        try:
            admin = get_object_or_404(CustomUser, id=admin_id, tenant_id=tenant_id)
            
            # Don't allow deactivating yourself
            if admin.id == request.user.id:
                return JsonResponse({
                    'success': False,
                    'message': 'You cannot deactivate your own account'
                })
            
            # Toggle status
            admin.is_active = not admin.is_active
            admin.save()
            
            # Log the action
            AdminLog.objects.create(
                tenant=admin.tenant,
                admin=request.user,
                action='toggle_admin_status',
                description=f"{'Activated' if admin.is_active else 'Deactivated'} admin: {admin.get_full_name()}",
                details=json.dumps({
                    'admin_id': str(admin.id),
                    'admin_email': admin.email,
                    'new_status': admin.is_active,
                    'changed_by': request.user.username
                })
            )
            
            return JsonResponse({
                'success': True,
                'message': f'Admin {"activated" if admin.is_active else "deactivated"} successfully',
                'is_active': admin.is_active
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Error: {str(e)}'
            })
    
    return JsonResponse({'success': False, 'message': 'Invalid request method'})

@staff_member_required
def remove_admin_from_tenant(request, tenant_id, admin_id):
    """Remove admin from tenant (but keep user account)"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    if request.method == 'POST':
        try:
            admin = get_object_or_404(CustomUser, id=admin_id, tenant_id=tenant_id)
            
            # Don't allow removing yourself
            if admin.id == request.user.id:
                return JsonResponse({
                    'success': False,
                    'message': 'You cannot remove yourself'
                })
            
            # Store admin details for logging
            admin_details = {
                'name': admin.get_full_name(),
                'email': admin.email,
                'role': admin.role,
                'tenant': admin.tenant.name
            }
            
            # Remove from tenant (set tenant to None)
            admin.tenant = None
            admin.role = 'customer'  # Default role
            admin.is_staff = False
            admin.save()
            
            # Log the action
            AdminLog.objects.create(
                tenant=get_object_or_404(Tenant, id=tenant_id),
                admin=request.user,
                action='remove_admin',
                description=f"Removed admin from tenant: {admin_details['name']}",
                details=json.dumps(admin_details)
            )
            
            return JsonResponse({
                'success': True,
                'message': f'Admin removed from tenant successfully'
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Error: {str(e)}'
            })
    
    return JsonResponse({'success': False, 'message': 'Invalid request method'})

@staff_member_required
def send_admin_password_reset(request, tenant_id, admin_id):
    """Send password reset email to admin"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    if request.method == 'POST':
        try:
            admin = get_object_or_404(CustomUser, id=admin_id, tenant_id=tenant_id)
            
            # Generate password reset token (using Django's built-in)
            from django.contrib.auth.tokens import default_token_generator
            from django.utils.encoding import force_bytes
            from django.utils.http import urlsafe_base64_encode
            
            token = default_token_generator.make_token(admin)
            uid = urlsafe_base64_encode(force_bytes(admin.pk))
            
            # Build reset URL
            reset_url = request.build_absolute_uri(
                reverse('password_reset_confirm', kwargs={'uidb64': uid, 'token': token})
            )
            
            # Send email (you would implement your email sending logic)
            try:
                send_password_reset_email(admin.email, reset_url, admin.get_full_name())
            except Exception as e:
                print(f"Failed to send password reset email: {e}")
                return JsonResponse({
                    'success': False,
                    'message': f'Error sending email: {str(e)}'
                })
            
            # Log the action
            AdminLog.objects.create(
                tenant=admin.tenant,
                admin=request.user,
                action='send_password_reset',
                description=f"Sent password reset to admin: {admin.get_full_name()}",
                details=json.dumps({
                    'admin_email': admin.email,
                    'reset_url': reset_url
                })
            )
            
            return JsonResponse({
                'success': True,
                'message': 'Password reset email sent successfully'
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Error: {str(e)}'
            })
    
    return JsonResponse({'success': False, 'message': 'Invalid request method'})

@staff_member_required
def check_username_availability(request):
    """Check if username is available"""
    username = request.GET.get('username', '').strip()
    
    if not username:
        return JsonResponse({'available': False, 'message': 'Username is required'})
    
    if len(username) < 3:
        return JsonResponse({'available': False, 'message': 'Username must be at least 3 characters'})
    
    # Check if username exists
    exists = CustomUser.objects.filter(username=username).exists()
    
    return JsonResponse({
        'available': not exists,
        'message': 'Username is available' if not exists else 'Username is already taken'
    })

@staff_member_required
def export_tenant_admins(request, tenant_id):
    """Export tenant admins to CSV"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    tenant = get_object_or_404(Tenant, id=tenant_id)
    admins = CustomUser.objects.filter(
        tenant=tenant,
        role__in=['isp_admin', 'isp_staff', 'support']
    ).order_by('last_name', 'first_name')
    
    # Create CSV response
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{tenant.subdomain}_admins_{datetime.now().strftime("%Y%m%d")}.csv"'
    
    writer = csv.writer(response)
    writer.writerow([
        'First Name', 'Last Name', 'Username', 'Email', 'Phone',
        'Role', 'Status', 'Staff Access', 'Last Login', 'Date Joined'
    ])
    
    for admin in admins:
        writer.writerow([
            admin.first_name,
            admin.last_name,
            admin.username,
            admin.email,
            admin.phone or '',
            admin.get_role_display(),
            'Active' if admin.is_active else 'Inactive',
            'Yes' if admin.is_staff else 'No',
            admin.last_login.strftime('%Y-%m-%d %H:%M') if admin.last_login else 'Never',
            admin.date_joined.strftime('%Y-%m-%d')
        ])
    
    return response

# Helper function to send welcome email (implement based on your email setup)
def send_welcome_email_to_admin(admin, password, tenant):
    """Send welcome email to new admin"""
    # This is a placeholder - implement based on your email configuration
    subject = f"Welcome to {tenant.name} Admin Portal"
    message = f"""
    Dear {admin.get_full_name()},
    
    You have been added as an administrator for {tenant.name} on the m_neti platform.
    
    Your login details:
    - Portal URL: {tenant.primary_domain}/isp/dashboard/
    - Username: {admin.username}
    - Password: {password}
    
    Please change your password after first login.
    
    Best regards,
    m_neti Team
    """
    
    # Send email using your email backend
    # admin.email_user(subject, message)  # If using Django's built-in email
    pass

def send_password_reset_email(email, reset_url, name):
    """Send password reset email"""
    # This is a placeholder - implement based on your email configuration
    subject = "Password Reset Request"
    message = f"""
    Dear {name},
    
    A password reset has been requested for your admin account.
    
    Click the link below to reset your password:
    {reset_url}
    
    If you didn't request this, please ignore this email.
    
    Best regards,
    m_neti Team
    """
    
    # Send email using your email backend
    pass

@staff_member_required
@require_http_methods(["POST"])
def superadmin_tenant_verify_api(request, tenant_id):
    """API endpoint for verifying/unverifying tenants"""
    if not request.user.is_superuser:
        return JsonResponse({'success': False, 'message': 'Access denied'}, status=403)
    
    try:
        tenant = get_object_or_404(Tenant, id=tenant_id)
        data = json.loads(request.body)
        
        action = data.get('action', 'verify')
        status = data.get('status', 'verified')
        notes = data.get('notes', '')
        
        if action == 'verify':
            tenant.is_verified = True
            tenant.verification_date = timezone.now()
            tenant.verification_notes = notes
            tenant.save()
            
            # Log the action
            AdminLog.objects.create(
                tenant=tenant,
                admin=request.user,
                action='verify_tenant',
                description=f"Verified ISP: {tenant.name}",
                details=json.dumps({'status': 'verified', 'notes': notes})
            )
            
            return JsonResponse({
                'success': True,
                'message': f'ISP {tenant.name} verified successfully',
                'is_verified': True,
                'verification_date': tenant.verification_date.isoformat() if tenant.verification_date else None
            })
            
        elif action == 'unverify':
            tenant.is_verified = False
            tenant.verification_notes = notes
            tenant.save()
            
            # Log the action
            AdminLog.objects.create(
                tenant=tenant,
                admin=request.user,
                action='unverify_tenant',
                description=f"Unverified ISP: {tenant.name}",
                details=json.dumps({'status': 'pending', 'notes': notes})
            )
            
            return JsonResponse({
                'success': True,
                'message': f'ISP {tenant.name} unverified',
                'is_verified': False
            })
            
        elif action == 'update_status':
            # Map status to boolean verification
            if status == 'verified':
                tenant.is_verified = True
                tenant.verification_date = timezone.now()
            elif status in ['pending', 'rejected']:
                tenant.is_verified = False
            
            tenant.verification_notes = notes
            tenant.save()
            
            # Log the action
            AdminLog.objects.create(
                tenant=tenant,
                admin=request.user,
                action=f'update_verification_status_{status}',
                description=f"Updated verification status for {tenant.name} to {status}",
                details=json.dumps({'status': status, 'notes': notes})
            )
            
            return JsonResponse({
                'success': True,
                'message': f'ISP {tenant.name} status updated to {status}',
                'status': status,
                'is_verified': status == 'verified',
                'verification_date': tenant.verification_date.isoformat() if tenant.verification_date else None
            })
            
        else:
            return JsonResponse({
                'success': False,
                'message': 'Invalid action'
            }, status=400)
            
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error: {str(e)}'
        }, status=500)


@staff_member_required
@require_http_methods(["POST"])
def superadmin_request_document(request, tenant_id):
    """Request additional documents from ISP"""
    if not request.user.is_superuser:
        return JsonResponse({'success': False, 'message': 'Access denied'}, status=403)
    
    try:
        tenant = get_object_or_404(Tenant, id=tenant_id)
        data = json.loads(request.body)
        
        document_type = data.get('document_type')
        document_names = {
            'business_registration': 'Business Registration Certificate',
            'tax_certificate': 'Tax Compliance Certificate',
            'id_document': 'Director ID Document'
        }
        
        if document_type not in document_names:
            return JsonResponse({
                'success': False,
                'message': 'Invalid document type'
            }, status=400)
        
        document_name = document_names[document_type]
        
        # Log the request
        AdminLog.objects.create(
            tenant=tenant,
            admin=request.user,
            action='request_document',
            description=f"Requested {document_name} from {tenant.name}",
            details=json.dumps({'document_type': document_type, 'document_name': document_name})
        )
        
        # TODO: Implement actual email sending
        # send_document_request_email(tenant, document_name)
        
        return JsonResponse({
            'success': True,
            'message': f'{document_name} request sent to {tenant.name}',
            'document_type': document_type
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error: {str(e)}'
        }, status=500)

@staff_member_required
def superadmin_verification_log_export(request, tenant_id):
    """Export verification logs for a tenant"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    tenant = get_object_or_404(Tenant, id=tenant_id)
    
    # Get verification logs
    logs = AdminLog.objects.filter(
        tenant=tenant,
        action__in=['verify_tenant', 'unverify_tenant', 'update_verification_status']
    ).order_by('-timestamp')
    
    # Create CSV response
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{tenant.subdomain}_verification_log_{timezone.now().strftime("%Y%m%d")}.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['Timestamp', 'Action', 'Admin', 'Description', 'Details'])
    
    for log in logs:
        writer.writerow([
            log.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            log.get_action_display(),
            log.admin.username if log.admin else 'System',
            log.description,
            json.dumps(log.details) if log.details else ''
        ])
    
    return response

@login_required
@staff_member_required
def superadmin_configure_paystack_admin(request, tenant_id):
    """Superadmin version of PayStack configuration for a tenant"""
    try:
        tenant = Tenant.objects.get(id=tenant_id)
        
        # Check if tenant is verified
        if not tenant.is_verified:
            messages.error(request, 'ISP must be verified before setting up PayStack')
            return redirect('superadmin_tenant_verify', tenant_id=tenant_id)
        
        # Get or create PayStack configuration
        config, created = PaystackConfiguration.objects.get_or_create(tenant=tenant)
        
        # Fetch banks from PayStack API
        kenyan_banks = []
        try:
            # Use the tenant's PayStack keys if available, otherwise use default
            secret_key = config.secret_key if config.secret_key else settings.PAYSTACK_SECRET_KEY
            
            # Fetch banks for Kenya from PayStack API
            response = requests.get(
                'https://api.paystack.co/bank',
                params={
                    'country': 'kenya',
                    'perPage': 100,
                    'currency': 'KES'
                },
                headers={
                    'Authorization': f'Bearer {secret_key}',
                    'Content-Type': 'application/json'
                },
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('status'):
                    kenyan_banks = data['data']
                    # Sort banks by name for better UX
                    kenyan_banks = sorted(kenyan_banks, key=lambda x: x.get('name', ''))
                    messages.info(request, f"Loaded {len(kenyan_banks)} banks from PayStack API")
                else:
                    messages.warning(request, 'Could not fetch banks from PayStack API. Using default list.')
                    kenyan_banks = get_default_banks_list()
            else:
                messages.warning(request, f'PayStack API returned status {response.status_code}. Using default list.')
                kenyan_banks = get_default_banks_list()
                
        except requests.exceptions.Timeout:
            messages.warning(request, 'PayStack API timeout. Using default bank list.')
            kenyan_banks = get_default_banks_list()
        except requests.exceptions.RequestException as e:
            messages.warning(request, f'Network error fetching banks: {str(e)}. Using default list.')
            kenyan_banks = get_default_banks_list()
        except Exception as e:
            messages.warning(request, f'Error fetching banks: {str(e)}. Using default list.')
            kenyan_banks = get_default_banks_list()
        
        # Handle form submission
        if request.method == 'POST':
            bank_code = request.POST.get('bank_code')
            account_number = request.POST.get('account_number')
            account_name = request.POST.get('account_name')
            
            try:
                # Validate inputs
                if not all([bank_code, account_number, account_name]):
                    messages.error(request, 'Please fill all fields')
                elif len(account_number) < 8 or len(account_number) > 20:
                    messages.error(request, 'Account number must be 8-20 digits')
                elif not account_number.isdigit():
                    messages.error(request, 'Account number must contain only numbers')
                else:
                    # Validate bank account with PayStack API
                    try:
                        # First, verify the account number
                        secret_key = config.secret_key if config.secret_key else settings.PAYSTACK_SECRET_KEY
                        
                        response = requests.get(
                            'https://api.paystack.co/bank/resolve',
                            params={
                                'account_number': account_number,
                                'bank_code': bank_code
                            },
                            headers={
                                'Authorization': f'Bearer {secret_key}',
                                'Content-Type': 'application/json'
                            },
                            timeout=15
                        )
                        
                        if response.status_code == 200:
                            data = response.json()
                            if data.get('status'):
                                # Account verified successfully
                                verified_account_name = data['data']['account_name']
                                
                                # Create or update PayStack subaccount
                                subaccount_response = requests.post(
                                    'https://api.paystack.co/subaccount',
                                    headers={
                                        'Authorization': f'Bearer {secret_key}',
                                        'Content-Type': 'application/json'
                                    },
                                    json={
                                        'business_name': tenant.company_name or tenant.name,
                                        'bank_code': bank_code,
                                        'account_number': account_number,
                                        'percentage_charge': 7.5,  # Platform commission
                                        'description': f'ISP: {tenant.name}',
                                        'primary_contact_email': tenant.contact_email,
                                        'primary_contact_name': tenant.contact_email,  # You might want to use actual contact person
                                        'settlement_bank': bank_code,
                                        'account_name': verified_account_name
                                    },
                                    timeout=30
                                )
                                
                                if subaccount_response.status_code == 200 or subaccount_response.status_code == 201:
                                    subaccount_data = subaccount_response.json()
                                    if subaccount_data.get('status'):
                                        # Successfully created subaccount
                                        subaccount_code = subaccount_data['data']['subaccount_code']
                                        
                                        # Update configuration
                                        config.bank_code = bank_code
                                        config.account_number = account_number
                                        config.account_name = verified_account_name
                                        config.subaccount_code = subaccount_code
                                        config.is_active = True
                                        config.configured_by = request.user
                                        config.save()
                                        
                                        messages.success(request, f'PayStack configuration saved successfully! Subaccount created: {subaccount_code}')
                                        
                                        # Log the action
                                        try:
                                            AdminLog.objects.create(
                                                tenant=tenant,
                                                admin=request.user,
                                                action='paystack_configured',
                                                description=f"PayStack configured for {tenant.name}",
                                                details={
                                                    'account_name': verified_account_name,
                                                    'account_number': account_number,
                                                    'bank_code': bank_code,
                                                    'subaccount_code': subaccount_code
                                                }
                                            )
                                        except:
                                            pass  # Logging failure shouldn't stop the process
                                        
                                        return redirect('superadmin_tenant_detail', tenant_id=tenant_id)
                                    else:
                                        messages.error(request, f'PayStack error: {subaccount_data.get("message", "Failed to create subaccount")}')
                                else:
                                    messages.error(request, f'Failed to create PayStack subaccount. Status: {subaccount_response.status_code}')
                            else:
                                messages.error(request, f'Account verification failed: {data.get("message", "Invalid account details")}')
                        else:
                            messages.error(request, f'Account verification failed. Status: {response.status_code}')
                            
                    except requests.exceptions.RequestException as e:
                        messages.error(request, f'Network error during PayStack integration: {str(e)}')
                    except Exception as e:
                        messages.error(request, f'Error during PayStack integration: {str(e)}')
                        
            except Exception as e:
                messages.error(request, f'Error configuring PayStack: {str(e)}')
        
        context = {
            'tenant': tenant,
            'config': config if config.is_active else None,
            'banks': kenyan_banks,
            'subaccount_info': {
                'account_name': config.account_name if config.account_name else None,
                'account_number': config.account_number if config.account_number else None,
                'bank_code': config.bank_code if config.bank_code else None,
                'subaccount_code': config.subaccount_code if config.subaccount_code else None,
            } if config.is_active else None
        }
        
        return render(request, 'admin/superadmin_configure_paystack.html', context)
        
    except Tenant.DoesNotExist:
        messages.error(request, 'ISP not found')
        return redirect('superadmin_tenants')
    except Exception as e:
        messages.error(request, f'Error: {str(e)}')
        return redirect('superadmin_tenants')

def get_default_banks_list():
    """Fallback default bank list if API fails"""
    return [
        {"code": "011", "name": "Kenya Commercial Bank (KCB)"},
        {"code": "031", "name": "Co-operative Bank of Kenya"},
        {"code": "032", "name": "CITIBANK"},
        {"code": "033", "name": "Standard Chartered Bank Kenya"},
        {"code": "070", "name": "NCBA Bank"},
        {"code": "001", "name": "Central Bank of Kenya"},
        {"code": "010", "name": "Bank of Africa"},
        {"code": "012", "name": "Bank of Baroda"},
        {"code": "016", "name": "Bank of India"},
        {"code": "030", "name": "Diamond Trust Bank (DTB)"},
        {"code": "035", "name": "Ecobank Kenya"},
        {"code": "039", "name": "Equity Bank"},
        {"code": "040", "name": "Family Bank"},
        {"code": "047", "name": "Guardian Bank"},
        {"code": "050", "name": "Gulf African Bank"},
        {"code": "054", "name": "Habib Bank AG Zurich"},
        {"code": "057", "name": "I&M Bank"},
        {"code": "060", "name": "Kingdom Bank"},
        {"code": "061", "name": "Mayfair Bank"},
        {"code": "063", "name": "M-Oriental Bank"},
        {"code": "066", "name": "National Bank of Kenya"},
        {"code": "067", "name": "Paramount Universal Bank"},
        {"code": "068", "name": "Prime Bank"},
        {"code": "072", "name": "SBM Bank Kenya"},
        {"code": "074", "name": "Shield Investment Bank"},
        {"code": "076", "name": "Spire Bank"},
        {"code": "079", "name": "Transnational Bank"},
        {"code": "080", "name": "UBA Kenya Bank"},
        {"code": "086", "name": "Victoria Commercial Bank"},
    ]

@login_required
@staff_member_required
def reset_paystack_config(request, tenant_id):
    """Reset PayStack configuration for a tenant"""
    if request.method == 'POST' and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        try:
            tenant = Tenant.objects.get(id=tenant_id)
            config = PaystackConfiguration.objects.filter(tenant=tenant).first()
            
            if config:
                config.is_active = False
                config.save()
                
                # Log the action
                VerificationLog.objects.create(
                    tenant=tenant,
                    action='paystack_reset_by_superadmin',
                    performed_by=request.user,
                    notes=f"PayStack configuration reset by superadmin {request.user.get_full_name()}"
                )
                
                return JsonResponse({'success': True, 'message': 'Configuration reset successfully'})
            else:
                return JsonResponse({'success': False, 'message': 'No configuration found'})
                
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})
    
    return JsonResponse({'success': False, 'message': 'Invalid request'}, status=400)

    # Add these imports at the top if not already present
from billing.models import BulkDataPackage, DataVendor, PlatformCommission, ISPBulkPurchase, CommissionTransaction
from decimal import Decimal
from django.db.models import Sum, Count, Q
import json
from django.http import HttpResponse
import csv

@staff_member_required
def superadmin_bulk_data_management(request):
    """Superadmin: Manage bulk data packages and vendors"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    packages = BulkDataPackage.objects.all().order_by('-created_at')
    vendors = DataVendor.objects.all().order_by('-created_at')
    
    # Statistics
    package_stats = {
        'total': packages.count(),
        'active': packages.filter(is_active=True).count(),
        'platform': packages.filter(source_type='platform').count(),
        'vendor': packages.filter(source_type__in=['vendor_direct', 'vendor_marketplace']).count(),
    }
    
    vendor_stats = {
        'total': vendors.count(),
        'approved': vendors.filter(is_approved=True).count(),
        'active': vendors.filter(is_active=True).count(),
    }
    
    context = {
        'packages': packages,
        'vendors': vendors,
        'package_stats': package_stats,
        'vendor_stats': vendor_stats,
        'page_title': 'Bulk Data Management',
        'page_subtitle': 'Manage bulk data packages and vendors',
    }
    
    return render(request, 'admin/superadmin_bulk_data.html', context)

@staff_member_required
def superadmin_create_bulk_package(request):
    """Create new bulk data package"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    if request.method == 'POST':
        try:
            # Extract form data
            name = request.POST.get('name')
            data_amount = Decimal(request.POST.get('data_amount', 0))
            selling_price = Decimal(request.POST.get('selling_price', 0))
            base_cost = Decimal(request.POST.get('base_cost', 0))
            commission_rate = Decimal(request.POST.get('commission_rate', 7.5))
            source_type = request.POST.get('source_type', 'platform')
            vendor_id = request.POST.get('vendor_id')
            validity_days = int(request.POST.get('validity_days', 30))
            description = request.POST.get('description', '')
            
            # Create package
            package = BulkDataPackage.objects.create(
                name=name,
                data_amount=data_amount,
                price=base_cost,
                selling_price=selling_price,
                base_cost=base_cost,
                commission_rate=commission_rate,
                source_type=source_type,
                validity_days=validity_days,
                description=description,
                is_active=True,
                created_by=request.user,
            )
            
            # Associate vendor if provided
            if vendor_id and source_type in ['vendor_direct', 'vendor_marketplace']:
                vendor = get_object_or_404(DataVendor, id=vendor_id)
                package.vendor = vendor
                package.save()
            
            # For platform packages, set stock
            if source_type == 'platform':
                platform_stock = Decimal(request.POST.get('platform_stock', 0))
                platform_margin = Decimal(request.POST.get('platform_margin', 15.0))
                package.platform_stock = platform_stock
                package.platform_margin = platform_margin
                package.save()
            
            messages.success(request, f'Package "{name}" created successfully!')
            return redirect('superadmin_bulk_data')
            
        except Exception as e:
            messages.error(request, f'Error creating package: {str(e)}')
    
    vendors = DataVendor.objects.filter(is_active=True, is_approved=True)
    context = {
        'vendors': vendors,
        'page_title': 'Create Bulk Data Package',
        'page_subtitle': 'Add new bulk data package to marketplace',
    }
    
    return render(request, 'admin/create_bulk_package.html', context)

@staff_member_required
def superadmin_commission_settings(request):
    """Manage platform commission rates"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    commissions = PlatformCommission.objects.all().order_by('service_type')
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'create_commission':
            service_type = request.POST.get('service_type')
            rate = Decimal(request.POST.get('rate', 7.5))
            applies_to_all = request.POST.get('applies_to_all') == 'on'
            tenant_id = request.POST.get('tenant_id')
            
            tenant = None
            if tenant_id and not applies_to_all:
                tenant = get_object_or_404(Tenant, id=tenant_id)
            
            commission = PlatformCommission.objects.create(
                service_type=service_type,
                rate=rate,
                applies_to_all=applies_to_all,
                tenant=tenant,
                is_active=True,
            )
            
            messages.success(request, f'Commission rate for {service_type} set to {rate}%')
            
        elif action == 'update_commission':
            commission_id = request.POST.get('commission_id')
            commission = get_object_or_404(PlatformCommission, id=commission_id)
            
            commission.rate = Decimal(request.POST.get('rate', 7.5))
            commission.is_active = request.POST.get('is_active') == 'on'
            commission.save()
            
            messages.success(request, 'Commission rate updated successfully!')
    
    tenants = Tenant.objects.all()
    context = {
        'commissions': commissions,
        'tenants': tenants,
        'page_title': 'Commission Settings',
        'page_subtitle': 'Configure platform commission rates',
    }
    
    return render(request, 'admin/superadmin_commission_settings.html', context)

@staff_member_required
def superadmin_bulk_purchases_report(request):
    """Report on all bulk data purchases"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    # Filter parameters
    status_filter = request.GET.get('status', '')
    tenant_filter = request.GET.get('tenant', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    
    purchases = ISPBulkPurchase.objects.all().select_related('tenant', 'package').order_by('-purchased_at')
    
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
    
    # Top ISPs by purchase amount
    top_isps = purchases.values('tenant__name').annotate(
        total_purchased=Sum('total_price'),
        total_commission=Sum('platform_commission'),
        purchase_count=Count('id')
    ).order_by('-total_purchased')[:10]
    
    # Monthly trend
    monthly_trend = purchases.values(
        year=ExtractYear('purchased_at'),
        month=ExtractMonth('purchased_at')
    ).annotate(
        total_purchases=Sum('total_price'),
        commission=Sum('platform_commission'),
        count=Count('id')
    ).order_by('-year', '-month')[:6]
    
    context = {
        'purchases': purchases,
        'total_purchases': total_purchases,
        'total_amount': total_amount,
        'total_commission': total_commission,
        'total_isp_net': total_isp_net,
        'top_isps': top_isps,
        'monthly_trend': monthly_trend,
        'tenants': Tenant.objects.all(),
        'status_filter': status_filter,
        'tenant_filter': tenant_filter,
        'date_from': date_from,
        'date_to': date_to,
        'page_title': 'Bulk Purchases Report',
        'page_subtitle': 'Platform-wide bulk data purchase analytics',
    }
    
    return render(request, 'admin/superadmin_bulk_purchases_report.html', context)

@staff_member_required
def superadmin_commission_report(request):
    """Platform-wide commission report"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    # Summary by service type
    by_service = CommissionTransaction.objects.values(
        'commission__service_type'
    ).annotate(
        total_amount=Sum('transaction_amount'),
        total_commission=Sum('commission_amount'),
        transaction_count=Count('id')
    ).order_by('-total_commission')
    
    # Summary by ISP
    by_isp = CommissionTransaction.objects.values(
        'tenant__name'
    ).annotate(
        total_amount=Sum('transaction_amount'),
        total_commission=Sum('commission_amount'),
        transaction_count=Count('id')
    ).order_by('-total_commission')
    
    # Total summary
    total_summary = CommissionTransaction.objects.aggregate(
        total_transactions=Sum('transaction_amount'),
        total_commission=Sum('commission_amount'),
        total_count=Count('id')
    )
    
    # Monthly commission trend
    monthly_commissions = CommissionTransaction.objects.annotate(
        year=ExtractYear('created_at'),
        month=ExtractMonth('created_at')
    ).values('year', 'month').annotate(
        commission=Sum('commission_amount'),
        revenue=Sum('transaction_amount'),
        count=Count('id')
    ).order_by('-year', '-month')[:6]
    
    context = {
        'by_service': by_service,
        'by_isp': by_isp,
        'total_summary': total_summary,
        'monthly_commissions': monthly_commissions,
        'tenants': Tenant.objects.all(),
        'page_title': 'Commission Analytics',
        'page_subtitle': 'Platform commission earnings report',
    }
    
    return render(request, 'admin/superadmin_commission_report.html', context)

@staff_member_required
def superadmin_manage_data_vendors(request):
    """Manage data vendors"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    vendors = DataVendor.objects.all().order_by('-created_at')
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'create_vendor':
            vendor = DataVendor.objects.create(
                name=request.POST.get('name'),
                company_name=request.POST.get('company_name'),
                contact_email=request.POST.get('contact_email'),
                contact_phone=request.POST.get('contact_phone'),
                website=request.POST.get('website', ''),
                bank_name=request.POST.get('bank_name'),
                account_number=request.POST.get('account_number'),
                account_name=request.POST.get('account_name'),
                commission_rate=Decimal(request.POST.get('commission_rate', 5.0)),
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
        
        elif action == 'toggle_active':
            vendor_id = request.POST.get('vendor_id')
            vendor = get_object_or_404(DataVendor, id=vendor_id)
            vendor.is_active = not vendor.is_active
            vendor.save()
            
            status = "activated" if vendor.is_active else "deactivated"
            messages.success(request, f'Vendor "{vendor.name}" {status}')
    
    context = {
        'vendors': vendors,
        'page_title': 'Data Vendors',
        'page_subtitle': 'Manage telecom/data vendors',
    }
    
    return render(request, 'admin/superadmin_data_vendors.html', context)

@staff_member_required
def superadmin_export_bulk_data_purchases(request):
    """Export bulk data purchases to CSV"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    purchases = ISPBulkPurchase.objects.all().select_related('tenant', 'package')
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="bulk_purchases_{timezone.now().strftime("%Y%m%d")}.csv"'
    
    writer = csv.writer(response)
    writer.writerow([
        'Date', 'ISP', 'Package', 'Quantity', 'Total Data (GB)', 
        'Total Amount', 'Platform Commission', 'ISP Net Amount',
        'Payment Status', 'Distribution Status', 'Notes'
    ])
    
    for purchase in purchases:
        writer.writerow([
            purchase.purchased_at.strftime('%Y-%m-%d %H:%M'),
            purchase.tenant.name,
            purchase.package.name,
            purchase.quantity,
            purchase.total_data,
            purchase.total_price,
            purchase.platform_commission,
            purchase.isp_net_amount,
            purchase.get_payment_status_display(),
            'Completed' if purchase.distribution_completed_at else 'Pending',
            purchase.notes[:100] if purchase.notes else ''
        ])
    
    return response

@staff_member_required
def superadmin_export_commissions(request):
    """Export commission transactions to CSV"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    transactions = CommissionTransaction.objects.all().select_related('tenant', 'payment')
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="commissions_{timezone.now().strftime("%Y%m%d")}.csv"'
    
    writer = csv.writer(response)
    writer.writerow([
        'Date', 'ISP', 'Payment Reference', 'Service Type',
        'Transaction Amount', 'Commission Amount', 'Net Amount',
        'Status', 'Description'
    ])
    
    for txn in transactions:
        writer.writerow([
            txn.created_at.strftime('%Y-%m-%d %H:%M'),
            txn.tenant.name,
            txn.payment.reference if txn.payment else 'N/A',
            txn.commission.get_service_type_display() if txn.commission else 'bulk_data',
            txn.transaction_amount,
            txn.commission_amount,
            txn.net_amount,
            txn.get_status_display(),
            txn.description[:100] if txn.description else ''
        ])
    
    return response

    # Add these imports at the top if not already present
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json

@staff_member_required
@require_http_methods(["POST"])
def mark_payment_completed(request, payment_id):
    """Mark a payment as completed (AJAX endpoint)"""
    if not request.user.is_superuser:
        return JsonResponse({'success': False, 'message': 'Access denied'}, status=403)
    
    try:
        payment = get_object_or_404(Payment, id=payment_id)
        
        # Check if payment belongs to the tenant you're managing
        tenant_id = request.POST.get('tenant_id') or request.GET.get('tenant_id')
        if tenant_id and str(payment.user.tenant.id) != str(tenant_id):
            return JsonResponse({'success': False, 'message': 'Payment does not belong to this ISP'})
        
        # Update payment status
        payment.status = 'completed'
        payment.save()
        
        # Log the action
        AdminLog.objects.create(
            tenant=payment.user.tenant,
            admin=request.user,
            action='mark_payment_completed',
            description=f"Marked payment {payment.reference} as completed",
            details=json.dumps({
                'payment_id': str(payment.id),
                'payment_reference': payment.reference,
                'amount': str(payment.amount),
                'previous_status': 'pending',
                'new_status': 'completed'
            })
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Payment marked as completed successfully',
            'payment_id': str(payment.id),
            'new_status': 'completed'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error: {str(e)}'
        }, status=500)

@staff_member_required
@require_http_methods(["POST"])
def refund_payment(request, payment_id):
    """Refund a payment (AJAX endpoint)"""
    if not request.user.is_superuser:
        return JsonResponse({'success': False, 'message': 'Access denied'}, status=403)
    
    try:
        payment = get_object_or_404(Payment, id=payment_id)
        
        # Check if payment is completed
        if payment.status != 'completed':
            return JsonResponse({'success': False, 'message': 'Only completed payments can be refunded'})
        
        # Get refund reason
        data = json.loads(request.body) if request.body else {}
        reason = data.get('reason', 'Refund requested by admin')
        
        # Update payment status to refunded
        payment.status = 'refunded'
        payment.refund_reason = reason
        payment.refunded_at = timezone.now()
        payment.refunded_by = request.user
        payment.save()
        
        # If using PayStack, you might want to call PayStack refund API here
        
        # Log the action
        AdminLog.objects.create(
            tenant=payment.user.tenant,
            admin=request.user,
            action='refund_payment',
            description=f"Refunded payment {payment.reference}",
            details=json.dumps({
                'payment_id': str(payment.id),
                'payment_reference': payment.reference,
                'amount': str(payment.amount),
                'reason': reason
            })
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Payment refunded successfully',
            'payment_id': str(payment.id),
            'new_status': 'refunded'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error: {str(e)}'
        }, status=500)

@staff_member_required
@require_http_methods(["POST"])
def resend_payment_receipt(request, payment_id):
    """Resend payment receipt to customer (AJAX endpoint)"""
    if not request.user.is_superuser:
        return JsonResponse({'success': False, 'message': 'Access denied'}, status=403)
    
    try:
        payment = get_object_or_404(Payment, id=payment_id)
        
        # TODO: Implement actual receipt email sending
        # For now, we'll just log the action
        
        # Log the action
        AdminLog.objects.create(
            tenant=payment.user.tenant,
            admin=request.user,
            action='resend_receipt',
            description=f"Resent receipt for payment {payment.reference} to {payment.user.email}",
            details=json.dumps({
                'payment_id': str(payment.id),
                'payment_reference': payment.reference,
                'customer_email': payment.user.email,
                'amount': str(payment.amount)
            })
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Receipt will be sent to customer email'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error: {str(e)}'
        }, status=500)

@staff_member_required
@require_http_methods(["GET"])
def view_payment_logs(request, payment_id):
    """View payment logs (AJAX endpoint)"""
    if not request.user.is_superuser:
        return JsonResponse({'success': False, 'message': 'Access denied'}, status=403)
    
    try:
        payment = get_object_or_404(Payment, id=payment_id)
        
        # Get payment logs (you might need a PaymentLog model)
        # For now, return basic payment info
        logs = AdminLog.objects.filter(
            action__in=['create_payment', 'mark_payment_completed', 'refund_payment', 'resend_receipt'],
            details__icontains=f'"payment_id": "{payment.id}"'
        ).order_by('-timestamp')[:10]
        
        log_data = []
        for log in logs:
            log_data.append({
                'timestamp': log.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                'action': log.get_action_display(),
                'admin': log.admin.username if log.admin else 'System',
                'description': log.description
            })
        
        return JsonResponse({
            'success': True,
            'payment': {
                'id': str(payment.id),
                'reference': payment.reference,
                'amount': str(payment.amount),
                'status': payment.status,
                'created_at': payment.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'updated_at': payment.updated_at.strftime('%Y-%m-%d %H:%M:%S')
            },
            'logs': log_data
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error: {str(e)}'
        }, status=500)

@staff_member_required
@require_http_methods(["DELETE"])
def delete_payment(request, payment_id):
    """Delete a payment record (AJAX endpoint)"""
    if not request.user.is_superuser:
        return JsonResponse({'success': False, 'message': 'Access denied'}, status=403)
    
    try:
        payment = get_object_or_404(Payment, id=payment_id)
        
        # Check if payment can be deleted (only failed or pending payments)
        if payment.status == 'completed':
            return JsonResponse({'success': False, 'message': 'Completed payments cannot be deleted'})
        
        # Store payment info for logging
        payment_info = {
            'id': str(payment.id),
            'reference': payment.reference,
            'amount': str(payment.amount),
            'customer': payment.user.get_full_name(),
            'status': payment.status
        }
        
        # Delete the payment
        payment.delete()
        
        # Log the action
        AdminLog.objects.create(
            tenant=payment.user.tenant if payment.user.tenant else None,
            admin=request.user,
            action='delete_payment',
            description=f"Deleted payment {payment_info['reference']}",
            details=json.dumps(payment_info)
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Payment deleted successfully'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error: {str(e)}'
        }, status=500)

@staff_member_required
@require_http_methods(["POST"])
def retry_failed_payment(request, payment_id):
    """Retry a failed payment (AJAX endpoint)"""
    if not request.user.is_superuser:
        return JsonResponse({'success': False, 'message': 'Access denied'}, status=403)
    
    try:
        payment = get_object_or_404(Payment, id=payment_id)
        
        # Check if payment is failed
        if payment.status != 'failed':
            return JsonResponse({'success': False, 'message': 'Only failed payments can be retried'})
        
        # Create a new payment based on the failed one
        new_payment = Payment.objects.create(
            user=payment.user,
            plan=payment.plan,
            amount=payment.amount,
            status='pending',
            reference=f"RETRY-{payment.reference}",
            parent_payment=payment,
            metadata=payment.metadata
        )
        
        # Log the action
        AdminLog.objects.create(
            tenant=payment.user.tenant,
            admin=request.user,
            action='retry_payment',
            description=f"Retried failed payment {payment.reference} as {new_payment.reference}",
            details=json.dumps({
                'original_payment_id': str(payment.id),
                'original_reference': payment.reference,
                'new_payment_id': str(new_payment.id),
                'new_reference': new_payment.reference,
                'amount': str(payment.amount)
            })
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Payment retry initiated',
            'new_payment_id': str(new_payment.id),
            'new_reference': new_payment.reference
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error: {str(e)}'
        }, status=500)

@staff_member_required
def payment_details(request, payment_id):
    """Get payment details (AJAX endpoint)"""
    if not request.user.is_superuser:
        return JsonResponse({'success': False, 'message': 'Access denied'}, status=403)
    
    try:
        payment = get_object_or_404(Payment, id=payment_id)
        
        return JsonResponse({
            'success': True,
            'payment': {
                'id': str(payment.id),
                'reference': payment.reference,
                'customer_name': payment.user.get_full_name(),
                'plan_name': payment.plan.name if payment.plan else 'N/A',
                'amount': str(payment.amount),
                'status': payment.status,
                'metadata': payment.metadata or {},
                'created_at': payment.created_at.isoformat(),
                'updated_at': payment.updated_at.isoformat(),
                'paystack_reference': payment.paystack_reference or 'N/A'
            }
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error: {str(e)}'
        }, status=500)

@staff_member_required
@require_http_methods(["POST"])
def send_payment_reminders(request, tenant_id):
    """Send payment reminders to customers with pending payments (AJAX endpoint)"""
    if not request.user.is_superuser:
        return JsonResponse({'success': False, 'message': 'Access denied'}, status=403)
    
    try:
        tenant = get_object_or_404(Tenant, id=tenant_id)
        
        # Find customers with pending payments
        pending_payments = Payment.objects.filter(
            user__tenant=tenant,
            status='pending',
            created_at__gte=timezone.now() - timedelta(days=3)
        ).select_related('user').distinct('user')
        
        count = 0
        for payment in pending_payments:
            # TODO: Send actual reminder email/SMS
            count += 1
            
            # Log each reminder
            AdminLog.objects.create(
                tenant=tenant,
                admin=request.user,
                action='send_payment_reminder',
                description=f"Sent payment reminder to {payment.user.get_full_name()}",
                details=json.dumps({
                    'customer_id': str(payment.user.id),
                    'customer_email': payment.user.email,
                    'payment_id': str(payment.id),
                    'payment_reference': payment.reference,
                    'amount': str(payment.amount)
                })
            )
        
        # Log the bulk action
        AdminLog.objects.create(
            tenant=tenant,
            admin=request.user,
            action='bulk_send_reminders',
            description=f"Sent payment reminders to {count} customers",
            details=json.dumps({'count': count, 'tenant_id': str(tenant.id)})
        )
        
        return JsonResponse({
            'success': True,
            'message': f'Payment reminders sent to {count} customers',
            'count': count
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error: {str(e)}'
        }, status=500)

@staff_member_required
def export_tenant_payments(request, tenant_id):
    """Export tenant payments to CSV"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    tenant = get_object_or_404(Tenant, id=tenant_id)
    
    # Get filter parameters
    status = request.GET.get('status', '')
    date_filter = request.GET.get('date', '')
    
    payments = Payment.objects.filter(user__tenant=tenant).select_related('user', 'plan')
    
    if status and status != 'all':
        payments = payments.filter(status=status)
    
    if date_filter:
        now = timezone.now()
        if date_filter == 'today':
            payments = payments.filter(created_at__date=now.date())
        elif date_filter == 'week':
            week_ago = now - timedelta(days=7)
            payments = payments.filter(created_at__gte=week_ago)
        elif date_filter == 'month':
            month_ago = now - timedelta(days=30)
            payments = payments.filter(created_at__gte=month_ago)
        elif date_filter == 'year':
            year_ago = now - timedelta(days=365)
            payments = payments.filter(created_at__gte=year_ago)
    
    # Create CSV response
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{tenant.subdomain}_payments_{timezone.now().strftime("%Y%m%d")}.csv"'
    
    writer = csv.writer(response)
    writer.writerow([
        'Payment ID', 'Reference', 'Customer', 'Plan', 'Amount',
        'Status', 'Payment Method', 'PayStack Ref', 'Created Date',
        'Completed Date', 'Customer Email', 'Customer Phone'
    ])
    
    for payment in payments:
        writer.writerow([
            payment.id,
            payment.reference,
            payment.user.get_full_name(),
            payment.plan.name if payment.plan else 'N/A',
            payment.amount,
            payment.status,
            payment.payment_method or 'paystack',
            payment.paystack_reference or '',
            payment.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            payment.completed_at.strftime('%Y-%m-%d %H:%M:%S') if payment.completed_at else '',
            payment.user.email,
            payment.user.phone or ''
        ])
    
    return response

@staff_member_required
def generate_payment_report(request, tenant_id):
    """Generate PDF payment report for tenant"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    tenant = get_object_or_404(Tenant, id=tenant_id)
    
    # This would typically generate a PDF using a library like ReportLab
    # For now, we'll return a CSV as an example
    format_type = request.GET.get('format', 'csv')
    
    if format_type == 'pdf':
        # Implement PDF generation here
        # return HttpResponse(pdf_content, content_type='application/pdf')
        pass
    
    # Fallback to CSV
    return export_tenant_payments(request, tenant_id)

# Add to views_superadmin.py
@staff_member_required
@require_http_methods(["POST", "GET", "DELETE"])
def payment_api_handler(request, tenant_id, payment_id, action):
    """Handle all payment API calls"""
    if not request.user.is_superuser:
        return JsonResponse({'success': False, 'message': 'Access denied'}, status=403)
    
    # Check if payment belongs to tenant
    try:
        payment = Payment.objects.get(id=payment_id, user__tenant_id=tenant_id)
    except Payment.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Payment not found or does not belong to this ISP'}, status=404)
    
    handlers = {
        'mark-completed': handle_mark_completed,
        'refund': handle_refund,
        'resend-receipt': handle_resend_receipt,
        'logs': handle_get_logs,
        'delete': handle_delete,
        'retry': handle_retry,
        'details': handle_details,
    }
    
    handler = handlers.get(action)
    if handler:
        return handler(request, payment)
    
    return JsonResponse({'success': False, 'message': 'Invalid action'}, status=400)

def handle_mark_completed(request, payment):
    """Mark payment as completed"""
    payment.status = 'completed'
    payment.completed_at = timezone.now()
    payment.save()
    
    # Log the action
    AdminLog.objects.create(
        tenant=payment.user.tenant,
        admin=request.user,
        action='mark_payment_completed',
        description=f"Marked payment {payment.reference} as completed",
        details={
            'payment_id': str(payment.id),
            'amount': str(payment.amount),
            'previous_status': 'pending',
            'new_status': 'completed'
        }
    )
    
    return JsonResponse({
        'success': True,
        'message': 'Payment marked as completed successfully',
        'payment_id': str(payment.id),
        'new_status': 'completed'
    })

def handle_refund(request, payment):
    """Handle refund"""
    data = json.loads(request.body) if request.body else {}
    reason = data.get('reason', 'Refund requested by admin')
    
    payment.status = 'refunded'
    payment.refund_reason = reason
    payment.refunded_at = timezone.now()
    payment.refunded_by = request.user
    payment.save()
    
    # Log the action
    AdminLog.objects.create(
        tenant=payment.user.tenant,
        admin=request.user,
        action='refund_payment',
        description=f"Refunded payment {payment.reference}",
        details={
            'payment_id': str(payment.id),
            'amount': str(payment.amount),
            'reason': reason
        }
    )
    
    return JsonResponse({
        'success': True,
        'message': 'Payment refund initiated successfully',
        'payment_id': str(payment.id)
    })

# Add these handler functions to your views_superadmin.py

def handle_resend_receipt(request, payment):
    """Handle resending receipt"""
    # TODO: Implement actual email sending logic
    # For now, just log the action
    
    AdminLog.objects.create(
        tenant=payment.user.tenant,
        admin=request.user,
        action='resend_payment_receipt',
        description=f"Resent receipt for payment {payment.reference} to {payment.user.email}",
        details={
            'payment_id': str(payment.id),
            'amount': str(payment.amount),
            'customer_email': payment.user.email,
            'customer_name': payment.user.get_full_name()
        }
    )
    
    return JsonResponse({
        'success': True,
        'message': f'Receipt will be sent to {payment.user.email}',
        'payment_id': str(payment.id),
        'customer_email': payment.user.email
    })

def handle_get_logs(request, payment):
    """Get payment logs"""
    # Get admin logs related to this payment
    logs = AdminLog.objects.filter(
        tenant=payment.user.tenant,
        details__contains=f'"payment_id": "{payment.id}"'
    ).order_by('-timestamp')[:10]
    
    # If no specific payment logs found, get general logs
    if not logs.exists():
        logs = AdminLog.objects.filter(
            tenant=payment.user.tenant,
            action__icontains='payment'
        ).order_by('-timestamp')[:10]
    
    log_data = []
    for log in logs:
        log_data.append({
            'timestamp': log.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            'action': log.get_action_display(),
            'admin': log.admin.username if log.admin else 'System',
            'description': log.description
        })
    
    return JsonResponse({
        'success': True,
        'payment': {
            'id': str(payment.id),
            'reference': payment.reference,
            'amount': str(payment.amount),
            'status': payment.status,
            'created_at': payment.created_at.isoformat(),
            'updated_at': payment.updated_at.isoformat()
        },
        'logs': log_data
    })

def handle_delete(request, payment):
    """Handle payment deletion"""
    # Check if payment can be deleted (only pending or failed payments)
    if payment.status == 'completed':
        return JsonResponse({
            'success': False,
            'message': 'Completed payments cannot be deleted. Consider refunding instead.'
        }, status=400)
    
    # Store payment info for logging
    payment_info = {
        'id': str(payment.id),
        'reference': payment.reference,
        'amount': str(payment.amount),
        'customer': payment.user.get_full_name(),
        'status': payment.status
    }
    
    # Delete the payment
    payment.delete()
    
    # Log the action
    AdminLog.objects.create(
        tenant=payment.user.tenant if payment.user.tenant else None,
        admin=request.user,
        action='delete_payment',
        description=f"Deleted payment {payment_info['reference']}",
        details=payment_info
    )
    
    return JsonResponse({
        'success': True,
        'message': 'Payment deleted successfully',
        'deleted_payment': payment_info
    })

def handle_retry(request, payment):
    """Handle payment retry"""
    # Check if payment is failed
    if payment.status != 'failed':
        return JsonResponse({
            'success': False,
            'message': 'Only failed payments can be retried'
        }, status=400)
    
    # Create a new payment based on the failed one
    try:
        new_payment = Payment.objects.create(
            user=payment.user,
            plan=payment.plan,
            amount=payment.amount,
            status='pending',
            reference=f"RETRY-{payment.reference}-{timezone.now().strftime('%Y%m%d%H%M%S')}",
            parent_payment=payment,
            metadata=payment.metadata
        )
        
        # Log the action
        AdminLog.objects.create(
            tenant=payment.user.tenant,
            admin=request.user,
            action='retry_payment',
            description=f"Retried failed payment {payment.reference} as {new_payment.reference}",
            details={
                'original_payment_id': str(payment.id),
                'original_reference': payment.reference,
                'new_payment_id': str(new_payment.id),
                'new_reference': new_payment.reference,
                'amount': str(payment.amount)
            }
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Payment retry initiated',
            'new_payment_id': str(new_payment.id),
            'new_reference': new_payment.reference
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error creating retry payment: {str(e)}'
        }, status=500)

def handle_details(request, payment):
    """Get payment details"""
    return JsonResponse({
        'success': True,
        'payment': {
            'id': str(payment.id),
            'reference': payment.reference,
            'customer_name': payment.user.get_full_name(),
            'plan_name': payment.plan.name if payment.plan else 'N/A',
            'amount': str(payment.amount),
            'status': payment.status,
            'metadata': payment.metadata or {},
            'created_at': payment.created_at.isoformat(),
            'updated_at': payment.updated_at.isoformat(),
            'paystack_reference': payment.paystack_reference or 'N/A',
            'payment_method': payment.payment_method or 'paystack',
            'customer_email': payment.user.email,
            'customer_phone': payment.user.phone or ''
        }
    })

@staff_member_required
@require_http_methods(["POST", "GET", "DELETE"])
def legacy_payment_api_handler(request, payment_id, action):
    """
    Handle legacy API calls: /api/payments/{id}/{action}/
    Redirects to the tenant-specific endpoint
    """
    try:
        # Get the payment to find its tenant
        payment = Payment.objects.get(id=payment_id)
        tenant_id = payment.user.tenant.id
        
        # Forward to the correct endpoint
        # Note: In production, you might want to forward the request instead of redirecting
        # For now, we'll process it directly
        
        return payment_api_handler(request, tenant_id, payment_id, action)
        
    except Payment.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'Payment not found'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error: {str(e)}'
        }, status=500)

# Add to imports
from billing.models import BulkBandwidthPackage, ISPBandwidthPurchase

@staff_member_required
def superadmin_bulk_bandwidth_management(request):
    """Superadmin: Manage bulk bandwidth packages and purchases"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    packages = BulkBandwidthPackage.objects.all().order_by('-created_at')
    purchases = ISPBandwidthPurchase.objects.all().select_related('tenant', 'bandwidth_package').order_by('-purchased_at')
    
    # Statistics
    package_stats = {
        'total': packages.count(),
        'active': packages.filter(is_active=True).count(),
        'dedicated': packages.filter(package_type='dedicated').count(),
        'shared': packages.filter(package_type='shared').count(),
        'burst': packages.filter(package_type='burst').count(),
    }
    
    purchase_stats = {
        'total': purchases.count(),
        'active': purchases.filter(payment_status='active').count(),
        'pending': purchases.filter(payment_status='pending').count(),
        'completed': purchases.filter(payment_status='completed').count(),
        'total_revenue': purchases.filter(payment_status__in=['completed', 'active']).aggregate(
            total=Sum('total_price')
        )['total'] or Decimal('0'),
    }
    
    context = {
        'packages': packages,
        'purchases': purchases,
        'package_stats': package_stats,
        'purchase_stats': purchase_stats,
        'page_title': 'Bulk Bandwidth Management',
        'page_subtitle': 'Manage bandwidth packages and ISP purchases',
    }
    
    return render(request, 'admin/superadmin_bulk_bandwidth.html', context)


@staff_member_required
def superadmin_create_bandwidth_package(request):
    """Create new bulk bandwidth package"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    vendors = DataVendor.objects.filter(is_active=True, is_approved=True)
    
    if request.method == 'POST':
        try:
            # Extract form data
            vendor_id = request.POST.get('vendor_id')
            name = request.POST.get('name')
            package_type = request.POST.get('package_type', 'dedicated')
            bandwidth_amount = Decimal(request.POST.get('bandwidth_amount', 0))
            unit = request.POST.get('unit', 'mbps')
            base_cost = Decimal(request.POST.get('base_cost', 0))
            selling_price = Decimal(request.POST.get('selling_price', 0))
            commission_rate = Decimal(request.POST.get('commission_rate', 7.5))
            validity_days = int(request.POST.get('validity_days', 30))
            
            # Technical details
            upstream_commit = request.POST.get('upstream_commit')
            downstream_commit = request.POST.get('downstream_commit')
            burst_limit = request.POST.get('burst_limit')
            
            # Get vendor
            vendor = get_object_or_404(DataVendor, id=vendor_id)
            
            # Create package
            package = BulkBandwidthPackage.objects.create(
                vendor=vendor,
                name=name,
                package_type=package_type,
                bandwidth_amount=bandwidth_amount,
                unit=unit,
                base_cost=base_cost,
                selling_price=selling_price,
                commission_rate=commission_rate,
                validity_days=validity_days,
                upstream_commit=Decimal(upstream_commit) if upstream_commit else None,
                downstream_commit=Decimal(downstream_commit) if downstream_commit else None,
                burst_limit=Decimal(burst_limit) if burst_limit else None,
                is_active=True,
            )
            
            messages.success(request, f'Bandwidth package "{name}" created successfully!')
            return redirect('superadmin_bulk_bandwidth')
            
        except Exception as e:
            messages.error(request, f'Error creating bandwidth package: {str(e)}')
    
    context = {
        'vendors': vendors,
        'page_title': 'Create Bandwidth Package',
        'page_subtitle': 'Add new bulk bandwidth package',
    }
    
    return render(request, 'admin/create_bandwidth_package.html', context)


@staff_member_required
def superadmin_bandwidth_purchases_report(request):
    """Report on all bandwidth purchases"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    # Filter parameters
    status_filter = request.GET.get('status', '')
    tenant_filter = request.GET.get('tenant', '')
    vendor_filter = request.GET.get('vendor', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    
    purchases = ISPBandwidthPurchase.objects.all().select_related(
        'tenant', 'bandwidth_package', 'bandwidth_package__vendor'
    ).order_by('-purchased_at')
    
    if status_filter:
        purchases = purchases.filter(payment_status=status_filter)
    
    if tenant_filter:
        purchases = purchases.filter(tenant_id=tenant_filter)
    
    if vendor_filter:
        purchases = purchases.filter(bandwidth_package__vendor_id=vendor_filter)
    
    if date_from:
        purchases = purchases.filter(purchased_at__gte=date_from)
    
    if date_to:
        purchases = purchases.filter(purchased_at__lte=date_to)
    
    # Statistics
    total_purchases = purchases.count()
    total_amount = purchases.aggregate(total=Sum('total_price'))['total'] or Decimal('0')
    total_commission = purchases.aggregate(total=Sum('platform_commission'))['total'] or Decimal('0')
    total_bandwidth = purchases.aggregate(total=Sum('total_bandwidth'))['total'] or Decimal('0')
    
    # Top ISPs by bandwidth purchased
    top_isps = purchases.values('tenant__name').annotate(
        total_bandwidth=Sum('total_bandwidth'),
        total_spent=Sum('total_price'),
        purchase_count=Count('id')
    ).order_by('-total_bandwidth')[:10]
    
    # Monthly trend
    monthly_trend = purchases.values(
        year=ExtractYear('purchased_at'),
        month=ExtractMonth('purchased_at')
    ).annotate(
        total_bandwidth=Sum('total_bandwidth'),
        total_revenue=Sum('total_price'),
        count=Count('id')
    ).order_by('-year', '-month')[:6]
    
    context = {
        'purchases': purchases,
        'total_purchases': total_purchases,
        'total_amount': total_amount,
        'total_commission': total_commission,
        'total_bandwidth': total_bandwidth,
        'top_isps': top_isps,
        'monthly_trend': monthly_trend,
        'tenants': Tenant.objects.all(),
        'vendors': DataVendor.objects.filter(is_active=True),
        'status_filter': status_filter,
        'tenant_filter': tenant_filter,
        'vendor_filter': vendor_filter,
        'date_from': date_from,
        'date_to': date_to,
        'page_title': 'Bandwidth Purchases Report',
        'page_subtitle': 'Platform-wide bandwidth purchase analytics',
    }
    
    return render(request, 'admin/superadmin_bandwidth_purchases_report.html', context)


@staff_member_required
@require_http_methods(["POST"])
def toggle_bandwidth_package_status(request, package_id):
    """Toggle bandwidth package active status"""
    if not request.user.is_superuser:
        return JsonResponse({'success': False, 'message': 'Access denied'}, status=403)
    
    try:
        package = get_object_or_404(BulkBandwidthPackage, id=package_id)
        package.is_active = not package.is_active
        package.save()
        
        return JsonResponse({
            'success': True,
            'message': f'Package {"activated" if package.is_active else "deactivated"}',
            'is_active': package.is_active
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error: {str(e)}'
        }, status=500)


@staff_member_required
@require_http_methods(["POST"])
def activate_bandwidth_purchase(request, purchase_id):
    """Activate a bandwidth purchase"""
    if not request.user.is_superuser:
        return JsonResponse({'success': False, 'message': 'Access denied'}, status=403)
    
    try:
        purchase = get_object_or_404(ISPBandwidthPurchase, id=purchase_id)
        
        if purchase.payment_status != 'completed':
            return JsonResponse({
                'success': False,
                'message': 'Only completed purchases can be activated'
            }, status=400)
        
        purchase.payment_status = 'active'
        purchase.activation_date = timezone.now()
        purchase.activated_by = request.user
        purchase.expiry_date = timezone.now() + timedelta(days=purchase.bandwidth_package.validity_days)
        purchase.save()
        
        # Log the action
        AdminLog.objects.create(
            tenant=purchase.tenant,
            admin=request.user,
            action='activate_bandwidth_purchase',
            description=f"Activated bandwidth purchase {purchase_id} for {purchase.tenant.name}",
            details=json.dumps({
                'purchase_id': str(purchase.id),
                'bandwidth': str(purchase.total_bandwidth),
                'expiry_date': purchase.expiry_date.isoformat()
            })
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Bandwidth purchase activated successfully',
            'new_status': 'active',
            'expiry_date': purchase.expiry_date.isoformat()
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error: {str(e)}'
        }, status=500)


@staff_member_required
def export_bandwidth_purchases(request):
    """Export bandwidth purchases to CSV"""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Access denied")
    
    purchases = ISPBandwidthPurchase.objects.all().select_related(
        'tenant', 'bandwidth_package', 'bandwidth_package__vendor'
    )
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="bandwidth_purchases_{timezone.now().strftime("%Y%m%d")}.csv"'
    
    writer = csv.writer(response)
    writer.writerow([
        'Date', 'ISP', 'Vendor', 'Package', 'Bandwidth', 'Unit',
        'Total Amount', 'Platform Commission', 'ISP Net Amount',
        'Payment Status', 'Activation Date', 'Expiry Date', 'Notes'
    ])
    
    for purchase in purchases:
        writer.writerow([
            purchase.purchased_at.strftime('%Y-%m-%d %H:%M'),
            purchase.tenant.name,
            purchase.bandwidth_package.vendor.name,
            purchase.bandwidth_package.name,
            purchase.total_bandwidth,
            purchase.bandwidth_package.unit,
            purchase.total_price,
            purchase.platform_commission,
            purchase.isp_net_amount,
            purchase.get_payment_status_display(),
            purchase.activation_date.strftime('%Y-%m-%d %H:%M') if purchase.activation_date else '',
            purchase.expiry_date.strftime('%Y-%m-%d %H:%M') if purchase.expiry_date else '',
            purchase.notes[:100] if purchase.notes else ''
        ])
    
    return response
