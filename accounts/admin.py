# accounts/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.urls import reverse, path
from django.utils.html import format_html
from django import forms
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import CustomUser, UserSession, LoginHistory, Tenant, LoginActivity

class TenantAdminForm(forms.ModelForm):
    """Custom form for Tenant admin with color pickers"""
    class Meta:
        model = Tenant
        fields = '__all__'
        widgets = {
            'primary_color': forms.TextInput(attrs={'type': 'color', 'class': 'color-picker'}),
            'secondary_color': forms.TextInput(attrs={'type': 'color', 'class': 'color-picker'}),
            'accent_color': forms.TextInput(attrs={'type': 'color', 'class': 'color-picker'}),
            'light_color': forms.TextInput(attrs={'type': 'color', 'class': 'color-picker'}),
            'dark_color': forms.TextInput(attrs={'type': 'color', 'class': 'color-picker'}),
            'text_color': forms.TextInput(attrs={'type': 'color', 'class': 'color-picker'}),
            'success_color': forms.TextInput(attrs={'type': 'color', 'class': 'color-picker'}),
            'warning_color': forms.TextInput(attrs={'type': 'color', 'class': 'color-picker'}),
            'error_color': forms.TextInput(attrs={'type': 'color', 'class': 'color-picker'}),
            'info_color': forms.TextInput(attrs={'type': 'color', 'class': 'color-picker'}),
        }
    
    def clean_primary_color(self):
        color = self.cleaned_data.get('primary_color')
        if color and not color.startswith('#'):
            return '#' + color
        return color

