# router_manager/views_assignment.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.db.models import Q, Count
from django.core.paginator import Paginator
import json, csv, io
import pandas as pd
from datetime import datetime

from accounts.decorators import isp_required
from accounts.models import CustomUser, Tenant
from .models import RouterConfig, Router, RouterLog
from .forms import (
    RouterAssignmentForm, QuickAssignmentForm, 
    RouterConfigForm, BulkAssignmentForm, RouterFilterForm
)


@login_required
@isp_required
def router_assignment_dashboard(request):
    """Main dashboard for router assignments"""
    tenant = request.user.tenant
    
    # Get statistics
    total_configs = RouterConfig.objects.filter(tenant=tenant).count()
    available_configs = RouterConfig.objects.filter(tenant=tenant, is_available=True).count()
    assigned_configs = RouterConfig.objects.filter(tenant=tenant, is_available=False).count()
    online_configs = RouterConfig.objects.filter(tenant=tenant, is_online=True).count()
    
    # Get customers without routers
    customers_without_routers = CustomUser.objects.filter(
        tenant=tenant,
        role='customer',
        is_active=True
    ).exclude(
        id__in=RouterConfig.objects.filter(
            tenant=tenant,
            assigned_to__isnull=False
        ).values_list('assigned_to_id', flat=True)
    ).count()
    
    # Recent assignments - use created_at instead of updated_at
    recent_assignments = RouterConfig.objects.filter(
        tenant=tenant,
        is_available=False
    ).select_related('assigned_to').order_by('-created_at')[:10]  # Changed to -created_at
    
    # Available routers by type
    router_types = RouterConfig.objects.filter(
        tenant=tenant,
        is_available=True
    ).values('router_type').annotate(
        count=Count('id')
    ).order_by('-count')
    
    context = {
        'tenant': tenant,
        'stats': {
            'total': total_configs,
            'available': available_configs,
            'assigned': assigned_configs,
            'online': online_configs,
            'customers_without': customers_without_routers,
        },
        'recent_assignments': recent_assignments,
        'router_types': router_types,
        'page_title': 'Router Assignment Dashboard',
        'page_subtitle': 'Manage router assignments to customers',
    }
    
    return render(request, 'router/assignment_dashboard.html', context)

@login_required
@isp_required
def router_assignment_list(request):
    """List all router assignments with filtering"""
    tenant = request.user.tenant
    
    # Get filter parameters
    status_filter = request.GET.get('status', 'all')
    type_filter = request.GET.get('type', 'all')
    search_query = request.GET.get('search', '')
    
    # Start with all router configs for this tenant
    router_configs = RouterConfig.objects.filter(tenant=tenant)
    
    # Apply filters
    if status_filter == 'available':
        router_configs = router_configs.filter(is_available=True)
    elif status_filter == 'assigned':
        router_configs = router_configs.filter(is_available=False)
    elif status_filter == 'online':
        router_configs = router_configs.filter(is_online=True)
    elif status_filter == 'offline':
        router_configs = router_configs.filter(is_online=False)
    
    if type_filter != 'all':
        router_configs = router_configs.filter(router_type=type_filter)
    
    if search_query:
        router_configs = router_configs.filter(
            Q(name__icontains=search_query) |
            Q(router_model__icontains=search_query) |
            Q(ip_address__icontains=search_query) |
            Q(assigned_to__username__icontains=search_query) |
            Q(assigned_to__email__icontains=search_query)
        )
    
    # Order by availability then name
    router_configs = router_configs.order_by('-is_available', 'name')

    assigned_count = router_configs.filter(is_available=False).count()
    online_count = router_configs.filter(is_online=True).count()

    
    # Pagination
    paginator = Paginator(router_configs, 25)
    page = request.GET.get('page', 1)
    
    try:
        configs_page = paginator.page(page)
    except Exception:
        configs_page = paginator.page(1)
    
    # Get customers without routers for quick assignment
    customers_without_routers = CustomUser.objects.filter(
        tenant=tenant,
        role='customer',
        is_active=True
    ).exclude(
        id__in=RouterConfig.objects.filter(
            tenant=tenant,
            assigned_to__isnull=False
        ).values_list('assigned_to_id', flat=True)
    ).order_by('username')
    
    # Filter form
    filter_form = RouterFilterForm(initial={
        'status': status_filter,
        'router_type': type_filter,
        'search': search_query
    })
    
    context = {
        'tenant': tenant,
        'router_configs': configs_page,
        'customers_without_routers': customers_without_routers,
        'filter_form': filter_form,
        'status_filter': status_filter,
        'type_filter': type_filter,
        'search_query': search_query,
        'assigned': assigned_count,
        'online': online_count,
        'page_title': 'Router Assignments',
        'page_subtitle': 'Manage router assignments',
    }
    
    return render(request, 'router/assignment_list.html', context)


