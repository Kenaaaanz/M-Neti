from venv import logger
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, update_session_auth_hash, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, update_session_auth_hash, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from datetime import timedelta
from django_countries import countries
import json
import csv
from django.http import JsonResponse, HttpResponse, HttpResponseForbidden
import logging
from django.views.decorators.http import require_POST, require_http_methods
from django.conf import settings
import requests
from .models import CustomUser, UserSession, LoginHistory, LoginActivity, Tenant
from .models import SupportConversation, SupportMessage, SupportAttachment
from .forms import (RegistrationForm, UserUpdateForm, AccountPreferencesForm, 
                   BillingAddressForm, UserProfileForm, CustomPasswordChangeForm)
from router_manager.models import Router
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.db.models import Q, Count
from django.core.paginator import Paginator


# Import billing models with proper error handling
try:
    from billing.models import Payment, SubscriptionPlan, Subscription
    BILLING_ENABLED = True
except ImportError:
    BILLING_ENABLED = False
    print("Billing app not available - billing features disabled")
    
# Paystack configuration
PAYSTACK_SECRET_KEY = getattr(settings, 'PAYSTACK_SECRET_KEY', 'your_paystack_secret_key_here')
PAYSTACK_PUBLIC_KEY = getattr(settings, 'PAYSTACK_PUBLIC_KEY', 'your_paystack_public_key_here')

def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard_router')
    
    tenant = getattr(request, 'tenant', None)
    
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        user = authenticate(request, username=username, password=password)
        
        if user is not None:

            # Check if user is approved
            if user.registration_status != 'approved':
                messages.error(request, 
                    'Your account is pending approval. Please wait for the ISP administrator to approve your registration.'
                )
                # Log the failed login attempt due to pending approval
                try:
                    LoginActivity.objects.create(
                        tenant=user.tenant if user.tenant else None,
                        user=user,
                        ip_address=get_client_ip(request),
                        user_agent=request.META.get('HTTP_USER_AGENT', ''),
                        status='failed',
                        reason='Pending approval'
                    )
                except Exception:
                    pass
                return render(request, 'accounts/login.html', {'tenant': tenant})
            
            if tenant and getattr(user, 'tenant', None) != tenant and not user.is_superuser:
                try:
                    LoginActivity.objects.create(
                        tenant=tenant,
                        user=user,
                        ip_address=get_client_ip(request),
                        user_agent=request.META.get('HTTP_USER_AGENT', ''),
                        status='failed'
                    )
                except Exception:
                    pass
                messages.error(request, 'This account does not belong to the current tenant domain.')
                context = {'tenant': tenant}
                return render(request, 'accounts/login.html', context)
            
            # Log login activity
            log_tenant = tenant or getattr(user, 'tenant', None)
            if log_tenant:
                try:
                    LoginActivity.objects.create(
                        tenant=log_tenant,
                        user=user,
                        ip_address=get_client_ip(request),
                        user_agent=request.META.get('HTTP_USER_AGENT', ''),
                        status='success'
                    )
                except Exception:
                    pass
            
            login(request, user)
            return redirect('dashboard_router')
        else:
            # Log failed attempt
            try:
                user = CustomUser.objects.get(username=username)
                LoginActivity.objects.create(
                    tenant=user.tenant if user.tenant else None,
                    user=user,
                    ip_address=get_client_ip(request),
                    user_agent=request.META.get('HTTP_USER_AGENT', ''),
                    status='failed'
                )
            except CustomUser.DoesNotExist:
                pass
            
            messages.error(request, 'Invalid username or password')
    
    context = {'tenant': tenant}
    return render(request, 'accounts/login.html', context)

def logout_view(request):
    logout(request)
    messages.success(request, 'You have been logged out successfully')
    return redirect('login')

@login_required
def dashboard_router(request):
    """Route user to appropriate dashboard"""
    user = request.user
    
    if user.role == 'superadmin':
        return redirect('superadmin_dashboard')
    elif user.role in ['isp_admin', 'isp_staff']:
        return redirect('isp_dashboard')
    elif user.role == 'customer':
        return redirect('dashboard')
    else:
        messages.error(request, 'Unknown user role')
        return redirect('login')
    