@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ['name', 'company_name', 'subdomain', 'primary_color_preview', 'is_active', 'is_verified', 'get_admin_count', 'created_at']
    list_filter = ['subscription_plan', 'is_active', 'is_verified', 'created_at']
    search_fields = ['name', 'subdomain', 'company_name', 'contact_email', 'contact_person']
    readonly_fields = ['created_at', 'updated_at', 'verification_date', 'primary_domain', 'dashboard_url', 'get_admin_count_display', 'preview_colors']
    list_editable = ['is_active', 'is_verified']
    actions = ['activate_tenants', 'deactivate_tenants', 'verify_tenants']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'company_name')
        }),
        ('Domain & URLs', {
            'fields': ('subdomain', 'custom_domain')
        }),
        ('Contact Information', {
            'fields': ('contact_email', 'contact_phone', 'contact_person', 'contact_position')
        }),
        ('Brand Colors - Primary Palette', {
            'fields': ('primary_color', 'secondary_color', 'accent_color'),
            'classes': ('collapse', 'color-palette-section'),
        }),
        ('Brand Colors - UI & Text', {
            'fields': ('light_color', 'dark_color', 'text_color'),
            'classes': ('collapse', 'color-palette-section'),
        }),
        ('Brand Colors - Semantic Colors', {
            'fields': ('success_color', 'warning_color', 'error_color', 'info_color'),
            'classes': ('collapse', 'color-palette-section'),
        }),
        ('Brand Assets', {
            'fields': ('logo',)
        }),
        ('ISP Settings', {
            'fields': ('bandwidth_limit', 'client_limit', 'auto_disconnect_enabled')
        }),
        ('Subscription & Verification', {
            'fields': ('subscription_plan', 'subscription_end', 'is_verified', 'verification_date', 'verification_notes')
        }),
        ('Business Information', {
            'fields': ('business_type', 'registration_number', 'tax_id', 'years_in_operation'),
            'classes': ('collapse',),
        }),
        ('Documents', {
            'fields': ('business_registration', 'tax_certificate', 'id_document', 'bank_details'),
            'classes': ('collapse',),
        }),
        ('System Information', {
            'fields': ('primary_domain', 'dashboard_url', 'get_admin_count_display', 'preview_colors')
        }),
        ('Status & Dates', {
            'fields': ('is_active', 'created_at', 'updated_at')
        }),
    )
    
    def primary_color_preview(self, obj):
        if obj.primary_color:
            return format_html(
                '<div style="display: flex; align-items: center; gap: 8px;">'
                '<div style="width: 20px; height: 20px; background-color: {}; border-radius: 3px; border: 1px solid #ccc;"></div>'
                '<span>{}</span>'
                '</div>',
                obj.primary_color, obj.primary_color
            )
        return "-"
    primary_color_preview.short_description = "Primary Color"
    
    def get_admin_count(self, obj):
        return obj.get_admin_count()
    get_admin_count.short_description = "Admins"
    
    def get_admin_count_display(self, obj):
        count = obj.get_admin_count()
        return format_html(
            '<span style="font-weight: bold; color: {};">{} admin(s)</span>',
            obj.primary_color if obj.primary_color else '#3b82f6',
            count
        )
    get_admin_count_display.short_description = "Admin Users"
    
    def preview_colors(self, obj):
        if obj.primary_color and obj.secondary_color:
            return format_html(
                '<div style="display: flex; gap: 4px; margin: 10px 0; flex-wrap: wrap;">'
                '<div style="width: 30px; height: 30px; background-color: {}; border-radius: 4px;" title="Primary: {}"></div>'
                '<div style="width: 30px; height: 30px; background-color: {}; border-radius: 4px;" title="Secondary: {}"></div>'
                '<div style="width: 30px; height: 30px; background-color: {}; border-radius: 4px;" title="Accent: {}"></div>'
                '<div style="width: 30px; height: 30px; background-color: {}; border-radius: 4px;" title="Success: {}"></div>'
                '<div style="width: 30px; height: 30px; background-color: {}; border-radius: 4px;" title="Warning: {}"></div>'
                '<div style="width: 30px; height: 30px; background-color: {}; border-radius: 4px;" title="Error: {}"></div>'
                '</div>'
                '<div style="margin-top: 10px; padding: 8px; background: linear-gradient(135deg, {}, {}); border-radius: 4px; color: white; text-align: center; font-weight: bold;">'
                'Brand Gradient Preview'
                '</div>',
                obj.primary_color, obj.primary_color,
                obj.secondary_color, obj.secondary_color,
                obj.accent_color or '#f59e0b', obj.accent_color or '#f59e0b',
                obj.success_color or '#10b981', obj.success_color or '#10b981',
                obj.warning_color or '#f59e0b', obj.warning_color or '#f59e0b',
                obj.error_color or '#ef4444', obj.error_color or '#ef4444',
                obj.primary_color, obj.secondary_color
            )
        return "Set primary and secondary colors to see preview"
    preview_colors.short_description = "Color Palette Preview"
    
    @admin.action(description="Activate selected tenants")
    def activate_tenants(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} tenant(s) activated successfully.")
    
    @admin.action(description="Deactivate selected tenants")
    def deactivate_tenants(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} tenant(s) deactivated successfully.")
    
    @admin.action(description="Verify selected tenants")
    def verify_tenants(self, request, queryset):
        from django.utils import timezone
        updated = queryset.update(
            is_verified=True,
            verification_date=timezone.now(),
            verification_notes=f"Bulk verified by {request.user.username} on {timezone.now().strftime('%Y-%m-%d %H:%M')}"
        )
        self.message_user(request, f"{updated} tenant(s) verified successfully.")
    
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        # Only show tenants that the user has access to
        if request.user.is_superuser:
            return queryset
        # For ISP users, only show their tenant
        if hasattr(request.user, 'tenant'):
            return queryset.filter(id=request.user.tenant.id)
        return queryset.none()
    
    def has_add_permission(self, request):
        # Only superusers can add tenants
        return request.user.is_superuser
    
    def has_change_permission(self, request, obj=None):
        # Superusers can change all, ISP admins can only change their tenant
        if request.user.is_superuser:
            return True
        if obj and hasattr(request.user, 'tenant'):
            return obj.id == request.user.tenant.id
        return False
    
    def has_delete_permission(self, request, obj=None):
        # Only superusers can delete tenants
        return request.user.is_superuser
    
    class Media:
        css = {
            'all': ('admin/css/tenant_admin.css',)
        }
        js = ('admin/js/tenant_admin.js',)
        
    # Form used in the admin view to create the user
    class CreateISPAdminForm(forms.Form):
        username = forms.CharField(max_length=150, help_text="Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.")
        email = forms.EmailField(required=False, help_text="Optional email address for the ISP admin")
        first_name = forms.CharField(max_length=30, required=False)
        last_name = forms.CharField(max_length=30, required=False)
        phone = forms.CharField(max_length=20, required=False, help_text="Optional phone number")
        company_account_number = forms.CharField(max_length=20, required=False, 
                                               help_text='Optional company account number for the ISP admin')
        password = forms.CharField(
            widget=forms.PasswordInput,
            help_text="<ul>"
                      "<li>Your password can't be too similar to your other personal information.</li>"
                      "<li>Your password must contain at least 8 characters.</li>"
                      "<li>Your password can't be a commonly used password.</li>"
                      "<li>Your password can't be entirely numeric.</li>"
                      "</ul>"
        )
        make_staff = forms.BooleanField(required=False, initial=True, 
                                       help_text='Allow this user to access the Django admin')
        send_welcome_email = forms.BooleanField(required=False, initial=True,
                                               help_text='Send welcome email with login instructions')

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('<uuid:tenant_id>/create-isp-admin/', 
                 self.admin_site.admin_view(self.create_isp_admin_view), 
                 name='accounts_tenant_create_isp_admin'),
            path('<uuid:tenant_id>/branding-preview/', 
                 self.admin_site.admin_view(self.branding_preview_view), 
                 name='accounts_tenant_branding_preview'),
        ]
        return custom_urls + urls

    def create_isp_admin_view(self, request, tenant_id):
        tenant = get_object_or_404(Tenant, pk=tenant_id)

        if request.method == 'POST':
            form = self.CreateISPAdminForm(request.POST)
            if form.is_valid():
                data = form.cleaned_data
                username = data['username']
                email = data.get('email') or ''
                password = data['password']
                make_staff = data.get('make_staff', True)
                send_email = data.get('send_welcome_email', True)

                # Create the user
                if CustomUser.objects.filter(username=username).exists():
                    messages.error(request, f"Username '{username}' already exists.")
                else:
                    # Create the user and set tenant and role
                    user = CustomUser.objects.create_user(
                        username=username, 
                        email=email, 
                        password=password,
                        first_name=data.get('first_name', ''),
                        last_name=data.get('last_name', ''),
                        phone=data.get('phone', '')
                    )
                    user.tenant = tenant
                    user.role = 'isp_admin'
                    user.is_staff = bool(make_staff)
                    user.is_active_customer = True
                    user.registration_status = 'approved'
                    
                    # Optionally set a provided company_account_number
                    ca_num = data.get('company_account_number')
                    if ca_num:
                        if CustomUser.objects.filter(company_account_number=ca_num).exists():
                            messages.error(request, f"Company account number '{ca_num}' is already in use.")
                            user.delete()
                            return redirect(request.path)
                        user.company_account_number = ca_num
                    
                    user.save()
                    
                    # Send welcome email if requested
                    if send_email and email:
                        try:
                            # You would implement send_welcome_email function
                            # send_welcome_email(user, password)
                            pass
                        except Exception as e:
                            messages.warning(request, f"User created but email failed: {str(e)}")
                    
                    messages.success(request, 
                        f"ISP admin '{username}' created for tenant {tenant.name}. "
                        f"<a href='{reverse('admin:accounts_customuser_change', args=[user.id])}'>View user</a>"
                    )
                    return redirect('admin:accounts_tenant_change', tenant.pk)
        else:
            form = self.CreateISPAdminForm()

        context = dict(
            self.admin_site.each_context(request),
            title=f'Create ISP Admin for {tenant.name}',
            form=form,
            tenant=tenant,
            opts=self.model._meta,
        )
        return render(request, 'admin/accounts/create_isp_admin.html', context)
    
    def branding_preview_view(self, request, tenant_id):
        """Preview the tenant's branding"""
        tenant = get_object_or_404(Tenant, pk=tenant_id)
        
        context = dict(
            self.admin_site.each_context(request),
            title=f'Branding Preview - {tenant.name}',
            tenant=tenant,
            opts=self.model._meta,
        )
        return render(request, 'admin/accounts/branding_preview.html', context)