@login_required
@isp_required
def assign_router_to_customer(request, config_id):
    """Assign router config to customer"""
    tenant = request.user.tenant
    
    try:
        router_config = RouterConfig.objects.get(id=config_id, tenant=tenant)
    except RouterConfig.DoesNotExist:
        messages.error(request, 'Router configuration not found')
        return redirect('router_assignment_list')
    
    if not router_config.is_available:
        messages.error(request, f'Router "{router_config.name}" is already assigned')
        return redirect('router_assignment_list')
    
    # Get customers without routers
    available_customers = CustomUser.objects.filter(
        tenant=tenant,
        role='customer',
        is_active=True
    ).exclude(
        id__in=RouterConfig.objects.filter(
            tenant=tenant,
            assigned_to__isnull=False
        ).values_list('assigned_to_id', flat=True)
    ).order_by('username')
    
    if request.method == 'POST':
        form = RouterAssignmentForm(request.POST, tenant=tenant)
        if form.is_valid():
            try:
                customer = form.cleaned_data['customer']
                notes = form.cleaned_data.get('notes', '')
                
                # Check if customer still doesn't have a router
                if RouterConfig.objects.filter(tenant=tenant, assigned_to=customer).exists():
                    messages.error(request, f'Customer {customer.username} already has a router assigned')
                    return redirect('router_assignment_list')
                
                # Assign router to customer
                router = router_config.assign_to_customer(customer)
                
                # Add notes if provided
                if notes:
                    router_config.notes = notes
                    router_config.save()
                
                # Log the assignment
                RouterLog.objects.create(
                    router=router,
                    log_type='assignment',
                    message=f'Router assigned to {customer.username} by {request.user.username}'
                )
                
                messages.success(
                    request,
                    f'Router "{router_config.name}" successfully assigned to {customer.username}'
                )
                return redirect('router_assignment_list')
                
            except Exception as e:
                messages.error(request, f'Error assigning router: {str(e)}')
    else:
        form = RouterAssignmentForm(tenant=tenant, initial={'name': router_config.name})
    
    context = {
        'tenant': tenant,
        'router_config': router_config,
        'form': form,
        'available_customers': available_customers,
        'page_title': f'Assign Router: {router_config.name}',
        'page_subtitle': 'Select customer for router assignment',
    }
    
    return render(request, 'router/assign_router.html', context)

@login_required
@isp_required
def unassign_router(request, config_id):
    """Unassign router config from customer"""
    tenant = request.user.tenant
    
    try:
        router_config = RouterConfig.objects.get(id=config_id, tenant=tenant, is_available=False)
    except RouterConfig.DoesNotExist:
        messages.error(request, 'Router configuration not found or not assigned')
        return redirect('router_assignment_list')
    
    customer = router_config.assigned_to
    
    if request.method == 'POST':
        confirm = request.POST.get('confirm', 'no')
        
        if confirm == 'yes':
            try:
                # Unassign router
                router_config.unassign()
                
                # Log the unassignment
                Router.objects.filter(user=customer, router_config=router_config).update(router_config=None)
                
                messages.success(
                    request,
                    f'Router "{router_config.name}" unassigned from {customer.username}'
                )
                
            except Exception as e:
                messages.error(request, f'Error unassigning router: {str(e)}')
        
        return redirect('router_assignment_list')
    
    context = {
        'tenant': tenant,
        'router_config': router_config,
        'customer': customer,
        'page_title': 'Unassign Router',
        'page_subtitle': 'Confirm router unassignment',
    }
    
    return render(request, 'router/unassign_router.html', context)