def get_client_ip(request):
    """Utility function to get client IP address from request."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

def register(request):
    if request.method == 'POST':
        form = RegistrationForm(request.POST)
        if form.is_valid():
            try:
                user = form.save()
                # Ensure user has a tenant
                if not user.tenant:
                    default_tenant = Tenant.objects.filter(is_active=True).first()
                    if default_tenant:
                        user.tenant = default_tenant
                        user.save()

                messages.success(request, 
                    'Registration submitted successfully! Your account is pending approval from the ISP administrator. '
                    'You will receive an email notification once your account is approved.'
                )
                return redirect('login')
            except Exception as e:
                messages.error(request, f'Registration error: {str(e)}')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = RegistrationForm()
    
    context = {
        'registration_form': form,
        'tenants': Tenant.objects.filter(is_active=True),
    }
    return render(request, 'accounts/register.html', context)

@login_required
def dashboard(request):
    user = request.user
    tenant = user.tenant
    
    # Get subscription
    subscription = Subscription.objects.filter(
        user=user,
        is_active=True
    ).select_related('plan').first()
    
    # Get recent payments
    recent_payments = Payment.objects.filter(
        user=user
    ).select_related('plan').order_by('-created_at')[:3]
    
    # Get router
    router = Router.objects.filter(user=user).first()
    
    # Calculate days remaining percentage
    if subscription and subscription.days_remaining and subscription.plan.duration_days:
        days_remaining_percentage = (subscription.days_remaining / subscription.plan.duration_days) * 100
    else:
        days_remaining_percentage = 0
    
    context = {
        'user': user,
        'tenant': tenant,
        'subscription': subscription,
        'recent_payments': recent_payments,
        'router': router,
        'subscription': {
            'days_remaining': subscription.days_remaining if subscription else 0,
            'days_remaining_percentage': days_remaining_percentage,
            'plan': subscription.plan if subscription else None,
            'start_date': subscription.start_date if subscription else None,
            'end_date': subscription.end_date if subscription else None,
        }
    }
    
    return render(request, 'accounts/dashboard.html', context)


@login_required
def profile(request):
    user = request.user

    # Check if user is approved
    if user.registration_status != 'approved':
        messages.warning(request, 
            'Your account is pending approval. You will have full access once the ISP administrator approves your registration.'
        )
        # Don't show billing/plan features to unapproved users
        BILLING_ENABLED_CONTEXT = False
    else:
        BILLING_ENABLED_CONTEXT = BILLING_ENABLED
    
    # Initialize billing variables
    active_subscription = None
    payment_history = []
    available_plans = []
    
    # Determine tenant context
    tenant = getattr(request, 'tenant', None) or getattr(user, 'tenant', None)

    # Get billing data only if billing app is available and user is approved
    if BILLING_ENABLED and user.registration_status == 'approved':
        try:
            # FIXED: Use date-based filtering instead of is_active field
            from django.utils import timezone
            now = timezone.now()
            active_subscription = Subscription.objects.filter(
                user=user,
                start_date__lte=now,
                end_date__gte=now
            ).select_related('plan').first()
        except Exception as e:
            print(f"Error getting subscription: {e}")
            active_subscription = None
        
        try:
            payment_history = Payment.objects.filter(user=user).select_related('plan').order_by('-created_at')[:10]
        except Exception as e:
            print(f"Error getting payment history: {e}")
            payment_history = []
        
        try:
            if tenant:
                available_plans = SubscriptionPlan.objects.filter(is_active=True, tenant=tenant).order_by('price')
            else:
                available_plans = SubscriptionPlan.objects.none()
        except Exception as e:
            print(f"Error getting available plans: {e}")
            available_plans = []
    
    # Handle POST requests
    if request.method == 'POST':
        # Handle account deletion
        if 'delete_account' in request.POST:
            user.delete()
            messages.success(request, 'Your account has been deleted successfully.')
            return redirect('home')
        
        # Handle profile update (personal info only)
        elif 'update_profile' in request.POST:
            form = UserProfileForm(request.POST, instance=user)
            if form.is_valid():
                form.save()
                messages.success(request, 'Profile updated successfully!')
                return redirect('profile')
            else:
                messages.error(request, 'Please correct the errors below.')
        
        # Handle password change
        elif 'change_password' in request.POST:
            password_form = CustomPasswordChangeForm(user, request.POST)
            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)
                messages.success(request, 'Password updated successfully!')
                return redirect('profile')
            else:
                for error in password_form.errors.values():
                    messages.error(request, error)
        
        # Handle session revocation
        elif 'revoke_session' in request.POST:
            session_key = request.POST.get('session_key')
            if session_key:
                try:
                    session = UserSession.objects.get(session_key=session_key, user=request.user)
                    session.is_active = False
                    session.save()
                    messages.success(request, 'Session revoked successfully.')
                except UserSession.DoesNotExist:
                    messages.error(request, 'Session not found.')
            return redirect('profile')
        
        # Handle plan upgrade
        elif 'upgrade_plan' in request.POST and BILLING_ENABLED and user.registration_status == 'approved':
            plan_id = request.POST.get('plan_id')
            if plan_id:
                try:
                    plan = SubscriptionPlan.objects.get(id=plan_id, is_active=True, tenant=tenant)
                    return redirect('paystack_subscribe_with_plan', plan_id=plan_id)
                except SubscriptionPlan.DoesNotExist:
                    messages.error(request, 'Selected plan not found.')
                except Exception as e:
                    messages.error(request, f'Error processing plan upgrade: {str(e)}')
            else:
                messages.error(request, 'Invalid plan selected.')

    # Initialize forms for GET requests or failed POST requests
    form = UserProfileForm(instance=user)
    password_form = CustomPasswordChangeForm(user)
    
    # Get active sessions
    active_sessions = UserSession.objects.filter(user=user, is_active=True).order_by('-last_activity')
    
    context = {
        'form': form,
        'password_form': password_form,
        'active_sessions': active_sessions,
        'active_subscription': active_subscription,
        'payment_history': payment_history,
        'available_plans': available_plans,
        'countries': list(countries),
        'billing_enabled': BILLING_ENABLED_CONTEXT,
    }
    
    return render(request, 'accounts/profile.html', context)

    
@login_required
def change_password(request):
    if request.method == 'POST':
        form = CustomPasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            form.save()
            update_session_auth_hash(request, request.user)
            messages.success(request, 'Your password has been changed successfully!')
            return redirect('profile')
    else:
        form = CustomPasswordChangeForm(request.user)
    return render(request, 'accounts/change_password.html', {'form': form})

@login_required
def update_notifications(request):
    user = request.user
    if request.method == 'POST':
        user.email_notifications = 'email_notifications' in request.POST
        user.sms_notifications = 'sms_notifications' in request.POST
        user.billing_reminders = 'billing_reminders' in request.POST
        user.service_updates = 'service_updates' in request.POST
        user.promotional_offers = 'promotional_offers' in request.POST
        user.save()
        messages.success(request, 'Notification preferences updated!')
    return redirect('profile')

@login_required
def update_billing_address(request):
    """
    Handle billing address updates
    """
    user = request.user
    
    try:
        # Get address fields from the request
        address = request.POST.get('address', '').strip()
        city = request.POST.get('city', '').strip()
        state = request.POST.get('state', '').strip()
        zip_code = request.POST.get('zip_code', '').strip()
        country = request.POST.get('country', '').strip()
        
        # Update user address fields
        if address:
            user.address = address
        if city:
            user.city = city
        if state:
            user.state = state
        if zip_code:
            user.zip_code = zip_code
        if country:
            user.country = country
        
        # Save the user object
        user.save()
        
        # Check if it's an AJAX request
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'status': 'success',
                'message': 'Billing address updated successfully!',
                'billing_address': {
                    'address': user.address,
                    'city': user.city,
                    'state': user.state,
                    'zip_code': user.zip_code,
                    'country': str(user.country) if user.country else ''
                }
            })
        else:
            messages.success(request, 'Billing address updated successfully!')
            return redirect('profile')
            
    except Exception as e:
        error_message = f'Error updating billing address: {str(e)}'
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'status': 'error',
                'message': error_message
            }, status=400)
        else:
            messages.error(request, error_message)
            return redirect('profile')
        
@login_required
@require_POST
def enable_2fa(request):
    """
    Enable two-factor authentication
    """
    user = request.user
    
    try:
        # In a real implementation, you would integrate with a 2FA library like django-otp
        # For now, we'll just update the flag
        user.two_factor_enabled = True
        user.save()
        
        messages.success(request, 'Two-factor authentication has been enabled successfully!')
        
        # Check if it's an AJAX request
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'status': 'success',
                'message': 'Two-factor authentication enabled successfully!',
                'two_factor_enabled': True
            })
            
    except Exception as e:
        error_message = f'Error enabling two-factor authentication: {str(e)}'
        messages.error(request, error_message)
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'status': 'error',
                'message': error_message
            }, status=400)
    
    return redirect('profile')

@login_required
@require_POST
def disable_2fa(request):
    """
    Disable two-factor authentication
    """
    user = request.user
    
    try:
        user.two_factor_enabled = False
        user.save()
        
        messages.success(request, 'Two-factor authentication has been disabled.')
        
        # Check if it's an AJAX request
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'status': 'success',
                'message': 'Two-factor authentication disabled successfully!',
                'two_factor_enabled': False
            })
            
    except Exception as e:
        error_message = f'Error disabling two-factor authentication: {str(e)}'
        messages.error(request, error_message)
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'status': 'error',
                'message': error_message
            }, status=400)
    
    return redirect('profile')


@login_required
def export_data(request):
    """
    Export user data in JSON or CSV format
    """
    user = request.user
    format_type = request.GET.get('format', 'json')
    
    try:
        # Prepare user data for export
        user_data = {
            'profile': {
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'company_account_number': user.company_account_number,
                'phone': str(user.phone) if user.phone else None,
                'address': user.address,
                'city': user.city,
                'state': user.state,
                'country': str(user.country) if user.country else None,
                'zip_code': user.zip_code,
                'account_type': user.account_type,
                'date_joined': user.date_joined.isoformat(),
            },
            'preferences': {
                'language': user.language,
                'timezone': user.timezone,
                'date_format': user.date_format,
                'dark_mode': user.dark_mode,
                'email_notifications': user.email_notifications,
                'sms_notifications': user.sms_notifications,
                'billing_reminders': user.billing_reminders,
                'service_updates': user.service_updates,
                'promotional_offers': user.promotional_offers,
            },
            'security': {
                'two_factor_enabled': user.two_factor_enabled,
                'last_password_change': user.last_password_change.isoformat(),
            }
        }
        
        # Add sessions data
        sessions = UserSession.objects.filter(user=user)
        user_data['sessions'] = [
            {
                'device_type': session.device_type,
                'ip_address': str(session.ip_address),
                'location': session.location,
                'last_activity': session.last_activity.isoformat(),
                'is_active': session.is_active,
            }
            for session in sessions
        ]
        
        # Add billing data if available
        if BILLING_ENABLED:
            try:
                subscriptions = SubscriptionPlan.objects.filter(user=user)
                payments = Payment.objects.filter(user=user)
                
                user_data['billing'] = {
                    'subscriptions': [
                        {
                            'plan': sub.plan.name,
                            'start_date': sub.start_date.isoformat(),
                            'end_date': sub.end_date.isoformat(),
                            'is_active': sub.is_active,
                            'auto_renew': sub.auto_renew,
                        }
                        for sub in subscriptions
                    ],
                    'payments': [
                        {
                            'plan': payment.plan.name,
                            'amount': float(payment.amount),
                            'reference': payment.reference,
                            'status': payment.status,
                            'created_at': payment.created_at.isoformat(),
                        }
                        for payment in payments
                    ]
                }
            except Exception as e:
                user_data['billing'] = {'error': str(e)}
        
        if format_type == 'csv':
            # Create CSV response
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="{user.username}_data_export.csv"'
            
            writer = csv.writer(response)
            
            # Write profile data
            writer.writerow(['Section', 'Field', 'Value'])
            for section, data in user_data.items():
                if isinstance(data, dict):
                    for key, value in data.items():
                        if isinstance(value, (list, dict)):
                            writer.writerow([section, key, json.dumps(value, default=str)])
                        else:
                            writer.writerow([section, key, str(value)])
            
            return response
        
        else:
            # Default to JSON
            response = JsonResponse(user_data, json_dumps_params={'indent': 2})
            response['Content-Disposition'] = f'attachment; filename="{user.username}_data_export.json"'
            return response
            
    except Exception as e:
        messages.error(request, f'Error exporting data: {str(e)}')
        return redirect('profile')
    
# Add these to your views.py if they're missing

@login_required
def update_notifications(request):
    """Update notification preferences"""
    user = request.user
    if request.method == 'POST':
        user.email_notifications = 'email_notifications' in request.POST
        user.sms_notifications = 'sms_notifications' in request.POST
        user.billing_reminders = 'billing_reminders' in request.POST
        user.service_updates = 'service_updates' in request.POST
        user.promotional_offers = 'promotional_offers' in request.POST
        user.save()
        messages.success(request, 'Notification preferences updated!')
    return redirect('profile')

@login_required
@require_POST
def update_preferences(request):
    """Update user preferences"""
    user = request.user
    try:
        if 'language' in request.POST:
            user.language = request.POST.get('language')
        if 'timezone' in request.POST:
            user.timezone = request.POST.get('timezone')
        if 'date_format' in request.POST:
            user.date_format = request.POST.get('date_format')
        
        user.dark_mode = 'dark_mode' in request.POST
        user.save()
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'status': 'success', 'message': 'Preferences updated successfully!'})
        else:
            messages.success(request, 'Preferences updated successfully!')
            return redirect('profile')
    except Exception as e:
        error_message = f'Error updating preferences: {str(e)}'
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'status': 'error', 'message': error_message}, status=400)
        else:
            messages.error(request, error_message)
            return redirect('profile')
        
@login_required
@require_http_methods(["POST"])
def revoke_session(request, session_id):
    """
    Revoke a specific user session
    """
    user = request.user
    
    try:
        # Get the session to revoke
        session = get_object_or_404(UserSession, id=session_id, user=user)
        
        # Don't allow revoking the current session
        if session.session_key == request.session.session_key:
            messages.error(request, 'Cannot revoke your current active session.')
            return redirect('profile')
        
        # Revoke the session
        session.is_active = False
        session.save()
        
        messages.success(request, 'Session revoked successfully.')
        
    except Exception as e:
        messages.error(request, f'Error revoking session: {str(e)}')
    
    return redirect('profile')
    
@login_required
def plan_selection(request):
    if not BILLING_ENABLED:
        messages.error(request, 'Billing features are not available.')
        return redirect('dashboard')
    
    user = request.user
    
    # Check if user is approved
    if user.registration_status != 'approved':
        messages.warning(request, 'Your account is pending approval.')
        return redirect('dashboard')
    
    tenant = getattr(user, 'tenant', None)
    
    if not tenant:
        messages.error(request, 'No ISP assigned to your account.')
        return redirect('dashboard')
    
    # Get plans for the user's tenant
    plans = SubscriptionPlan.objects.filter(tenant=tenant, is_active=True).order_by('price')
    
    # Get current subscription
    current_subscription = None
    if BILLING_ENABLED:
        try:
            current_subscription = Subscription.objects.filter(
                user=user, 
                is_active=True
            ).select_related('plan').first()
        except Exception as e:
            print(f"Error getting subscription: {e}")
    
    context = {
        'plans': plans,
        'current_subscription': current_subscription,
        'tenant': tenant,
    }
    
    return render(request, 'accounts/plan_selection.html', context)

    
@login_required
def paystack_subscribe(request):
    """Handle general subscription (no specific plan)"""
    if not BILLING_ENABLED:
        messages.error(request, 'Billing is not enabled on this system.')
        return redirect('profile')
    
    # Redirect to plan selection where they can choose a plan
    messages.info(request, 'Please select a specific plan to subscribe.')
    return redirect('plan_selection')

@login_required
def paystack_subscribe_with_plan(request, plan_id):
    """Handle subscription with specific SubscriptionPlan - Fixed version"""
    if not BILLING_ENABLED:
        messages.error(request, 'Billing is not enabled on this system.')
        return redirect('profile')
    
    try:
        user = request.user
        tenant = getattr(request, 'tenant', None) or getattr(user, 'tenant', None)
        
        if not tenant:
            messages.error(request, 'No tenant associated with your account.')
            return redirect('plan_selection')
        
        # Get plan for current tenant
        plan = get_object_or_404(
            SubscriptionPlan, 
            id=plan_id, 
            tenant=tenant,
            is_active=True
        )
        # Generate unique reference
        import uuid
        reference = f"sub_{request.user.id}_{uuid.uuid4().hex[:8]}"
        
        # Create payment record
        payment = Payment.objects.create(
            user=request.user,
            plan=plan,  # This should be a SubscriptionPlan foreign key
            amount=plan.price,
            reference=reference,
            status='pending'
        )
        
        # Paystack configuration
        PAYSTACK_SECRET_KEY = getattr(settings, 'PAYSTACK_SECRET_KEY', 'your_secret_key_here')
        
        # Paystack payment data
        paystack_data = {
            'email': request.user.email,
            'amount': int(plan.price * 100),  # Convert to kobo
            'reference': reference,
            'callback_url': request.build_absolute_uri(f'/accounts/paystack/verify/{reference}/'),
            'metadata': {
                'user_id': request.user.id,
                'plan_id': plan.id,
                'payment_id': payment.id,
                'custom_fields': [
                    {
                        'display_name': "Plan Name",
                        'variable_name': "plan_name", 
                        'value': plan.name
                    },
                    {
                        'display_name': "Customer Name", 
                        'variable_name': "customer_name",
                        'value': f"{request.user.first_name} {request.user.last_name}"
                    }
                ]
            }
        }
        
        # Initialize Paystack transaction
        headers = {
            'Authorization': f'Bearer {PAYSTACK_SECRET_KEY}',
            'Content-Type': 'application/json',
        }
        
        import requests
        response = requests.post(
            'https://api.paystack.co/transaction/initialize',
            json=paystack_data,
            headers=headers,
            timeout=30  # 30 second timeout
        )
        
        if response.status_code == 200:
            data = response.json()
            if data['status']:
                # Success - redirect to Paystack payment page
                authorization_url = data['data']['authorization_url']
                messages.success(request, f'Redirecting to Paystack for {plan.name} subscription...')
                return redirect(authorization_url)
            else:
                # Paystack API returned error
                error_message = data.get('message', 'Unknown Paystack error')
                payment.status = 'failed'
                payment.save()
                messages.error(request, f'Paystack error: {error_message}')
        else:
            # HTTP error
            payment.status = 'failed'
            payment.save()
            messages.error(request, f'Unable to connect to Paystack. Please try again.')
            
    except SubscriptionPlan.DoesNotExist:
        messages.error(request, 'Selected plan not found or is no longer available.')
    except requests.exceptions.RequestException as e:
        # Network-related errors
        messages.error(request, 'Network error. Please check your connection and try again.')
        print(f"Paystack network error: {e}")
    except Exception as e:
        # Any other unexpected errors
        messages.error(request, 'An unexpected error occurred. Please try again.')
        print(f"Paystack subscription error: {e}")
    
    return redirect('plan_selection')

@login_required
def paystack_verify_payment(request, reference):
    """Verify Paystack payment and activate subscription - Fixed for SubscriptionPlan"""
    if not BILLING_ENABLED:
        messages.error(request, 'Billing is not enabled on this system.')
        return redirect('profile')
    
    try:
        # Get the payment record
        payment = get_object_or_404(Payment, reference=reference, user=request.user)
        
        # Skip if already processed
        if payment.status == 'success':
            messages.info(request, 'Payment already processed successfully.')
            return redirect('dashboard')
        
        # Verify payment with Paystack
        PAYSTACK_SECRET_KEY = getattr(settings, 'PAYSTACK_SECRET_KEY', 'your_secret_key_here')
        
        headers = {
            'Authorization': f'Bearer {PAYSTACK_SECRET_KEY}',
            'Content-Type': 'application/json',
        }
        
        import requests
        response = requests.get(
            f'https://api.paystack.co/transaction/verify/{reference}',
            headers=headers,
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            
            if data['status'] and data['data']['status'] == 'success':
                # Payment successful
                payment_data = data['data']
                
                # Update payment record
                payment.status = 'success'
                payment.paystack_reference = payment_data.get('id', '')
                if payment_data.get('paid_at'):
                    payment.transaction_date = payment_data['paid_at']
                payment.save()
                
                # Get the SubscriptionPlan from the payment
                plan = payment.plan
                
                # Deactivate any existing subscriptions
                Subscription.objects.filter(user=request.user, is_active=True).update(is_active=False)
                
                # Create new subscription using Subscription model
                subscription = Subscription.objects.create(
                    user=request.user,
                    plan=plan,
                    start_date=timezone.now(),
                    end_date=timezone.now() + timedelta(days=plan.duration_days),
                    is_active=True
                )
                
                messages.success(request, f'Successfully subscribed to {plan.name}! Your subscription is now active.')
                return redirect('dashboard')
            
            else:
                # Payment failed or pending
                payment.status = 'failed'
                payment.save()
                
                error_message = data['data'].get('gateway_response', 'Payment failed')
                messages.error(request, f'Payment failed: {error_message}')
                
        else:
            # HTTP error during verification
            messages.error(request, 'Error verifying payment with Paystack. Please contact support.')
            
    except Payment.DoesNotExist:
        messages.error(request, 'Payment record not found.')
    except requests.exceptions.RequestException as e:
        messages.error(request, 'Network error during payment verification. Please check your subscription status.')
        print(f"Paystack verification network error: {e}")
    except Exception as e:
        messages.error(request, 'An unexpected error occurred during payment verification.')
        print(f"Paystack verification error: {e}")
    
    return redirect('plan_selection')

@login_required
def initiate_paystack_payment(request, plan_id):
    """
    AJAX endpoint to initiate Paystack payment (for JavaScript integration) - Fixed
    """
    if not BILLING_ENABLED:
        return JsonResponse({
            'status': 'error',
            'message': 'Billing is not enabled on this system.'
        })
    
    if request.method == 'POST':
        try:
            user = request.user
            tenant = getattr(request, 'tenant', None) or getattr(user, 'tenant', None)

            if not tenant:
                return JsonResponse({
                    'status': 'error',
                    'message': 'No tenant associated with your account.'
                })
            
            plan = get_object_or_404(SubscriptionPlan, id=plan_id, is_active=True, tenant=tenant)

            # Generate unique reference
            import uuid
            reference = f"sub_{request.user.id}_{uuid.uuid4().hex[:8]}"
            
            # Create payment record
            payment = Payment.objects.create(
                user=user,
                plan=plan,
                amount=plan.price,
                reference=reference,
                status='pending'
            )
            
            # Paystack payment data
            paystack_data = {
                'email': request.user.email,
                'amount': int(plan.price * 100),  # Convert to kobo
                'reference': reference,
                'callback_url': request.build_absolute_uri(f'/accounts/paystack/verify/{reference}/'),
                'metadata': {
                    'user_id': request.user.id,
                    'plan_id': plan.id,
                    'payment_id': payment.id,
                    'tenant_id': str(tenant.id) if tenant else None,
                }
            }
            
            # Initialize Paystack transaction
            headers = {
                'Authorization': f'Bearer {PAYSTACK_SECRET_KEY}',
                'Content-Type': 'application/json',
            }
            
            response = requests.post(
                'https://api.paystack.co/transaction/initialize',
                json=paystack_data,
                headers=headers
            )
            
            if response.status_code == 200:
                data = response.json()
                if data['status']:
                    return JsonResponse({
                        'status': 'success',
                        'payment_url': data['data']['authorization_url'],
                        'reference': reference
                    })
                else:
                    return JsonResponse({
                        'status': 'error',
                        'message': 'Failed to initialize payment with Paystack.'
                    })
            else:
                return JsonResponse({
                    'status': 'error',
                    'message': 'Error connecting to Paystack.'
                })
                
        except SubscriptionPlan.DoesNotExist:
            return JsonResponse({
                'status': 'error',
                'message': 'Selected plan not found.'
            })
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': f'Error processing payment: {str(e)}'
            })
    
    return JsonResponse({
        'status': 'error',
        'message': 'Invalid request method.'
    })

@login_required
@require_http_methods(["GET", "POST"])
def delete_account(request):
    """
    Handle account deletion with confirmation
    """
    user = request.user
    
    if request.method == 'POST':
        try:
            # Double-check confirmation
            confirmation = request.POST.get('confirmation', '')
            if confirmation != 'DELETE MY ACCOUNT':
                messages.error(request, 'Please type "DELETE MY ACCOUNT" to confirm deletion.')
                return redirect('profile')
            
            # Log out the user before deleting account
            from django.contrib.auth import logout
            logout(request)
            
            # Delete the user account
            user.delete()
            
            messages.success(request, 'Your account has been permanently deleted. We hope to see you again!')
            return redirect('home')
            
        except Exception as e:
            messages.error(request, f'Error deleting account: {str(e)}')
            return redirect('profile')
    
    # GET request - show confirmation page
    return render(request, 'accounts/delete_account_confirm.html', {
        'user': user
    })

@login_required
def support_chat(request):
    """Modern support chat interface for customers"""
    user = request.user
    tenant = getattr(user, 'tenant', None)
    
    # Get conversations for this user
    conversations = SupportConversation.objects.filter(
        user=user
    ).order_by('-last_message_at')
    
    # Get active conversation
    conversation_id = request.GET.get('conversation')
    active_conversation = None
    messages_list = []
    
    if conversation_id:
        try:
            active_conversation = SupportConversation.objects.get(
                id=conversation_id,
                customer=user
            )
            # Mark as read by customer
            if user.role == 'customer':
                active_conversation.is_read_by_customer = True
                active_conversation.save()
            
            # Get messages for this conversation
            messages_list = SupportMessage.objects.filter(
                conversation=active_conversation
            ).select_related('sender').order_by('created_at')
            
        except SupportConversation.DoesNotExist:
            messages.error(request, 'Conversation not found')
    
    context = {
        'conversations': conversations,
        'active_conversation': active_conversation,
        'messages': messages_list,
        'tenant': tenant,
        'page_title': 'Support Chat',
        'page_subtitle': 'Get help from our support team',
    }
    
    return render(request, 'accounts/support_chat.html', context)

@login_required
def support_operator_dashboard(request):
    """Operator dashboard for ISP staff"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    # Get filter parameters
    status_filter = request.GET.get('status', 'open')
    priority_filter = request.GET.get('priority', 'all')
    assigned_filter = request.GET.get('assigned', 'all')
    
    # Base query
    conversations = SupportConversation.objects.filter(
        tenant=tenant
    ).select_related('customer', 'assigned_to')
    
    # Apply filters
    if status_filter != 'all':
        conversations = conversations.filter(status=status_filter)
    
    if priority_filter != 'all':
        conversations = conversations.filter(priority=priority_filter)
    
    if assigned_filter == 'me':
        conversations = conversations.filter(assigned_to=request.user)
    elif assigned_filter == 'unassigned':
        conversations = conversations.filter(assigned_to__isnull=True)
    elif assigned_filter == 'others':
        conversations = conversations.filter(
            assigned_to__isnull=False
        ).exclude(assigned_to=request.user)
    
    # Get statistics
    stats = {
        'total': SupportConversation.objects.filter(tenant=tenant).count(),
        'open': SupportConversation.objects.filter(tenant=tenant, status='open').count(),
        'in_progress': SupportConversation.objects.filter(tenant=tenant, status='in_progress').count(),
        'resolved': SupportConversation.objects.filter(tenant=tenant, status='resolved').count(),
        'assigned_to_me': SupportConversation.objects.filter(
            tenant=tenant, assigned_to=request.user
        ).count(),
        'unassigned': SupportConversation.objects.filter(
            tenant=tenant, assigned_to__isnull=True
        ).count(),
        'unread': SupportConversation.objects.filter(
            tenant=tenant, is_read_by_support=False
        ).count(),
    }
    
    # Recent conversations for quick access
    recent_conversations = conversations.order_by('-last_message_at')[:10]
    
    context = {
        'conversations': recent_conversations,
        'stats': stats,
        'status_filter': status_filter,
        'priority_filter': priority_filter,
        'assigned_filter': assigned_filter,
        'tenant': tenant,
        'page_title': 'Support Dashboard',
        'page_subtitle': 'Manage customer support requests',
    }
    
    return render(request, 'accounts/support_operator_dashboard.html', context)