@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = ['username', 'email', 'tenant', 'role', 'is_active_customer', 'registration_status', 'last_payment_date']
    list_filter = ['tenant', 'role', 'is_active_customer', 'is_staff', 'is_superuser', 'registration_status']
    search_fields = ['username', 'email', 'company_account_number', 'first_name', 'last_name']
    list_select_related = ['tenant']
    actions = ['activate_customers', 'deactivate_customers', 'approve_registrations']
    
    fieldsets = UserAdmin.fieldsets + (
        ('m_neti Information', {
            'fields': ('tenant', 'company_account_number', 'phone', 'role', 'registration_status')
        }),
        ('Customer Information', {
            'fields': ('subscription_plan', 'bandwidth_limit', 'data_usage', 'account_balance', 
                      'is_active_customer', 'last_payment_date', 'next_payment_date',
                      'registration_date', 'approval_date', 'approved_by')
        }),
    )
    
    readonly_fields = UserAdmin.readonly_fields + ('registration_date', 'approval_date', 'approved_by')
    
    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if obj:
            readonly.extend(['company_account_number', 'date_joined', 'registration_date'])
        return readonly
    
    @admin.action(description="Activate selected customers")
    def activate_customers(self, request, queryset):
        updated = queryset.update(is_active_customer=True)
        self.message_user(request, f"{updated} customer(s) activated successfully.")
    
    @admin.action(description="Deactivate selected customers")
    def deactivate_customers(self, request, queryset):
        updated = queryset.update(is_active_customer=False)
        self.message_user(request, f"{updated} customer(s) deactivated successfully.")
    
    @admin.action(description="Approve pending registrations")
    def approve_registrations(self, request, queryset):
        from django.utils import timezone
        updated = 0
        for user in queryset.filter(registration_status='pending'):
            user.registration_status = 'approved'
            user.is_active_customer = True
            user.approval_date = timezone.now()
            # approved_by is a ForeignKey to CustomUser; assign the user instance
            user.approved_by = request.user
            user.save()
            updated += 1
        self.message_user(request, f"{updated} registration(s) approved successfully.")