@login_required
@isp_required
def quick_assign_router(request):
    """Quick assign router via AJAX"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST method required'})
    
    tenant = request.user.tenant
    
    try:
        data = json.loads(request.body)
        config_id = data.get('config_id')
        customer_id = data.get('customer_id')
        
        router_config = RouterConfig.objects.get(id=config_id, tenant=tenant)
        customer = CustomUser.objects.get(id=customer_id, tenant=tenant, role='customer')
        
        # Check if router is available
        if not router_config.is_available:
            return JsonResponse({
                'success': False,
                'error': f'Router "{router_config.name}" is already assigned'
            })
        
        # Check if customer already has a router
        if RouterConfig.objects.filter(tenant=tenant, assigned_to=customer).exists():
            return JsonResponse({
                'success': False,
                'error': f'Customer {customer.username} already has a router assigned'
            })
        
        # Assign router
        router = router_config.assign_to_customer(customer)
        
        # Log the assignment
        RouterLog.objects.create(
            router=router,
            log_type='assignment',
            message=f'Quick assignment to {customer.username} by {request.user.username}'
        )
        
        return JsonResponse({
            'success': True,
            'message': f'Router assigned to {customer.username}',
            'customer': {
                'id': customer.id,
                'username': customer.username,
                'email': customer.email,
            },
            'router_config': {
                'id': router_config.id,
                'name': router_config.name,
                'status': 'assigned'
            }
        })
        
    except RouterConfig.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Router configuration not found'})
    except CustomUser.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Customer not found'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
@isp_required
def bulk_assignment(request):
    """Bulk assign routers from CSV/Excel file"""
    tenant = request.user.tenant
    
    if request.method == 'POST':
        form = BulkAssignmentForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded_file = request.FILES['customer_file']
            file_type = form.cleaned_data['file_type']
            
            try:
                # Process file based on type
                if file_type == 'csv':
                    file_content = uploaded_file.read().decode('utf-8')
                    reader = csv.DictReader(io.StringIO(file_content))
                    data = list(reader)
                else:  # excel
                    df = pd.read_excel(uploaded_file)
                    data = df.to_dict('records')
                
                # Process assignments
                results = {
                    'total': len(data),
                    'successful': 0,
                    'failed': 0,
                    'details': []
                }
                
                for row in data:
                    try:
                        customer_username = row.get('username', '').strip()
                        router_name = row.get('router_name', '').strip()
                        
                        if not customer_username or not router_name:
                            results['failed'] += 1
                            results['details'].append({
                                'row': row,
                                'error': 'Missing username or router_name'
                            })
                            continue
                        
                        # Get customer and router
                        customer = CustomUser.objects.get(
                            username=customer_username,
                            tenant=tenant,
                            role='customer'
                        )
                        
                        router_config = RouterConfig.objects.get(
                            name=router_name,
                            tenant=tenant,
                            is_available=True
                        )
                        
                        # Check if customer already has router
                        if RouterConfig.objects.filter(tenant=tenant, assigned_to=customer).exists():
                            results['failed'] += 1
                            results['details'].append({
                                'row': row,
                                'error': f'Customer {customer_username} already has a router'
                            })
                            continue
                        
                        # Assign router
                        router = router_config.assign_to_customer(customer)
                        
                        results['successful'] += 1
                        results['details'].append({
                            'row': row,
                            'success': True
                        })
                        
                    except CustomUser.DoesNotExist:
                        results['failed'] += 1
                        results['details'].append({
                            'row': row,
                            'error': f'Customer {row.get("username")} not found'
                        })
                    except RouterConfig.DoesNotExist:
                        results['failed'] += 1
                        results['details'].append({
                            'row': row,
                            'error': f'Router {row.get("router_name")} not found or not available'
                        })
                    except Exception as e:
                        results['failed'] += 1
                        results['details'].append({
                            'row': row,
                            'error': str(e)
                        })
                
                # Store results in session
                request.session['bulk_assignment_results'] = results
                
                messages.success(
                    request,
                    f'Bulk assignment completed: {results["successful"]} successful, {results["failed"]} failed'
                )
                
                return redirect('bulk_assignment_results')
                
            except Exception as e:
                messages.error(request, f'Error processing file: {str(e)}')
    else:
        form = BulkAssignmentForm()
    
    # Get sample data
    sample_data = [
        {'username': 'customer1', 'router_name': 'Office Router 1'},
        {'username': 'customer2', 'router_name': 'Office Router 2'},
    ]
    
    context = {
        'tenant': tenant,
        'form': form,
        'sample_data': sample_data,
        'page_title': 'Bulk Router Assignment',
        'page_subtitle': 'Assign routers to multiple customers via CSV/Excel',
    }
    
    return render(request, 'router/bulk_assignment.html', context)


@login_required
@isp_required
def bulk_assignment_results(request):
    """Show results of bulk assignment"""
    tenant = request.user.tenant
    
    results = request.session.get('bulk_assignment_results', {})
    
    if not results:
        messages.error(request, 'No bulk assignment results found')
        return redirect('bulk_assignment')
    
    context = {
        'tenant': tenant,
        'results': results,
        'page_title': 'Bulk Assignment Results',
        'page_subtitle': 'Results of bulk router assignment',
    }
    
    return render(request, 'router/bulk_assignment_results.html', context)


@login_required
@isp_required
def available_routers_api(request):
    """API endpoint to get available routers"""
    tenant = request.user.tenant
    
    available_configs = RouterConfig.objects.filter(
        tenant=tenant,
        is_available=True
    ).values('id', 'name', 'router_type', 'router_model', 'ip_address')
    
    configs_list = list(available_configs)
    
    return JsonResponse({
        'success': True,
        'available_routers': configs_list
    })


@login_required
@isp_required
def customer_router_details(request, customer_id):
    """View customer's router details"""
    tenant = request.user.tenant
    
    try:
        customer = CustomUser.objects.get(id=customer_id, tenant=tenant, role='customer')
    except CustomUser.DoesNotExist:
        messages.error(request, 'Customer not found')
        return redirect('router_assignment_list')
    
    # Get customer's router
    try:
        router = Router.objects.get(user=customer)
    except Router.DoesNotExist:
        router = None
    
    # Get assigned router config if any
    router_config = None
    if router and router.router_config:
        router_config = router.router_config
    
    # Get connected devices
    connected_devices = []
    if router:
        from .models import ConnectedDevice
        connected_devices = ConnectedDevice.objects.filter(router=router).order_by('-last_seen')[:10]
    
    context = {
        'tenant': tenant,
        'customer': customer,
        'router': router,
        'router_config': router_config,
        'connected_devices': connected_devices,
        'page_title': f'Router Details: {customer.username}',
        'page_subtitle': 'View customer router information',
    }
    
    return render(request, 'router/customer_router_details.html', context)


