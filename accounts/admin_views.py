from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render
from django.utils import timezone
from django.db.models import Count, Sum, Avg, Q
from django.db.models.functions import TruncDay, TruncMonth, TruncYear
from accounts.models import CustomUser, LoginHistory, UserSession
from billing.models import  Payment, SubscriptionPlan #, Plan
from router_manager.models import Router, ConnectedDevice
import json
from datetime import datetime, timedelta

@staff_member_required
def superadmin_dashboard(request):
    # Date ranges
    today = timezone.now().date()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)
    year_ago = today - timedelta(days=365)
    
    # User Statistics
    total_users = CustomUser.objects.count()
    new_users_today = CustomUser.objects.filter(date_joined__date=today).count()
    new_users_week = CustomUser.objects.filter(date_joined__date__gte=week_ago).count()
    active_users = UserSession.objects.filter(
        last_activity__gte=timezone.now() - timedelta(days=1)
    ).values('user').distinct().count()
    
    # Billing Statistics
    total_revenue = Payment.objects.filter(status='success').aggregate(Sum('amount'))['amount__sum'] or 0
    monthly_revenue = Payment.objects.filter(
        status='success',
        created_at__date__gte=month_ago
    ).aggregate(Sum('amount'))['amount__sum'] or 0
    pending_payments = Payment.objects.filter(status='pending').count()
    
    # Router Statistics
    total_routers = Router.objects.count()
    online_routers = Router.objects.filter(is_online=True).count()
    total_devices = ConnectedDevice.objects.count()
    online_devices = ConnectedDevice.objects.filter(
        last_seen__gte=timezone.now() - timedelta(minutes=5)
    ).count()
    
    # Plan Distribution Data for Pie Chart
    plan_distribution = SubscriptionPlan.objects.filter(is_active=True).values(
        'plan__name'
    ).annotate(
        count=Count('id')
    ).order_by('-count')
    
    plan_labels = [item['plan__name'] for item in plan_distribution]
    plan_data = [item['count'] for item in plan_distribution]
    
    # User Growth Data for Line Chart
    user_growth = CustomUser.objects.filter(
        date_joined__date__gte=year_ago
    ).annotate(
        month=TruncMonth('date_joined')
    ).values('month').annotate(
        count=Count('id')
    ).order_by('month')
    
    growth_labels = [item['month'].strftime('%b %Y') for item in user_growth]
    growth_data = [item['count'] for item in user_growth]
    
    # Revenue Data for Bar Chart
    revenue_data = Payment.objects.filter(
        status='success',
        created_at__date__gte=month_ago
    ).annotate(
        day=TruncDay('created_at')
    ).values('day').annotate(
        total=Sum('amount')
    ).order_by('day')
    
    revenue_labels = [item['day'].strftime('%d %b') for item in revenue_data]
    revenue_values = [float(item['total']) for item in revenue_data]
    
    # Device Type Distribution
    device_types = ConnectedDevice.objects.values(
        'device_type'
    ).annotate(
        count=Count('id')
    ).order_by('-count')
    
    device_labels = [dict(ConnectedDevice.DEVICE_TYPES).get(item['device_type'], item['device_type']) for item in device_types]
    device_data = [item['count'] for item in device_types]
    
    # Account Type Distribution
    account_types = CustomUser.objects.values(
        'account_type'
    ).annotate(
        count=Count('id')
    ).order_by('-count')
    
    account_labels = [dict(CustomUser.COMPANY_ACCOUNT_TYPES).get(item['account_type'], item['account_type']) for item in account_types]
    account_data = [item['count'] for item in account_types]
    
    # Login Activity (Success vs Failed)
    login_activity = LoginHistory.objects.filter(
        timestamp__date__gte=week_ago
    ).values('success').annotate(
        count=Count('id')
    )
    
    login_success = next((item['count'] for item in login_activity if item['success']), 0)
    login_failed = next((item['count'] for item in login_activity if not item['success']), 0)
    
    # Recent Activities
    recent_payments = Payment.objects.select_related('user', 'plan').order_by('-created_at')[:10]
    recent_logins = LoginHistory.objects.select_related('user').filter(success=True).order_by('-timestamp')[:10]
    
    context = {
        'total_users': total_users,
        'new_users_today': new_users_today,
        'new_users_week': new_users_week,
        'active_users': active_users,
        'total_revenue': total_revenue,
        'monthly_revenue': monthly_revenue,
        'pending_payments': pending_payments,
        'total_routers': total_routers,
        'online_routers': online_routers,
        'total_devices': total_devices,
        'online_devices': online_devices,
        
        # Chart Data as JSON
        'plan_distribution': {
            'labels': json.dumps(plan_labels),
            'data': json.dumps(plan_data),
        },
        'user_growth': {
            'labels': json.dumps(growth_labels),
            'data': json.dumps(growth_data),
        },
        'revenue_data': {
            'labels': json.dumps(revenue_labels),
            'data': json.dumps(revenue_values),
        },
        'device_distribution': {
            'labels': json.dumps(device_labels),
            'data': json.dumps(device_data),
        },
        'account_distribution': {
            'labels': json.dumps(account_labels),
            'data': json.dumps(account_data),
        },
        'login_activity': {
            'success': login_success,
            'failed': login_failed,
        },
        
        'recent_payments': recent_payments,
        'recent_logins': recent_logins,
    }
    
    return render(request, 'admin/superadmin_dashboard.html', context)

@staff_member_required
def analytics_detail(request, chart_type):
    # Detailed analytics for each chart type
    today = timezone.now().date()
    month_ago = today - timedelta(days=30)
    
    if chart_type == 'users':
        # User analytics detail
        users_by_day = CustomUser.objects.filter(
            date_joined__date__gte=month_ago
        ).annotate(
            day=TruncDay('date_joined')
        ).values('day').annotate(
            count=Count('id')
        ).order_by('day')
        
        data = {
            'labels': [item['day'].strftime('%d %b') for item in users_by_day],
            'data': [item['count'] for item in users_by_day],
            'title': 'User Registration Trend (30 Days)'
        }
        
    elif chart_type == 'revenue':
        # Revenue analytics detail
        revenue_by_day = Payment.objects.filter(
            status='success',
            created_at__date__gte=month_ago
        ).annotate(
            day=TruncDay('created_at')
        ).values('day').annotate(
            total=Sum('amount')
        ).order_by('day')
        
        data = {
            'labels': [item['day'].strftime('%d %b') for item in revenue_by_day],
            'data': [float(item['total']) for item in revenue_by_day],
            'title': 'Revenue Trend (30 Days)'
        }
        
    elif chart_type == 'devices':
        # Device analytics detail
        devices_by_day = ConnectedDevice.objects.filter(
            first_seen__date__gte=month_ago
        ).annotate(
            day=TruncDay('first_seen')
        ).values('day').annotate(
            count=Count('id')
        ).order_by('day')
        
        data = {
            'labels': [item['day'].strftime('%d %b') for item in devices_by_day],
            'data': [item['count'] for item in devices_by_day],
            'title': 'New Devices Trend (30 Days)'
        }
    
    return render(request, 'admin/analytics_detail.html', {'chart_data': data, 'chart_type': chart_type})