@admin.register(LoginActivity)
class LoginActivityAdmin(admin.ModelAdmin):
    list_display = ['user', 'tenant', 'ip_address', 'status', 'timestamp', 'user_agent_short']
    list_filter = ['status', 'timestamp', 'tenant']
    search_fields = ['user__username', 'ip_address', 'user_agent']
    readonly_fields = ['timestamp']
    date_hierarchy = 'timestamp'
    
    def user_agent_short(self, obj):
        if obj.user_agent:
            if 'Mobile' in obj.user_agent:
                return '📱 Mobile'
            elif 'Tablet' in obj.user_agent:
                return '📱 Tablet'
            elif 'Windows' in obj.user_agent:
                return '💻 Windows'
            elif 'Mac' in obj.user_agent:
                return '💻 Mac'
            elif 'Linux' in obj.user_agent:
                return '💻 Linux'
            return '🌐 Browser'
        return '-'
    user_agent_short.short_description = 'Device'
    
    def has_add_permission(self, request):
        return False

@admin.register(UserSession)
class UserSessionAdmin(admin.ModelAdmin):
    list_display = ('user', 'ip_address', 'device_type', 'last_activity', 'is_active', 'duration')
    list_filter = ('device_type', 'is_active', 'last_activity')
    search_fields = ('user__username', 'ip_address', 'user_agent')
    readonly_fields = ('last_activity', 'session_key')
    
    def duration(self, obj):
        if obj.created_at and obj.last_activity:
            delta = obj.last_activity - obj.created_at
            hours, remainder = divmod(delta.seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            if hours > 0:
                return f"{hours}h {minutes}m"
            return f"{minutes}m {seconds}s"
        return "-"
    duration.short_description = "Session Length"

@admin.register(LoginHistory)
class LoginHistoryAdmin(admin.ModelAdmin):
    list_display = ('user', 'tenant_info', 'ip_address', 'timestamp', 'success', 'reason_short', 'location')
    list_filter = ('success', 'timestamp', 'user__tenant')  # Fixed: use user__tenant instead of tenant
    search_fields = ('user__username', 'ip_address', 'reason', 'user__tenant__name')
    readonly_fields = ('timestamp',)
    date_hierarchy = 'timestamp'
    
    def tenant_info(self, obj):
        if obj.user and obj.user.tenant:
            return obj.user.tenant.name
        return "N/A"
    tenant_info.short_description = "Tenant"
    tenant_info.admin_order_field = 'user__tenant__name'  # Allows sorting by tenant name
    
    def reason_short(self, obj):
        if obj.reason:
            return obj.reason[:50] + '...' if len(obj.reason) > 50 else obj.reason
        return "-"
    reason_short.short_description = "Reason"
    
    def location(self, obj):
        if obj.ip_address and obj.ip_address.startswith('192.168'):
            return "Local Network"
        return "External"
    location.short_description = "Location"