@login_required
@isp_required
def download_assignment_template(request):
    """Download CSV template for bulk assignment"""
    # Create CSV response
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="router_assignment_template.csv"'
    
    writer = csv.writer(response)
    
    # Write header
    writer.writerow(['username', 'router_name', 'notes'])
    writer.writerow(['customer1', 'Office Router 1', 'Optional notes'])
    writer.writerow(['customer2', 'Office Router 2', ''])
    
    return response


@login_required
@isp_required
def test_router_connection(request, config_id):
    """Test connection to router config"""
    tenant = request.user.tenant
    
    try:
        router_config = RouterConfig.objects.get(id=config_id, tenant=tenant)
    except RouterConfig.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Router configuration not found'})
    
    # Simulate connection test (implement real test logic)
    import socket
    import time
    
    try:
        # Try to connect to router
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        result = sock.connect_ex((router_config.ip_address, router_config.web_port))
        sock.close()
        
        if result == 0:
            router_config.is_online = True
            router_config.last_checked = timezone.now()
            router_config.save()
            
            return JsonResponse({
                'success': True,
                'message': f'Router "{router_config.name}" is online and reachable',
                'status': 'online'
            })
        else:
            router_config.is_online = False
            router_config.save()
            
            return JsonResponse({
                'success': False,
                'message': f'Cannot connect to router "{router_config.name}"',
                'status': 'offline'
            })
            
    except Exception as e:
        router_config.is_online = False
        router_config.save()
        
        return JsonResponse({
            'success': False,
            'message': f'Connection test failed: {str(e)}',
            'status': 'error'
        })
    
@login_required
@isp_required
def bulk_assignment(request):
    """Bulk assign routers from CSV/Excel file"""
    tenant = request.user.tenant
    
    # Get stats
    available_routers = RouterConfig.objects.filter(
        tenant=tenant,
        is_available=True
    ).count()
    
    customers_without_routers = CustomUser.objects.filter(
        tenant=tenant,
        role='customer',
        is_active=True
    ).exclude(
        id__in=RouterConfig.objects.filter(
            tenant=tenant,
            assigned_to__isnull=False
        ).values_list('assigned_to_id', flat=True)
    ).count()
    
    if request.method == 'POST':
        form = BulkAssignmentForm(request.POST, request.FILES)
        if form.is_valid():
            # ... your existing processing code ...
            
            return redirect('bulk_assignment_results')
    else:
        form = BulkAssignmentForm()
    
    # Get sample data
    sample_data = [
        {'username': 'john_doe', 'router_name': 'Office Router 1', 'notes': 'Assigned for new office'},
        {'username': 'jane_smith', 'router_name': 'Home Router 2', 'notes': ''},
        {'username': 'bob_wilson', 'router_name': 'Branch Router 3', 'notes': 'Remote worker'},
    ]
    
    context = {
        'tenant': tenant,
        'form': form,
        'sample_data': sample_data,
        'available_routers': available_routers,
        'customers_without': customers_without_routers,
        'page_title': 'Bulk Router Assignment',
        'page_subtitle': 'Assign routers to multiple customers via CSV/Excel',
    }
    
    return render(request, 'router/bulk_assignment.html', context)