@login_required
def support_conversation_detail(request, conversation_id):
    """Detailed view of a conversation for operators"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return HttpResponseForbidden("Access denied")
    
    tenant = request.user.tenant
    
    conversation = get_object_or_404(
        SupportConversation,
        id=conversation_id,
        tenant=tenant
    )
    
    # Mark as read by support
    conversation.is_read_by_support = True
    conversation.save()
    
    # Get messages
    messages_list = SupportMessage.objects.filter(
        conversation=conversation
    ).select_related('sender').order_by('created_at')
    
    # Get customer details
    customer = conversation.customer
    
    # Get available operators for assignment
    operators = CustomUser.objects.filter(
        tenant=tenant,
        role__in=['isp_admin', 'isp_staff']
    ).exclude(id=request.user.id)
    
    context = {
        'conversation': conversation,
        'messages': messages_list,
        'customer': customer,
        'operators': operators,
        'tenant': tenant,
        'page_title': f'Support: {conversation.subject}',
        'page_subtitle': f'Conversation with {customer.get_full_name() or customer.username}',
    }
    
    return render(request, 'accounts/support_conversation_detail.html', context)

@login_required
def support_create_conversation(request):
    """Create a new support conversation"""
    if request.user.role != 'customer':
        return HttpResponseForbidden("Only customers can create support conversations")
    
    if request.method == 'POST':
        subject = request.POST.get('subject', '').strip()
        message = request.POST.get('message', '').strip()
        category = request.POST.get('category', 'general')
        priority = request.POST.get('priority', 'medium')
        
        if not subject or not message:
            return JsonResponse({
                'success': False,
                'error': 'Subject and message are required'
            })
        
        try:
            tenant = request.user.tenant
            if not tenant:
                return JsonResponse({
                    'success': False,
                    'error': 'No ISP associated with your account'
                })
            
            # Create conversation
            conversation = SupportConversation.objects.create(
                tenant=tenant,
                customer=request.user,
                subject=subject,
                category=category,
                priority=priority,
                status='open'
            )
            
            # Create first message
            SupportMessage.objects.create(
                conversation=conversation,
                sender=request.user,
                message=message
            )
            
            return JsonResponse({
                'success': True,
                'conversation_id': conversation.id,
                'message': 'Support request created successfully'
            })
            
        except Exception as e:
            logger.error(f"Error creating support conversation: {e}")
            return JsonResponse({
                'success': False,
                'error': 'Failed to create support request'
            })
    
    # GET request - show form
    return render(request, 'accounts/support_create.html', {
        'tenant': request.user.tenant,
        'page_title': 'New Support Request',
        'page_subtitle': 'Describe your issue to get help',
    })

@login_required
def api_support_send_message(request, conversation_id):
    """API endpoint to send a message in a conversation"""
    try:
        data = json.loads(request.body)
        message_text = data.get('message', '').strip()
        
        if not message_text:
            return JsonResponse({
                'success': False,
                'error': 'Message cannot be empty'
            })
        
        # Get conversation
        if request.user.role == 'customer':
            conversation = get_object_or_404(
                SupportConversation,
                id=conversation_id,
                customer=request.user
            )
        else:
            conversation = get_object_or_404(
                SupportConversation,
                id=conversation_id,
                tenant=request.user.tenant
            )
        
        # Update conversation status
        if request.user.role in ['isp_admin', 'isp_staff']:
            conversation.is_read_by_customer = False
            if conversation.status == 'open':
                conversation.status = 'in_progress'
                conversation.assigned_to = request.user
        else:
            conversation.is_read_by_support = False
        
        conversation.save()
        
        # Create message
        message = SupportMessage.objects.create(
            conversation=conversation,
            sender=request.user,
            message=message_text
        )
        
        return JsonResponse({
            'success': True,
            'message_id': message.id,
            'sender_name': request.user.get_full_name() or request.user.username,
            'sender_role': request.user.role,
            'timestamp': message.created_at.isoformat(),
            'conversation_status': conversation.status
        })
        
    except Exception as e:
        logger.error(f"Error sending support message: {e}")
        return JsonResponse({
            'success': False,
            'error': 'Failed to send message'
        })

@login_required
def api_support_get_messages(request, conversation_id):
    """API endpoint to get messages for a conversation"""
    try:
        if request.user.role == 'customer':
            conversation = get_object_or_404(
                SupportConversation,
                id=conversation_id,
                customer=request.user
            )
        else:
            conversation = get_object_or_404(
                SupportConversation,
                id=conversation_id,
                tenant=request.user.tenant
            )
        
        # Mark messages as read
        if request.user.role in ['isp_admin', 'isp_staff']:
            conversation.is_read_by_support = True
        else:
            conversation.is_read_by_customer = True
        conversation.save()
        
        # Get messages
        messages_list = SupportMessage.objects.filter(
            conversation=conversation
        ).select_related('sender').order_by('created_at')
        
        messages_data = []
        for msg in messages_list:
            messages_data.append({
                'id': msg.id,
                'sender_id': msg.sender.id,
                'sender_name': msg.sender.get_full_name() or msg.sender.username,
                'sender_role': msg.sender.role,
                'sender_avatar': f"https://ui-avatars.com/api/?name={msg.sender.username}&background=random",
                'message': msg.message,
                'timestamp': msg.created_at.isoformat(),
                'is_customer': msg.sender.role == 'customer',
                'is_operator': msg.sender.role in ['isp_admin', 'isp_staff']
            })
        
        return JsonResponse({
            'success': True,
            'messages': messages_data,
            'conversation_status': conversation.status,
            'assigned_to': conversation.assigned_to.username if conversation.assigned_to else None
        })
        
    except Exception as e:
        logger.error(f"Error getting support messages: {e}")
        return JsonResponse({
            'success': False,
            'error': 'Failed to load messages'
        })

@login_required
def api_support_update_conversation(request, conversation_id):
    """API endpoint to update conversation details (status, priority, assignment)"""
    if request.user.role not in ['isp_admin', 'isp_staff']:
        return JsonResponse({'success': False, 'error': 'Access denied'})
    
    try:
        data = json.loads(request.body)
        conversation = get_object_or_404(
            SupportConversation,
            id=conversation_id,
            tenant=request.user.tenant
        )
        
        # Update fields
        if 'status' in data:
            conversation.status = data['status']
        
        if 'priority' in data:
            conversation.priority = data['priority']
        
        if 'assigned_to' in data:
            if data['assigned_to']:
                try:
                    assigned_user = CustomUser.objects.get(
                        id=data['assigned_to'],
                        tenant=request.user.tenant,
                        role__in=['isp_admin', 'isp_staff']
                    )
                    conversation.assigned_to = assigned_user
                except CustomUser.DoesNotExist:
                    pass
            else:
                conversation.assigned_to = None
        
        conversation.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Conversation updated successfully',
            'conversation': {
                'id': conversation.id,
                'status': conversation.status,
                'priority': conversation.priority,
                'assigned_to': conversation.assigned_to.username if conversation.assigned_to else None,
                'updated_at': conversation.updated_at.isoformat()
            }
        })
        
    except Exception as e:
        logger.error(f"Error updating conversation: {e}")
        return JsonResponse({
            'success': False,
            'error': 'Failed to update conversation'
        })

@login_required
def api_support_get_conversations(request):
    """API endpoint to get conversations list"""
    try:
        if request.user.role == 'customer':
            conversations = SupportConversation.objects.filter(
                user=request.user
            ).order_by('-last_message_at')
        else:
            conversations = SupportConversation.objects.filter(
                tenant=request.user.tenant
            ).order_by('-last_message_at')
        
        conversations_data = []
        for conv in conversations:
            last_message = conv.messages.last()
            conversations_data.append({
                'id': conv.id,
                'subject': conv.subject,
                'customer_name': conv.customer.get_full_name() or conv.customer.username,
                'status': conv.status,
                'priority': conv.priority,
                'category': conv.category,
                'last_message': last_message.message[:100] + '...' if last_message else '',
                'last_message_at': conv.last_message_at.isoformat(),
                'unread_count': conv.messages.filter(is_read=False).exclude(sender=request.user).count(),
                'is_read': conv.is_read_by_support if request.user.role != 'customer' else conv.is_read_by_customer,
                'assigned_to': conv.assigned_to.username if conv.assigned_to else 'Unassigned'
            })
        
        return JsonResponse({
            'success': True,
            'conversations': conversations_data
        })
        
    except Exception as e:
        logger.error(f"Error getting conversations: {e}")
        return JsonResponse({
            'success': False,
            'error': 'Failed to load conversations'
        })

@login_required
def api_support_get_unread_count(request):
    """API endpoint to get unread message count"""
    try:
        if request.user.role == 'customer':
            unread_count = SupportConversation.objects.filter(
                customer=request.user,
                is_read_by_customer=False
            ).count()
        else:
            unread_count = SupportConversation.objects.filter(
                tenant=request.user.tenant,
                is_read_by_support=False
            ).count()
        
        return JsonResponse({
            'success': True,
            'unread_count': unread_count
        })
        
    except Exception as e:
        logger.error(f"Error getting unread count: {e}")
        return JsonResponse({
            'success': False,
            'unread_count': 0
        })