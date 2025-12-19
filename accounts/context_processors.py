from itertools import count
from .models import Tenant, CustomUser
from django.db.models import Q

def tenant_context(request):
    """
    Context processor for tenant information and comprehensive branding
    """
    context = {}
    
    # Get tenant from request or user
    tenant = getattr(request, 'tenant', None)
    if not tenant and hasattr(request, 'user') and request.user.is_authenticated:
        tenant = getattr(request.user, 'tenant', None)
    
    if tenant:
        context.update({
            'tenant': tenant,
            'tenant_domain': tenant.primary_domain,
            'tenant_name': tenant.name,
            'tenant_company': tenant.company_name,
            'tenant_contact_email': tenant.contact_email,
            'tenant_contact_phone': tenant.contact_phone,
            'tenant_logo_url': tenant.logo.url if tenant.logo else None,
            'tenant_subdomain': tenant.subdomain,
            'is_tenant_active': tenant.is_active,
            'tenant_subscription_plan': tenant.subscription_plan,
            'tenant_subscription_active': tenant.is_subscription_active(),
        })
        
        # Get tenant colors with defaults
        primary_color = tenant.primary_color if tenant.primary_color else '#4361ee'
        secondary_color = tenant.secondary_color if tenant.secondary_color else '#3a0ca3'
        accent_color = tenant.accent_color if tenant.accent_color else '#f59e0b'
        light_color = tenant.light_color if tenant.light_color else '#eff6ff'
        dark_color = tenant.dark_color if tenant.dark_color else '#1e3a8a'
        text_color = tenant.text_color if tenant.text_color else '#1f2937'
        success_color = tenant.success_color if tenant.success_color else '#10b981'
        warning_color = tenant.warning_color if tenant.warning_color else '#f59e0b'
        error_color = tenant.error_color if tenant.error_color else '#ef4444'
        info_color = tenant.info_color if tenant.info_color else '#3b82f6'
        
        # Helper function to generate color variations
        def hex_to_rgb(hex_color):
            """Convert hex color to RGB tuple"""
            hex_color = hex_color.lstrip('#')
            if len(hex_color) == 3:
                hex_color = ''.join([c*2 for c in hex_color])
            return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        
        def rgb_to_hex(rgb):
            """Convert RGB tuple to hex color"""
            return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
        
        def lighten_color(hex_color, factor=0.2):
            """Lighten a hex color by a factor"""
            rgb = hex_to_rgb(hex_color)
            light_rgb = tuple(min(255, int(c + (255 - c) * factor)) for c in rgb)
            return rgb_to_hex(light_rgb)
        
        def darken_color(hex_color, factor=0.2):
            """Darken a hex color by a factor"""
            rgb = hex_to_rgb(hex_color)
            dark_rgb = tuple(max(0, int(c * (1 - factor))) for c in rgb)
            return rgb_to_hex(dark_rgb)
        
        # Generate color variations
        primary_light = lighten_color(primary_color, 0.15)
        primary_dark = darken_color(primary_color, 0.15)
        secondary_light = lighten_color(secondary_color, 0.15)
        secondary_dark = darken_color(secondary_color, 0.15)
        accent_light = lighten_color(accent_color, 0.15)
        accent_dark = darken_color(accent_color, 0.15)
        
        # Get RGB values for CSS variables
        primary_rgb = hex_to_rgb(primary_color)
        secondary_rgb = hex_to_rgb(secondary_color)
        accent_rgb = hex_to_rgb(accent_color)
        
        context['tenant_css'] = f"""
        :root {{
            /* Primary Color Palette */
            --tenant-primary: {primary_color};
            --tenant-primary-light: {primary_light};
            --tenant-primary-dark: {primary_dark};
            --tenant-primary-rgb: {primary_rgb[0]}, {primary_rgb[1]}, {primary_rgb[2]};
            --tenant-primary-10: {primary_color}1a;
            --tenant-primary-20: {primary_color}33;
            --tenant-primary-50: {primary_color}80;
            
            /* Secondary Color Palette */
            --tenant-secondary: {secondary_color};
            --tenant-secondary-light: {secondary_light};
            --tenant-secondary-dark: {secondary_dark};
            --tenant-secondary-rgb: {secondary_rgb[0]}, {secondary_rgb[1]}, {secondary_rgb[2]};
            
            /* Accent Color Palette */
            --tenant-accent: {accent_color};
            --tenant-accent-light: {accent_light};
            --tenant-accent-dark: {accent_dark};
            --tenant-accent-rgb: {accent_rgb[0]}, {accent_rgb[1]}, {accent_rgb[2]};
            
            /* Light & Dark Variants */
            --tenant-light: {light_color};
            --tenant-dark: {dark_color};
            
            /* Text Colors */
            --tenant-text: {text_color};
            --tenant-text-light: #6b7280;
            --tenant-text-lighter: #9ca3af;
            
            /* UI Colors */
            --tenant-success: {success_color};
            --tenant-warning: {warning_color};
            --tenant-error: {error_color};
            --tenant-info: {info_color};
            
            /* Background Colors */
            --tenant-bg-primary: #ffffff;
            --tenant-bg-secondary: #f9fafb;
            --tenant-bg-tertiary: #f3f4f6;
            
            /* Border Colors */
            --tenant-border: #e5e7eb;
            --tenant-border-light: #f3f4f6;
            --tenant-border-dark: #d1d5db;
            
            /* Shadow Colors */
            --tenant-shadow-sm: 0 1px 2px 0 rgba({primary_rgb[0]}, {primary_rgb[1]}, {primary_rgb[2]}, 0.05);
            --tenant-shadow: 0 1px 3px 0 rgba({primary_rgb[0]}, {primary_rgb[1]}, {primary_rgb[2]}, 0.1), 0 1px 2px 0 rgba({primary_rgb[0]}, {primary_rgb[1]}, {primary_rgb[2]}, 0.06);
            --tenant-shadow-md: 0 4px 6px -1px rgba({primary_rgb[0]}, {primary_rgb[1]}, {primary_rgb[2]}, 0.1), 0 2px 4px -1px rgba({primary_rgb[0]}, {primary_rgb[1]}, {primary_rgb[2]}, 0.06);
            --tenant-shadow-lg: 0 10px 15px -3px rgba({primary_rgb[0]}, {primary_rgb[1]}, {primary_rgb[2]}, 0.1), 0 4px 6px -2px rgba({primary_rgb[0]}, {primary_rgb[1]}, {primary_rgb[2]}, 0.05);
            --tenant-shadow-xl: 0 20px 25px -5px rgba({primary_rgb[0]}, {primary_rgb[1]}, {primary_rgb[2]}, 0.1), 0 10px 10px -5px rgba({primary_rgb[0]}, {primary_rgb[1]}, {primary_rgb[2]}, 0.04);
            
            /* Brand Gradients */
            --tenant-gradient-primary: linear-gradient(135deg, {primary_color} 0%, {primary_light} 100%);
            --tenant-gradient-secondary: linear-gradient(135deg, {secondary_color} 0%, {secondary_light} 100%);
            --tenant-gradient-hero: linear-gradient(135deg, {primary_color} 0%, {secondary_color} 100%);
            --tenant-gradient-accent: linear-gradient(135deg, {accent_color} 0%, {accent_light} 100%);
            --tenant-gradient-light: linear-gradient(135deg, {light_color} 0%, #ffffff 100%);
        }}
        
        /* Tenant-specific component styles */
        .tenant-brand-bg {{
            background: var(--tenant-gradient-hero) !important;
        }}
        
        .tenant-gradient-bg {{
            background: var(--tenant-gradient-primary) !important;
        }}
        
        .tenant-primary-bg {{
            background-color: var(--tenant-primary) !important;
        }}
        
        .tenant-secondary-bg {{
            background-color: var(--tenant-secondary) !important;
        }}
        
        .tenant-accent-bg {{
            background-color: var(--tenant-accent) !important;
        }}
        
        .tenant-light-bg {{
            background-color: var(--tenant-light) !important;
        }}
        
        .tenant-primary-text {{
            color: var(--tenant-primary) !important;
        }}
        
        .tenant-secondary-text {{
            color: var(--tenant-secondary) !important;
        }}
        
        .tenant-accent-text {{
            color: var(--tenant-accent) !important;
        }}
        
        .tenant-border-primary {{
            border-color: var(--tenant-primary) !important;
        }}
        
        .tenant-border-secondary {{
            border-color: var(--tenant-secondary) !important;
        }}
        
        .tenant-border-accent {{
            border-color: var(--tenant-accent) !important;
        }}
        
        .tenant-button-primary {{
            background: var(--tenant-gradient-primary);
            border: none;
            color: white !important;
            transition: all 0.2s ease;
        }}
        
        .tenant-button-primary:hover {{
            background: var(--tenant-primary-dark);
            transform: translateY(-1px);
            box-shadow: var(--tenant-shadow-md);
        }}
        
        .tenant-button-secondary {{
            background: var(--tenant-gradient-secondary);
            border: none;
            color: white !important;
            transition: all 0.2s ease;
        }}
        
        .tenant-button-secondary:hover {{
            background: var(--tenant-secondary-dark);
            transform: translateY(-1px);
            box-shadow: var(--tenant-shadow-md);
        }}
        
        .tenant-button-accent {{
            background: var(--tenant-gradient-accent);
            border: none;
            color: white !important;
            transition: all 0.2s ease;
        }}
        
        .tenant-button-accent:hover {{
            background: var(--tenant-accent-dark);
            transform: translateY(-1px);
            box-shadow: var(--tenant-shadow-md);
        }}
        
        .tenant-card {{
            border-left: 4px solid var(--tenant-primary);
            box-shadow: var(--tenant-shadow-sm);
            transition: all 0.3s ease;
        }}
        
        .tenant-card:hover {{
            box-shadow: var(--tenant-shadow-md);
            transform: translateY(-2px);
        }}
        
        .tenant-nav-active {{
            color: var(--tenant-primary) !important;
            background-color: var(--tenant-primary-10) !important;
            border-left: 3px solid var(--tenant-primary);
        }}
        
        .tenant-badge {{
            background-color: var(--tenant-primary);
            color: white;
            padding: 0.25rem 0.5rem;
            border-radius: 0.375rem;
            font-size: 0.75rem;
            font-weight: 600;
        }}
        
        .tenant-progress-bar {{
            background: var(--tenant-gradient-primary);
            height: 0.5rem;
            border-radius: 0.25rem;
        }}
        
        /* Override Tailwind colors with tenant colors */
        .text-blue-600 {{ color: var(--tenant-primary) !important; }}
        .bg-blue-600 {{ background-color: var(--tenant-primary) !important; }}
        .border-blue-600 {{ border-color: var(--tenant-primary) !important; }}
        .hover\:bg-blue-700:hover {{ background-color: var(--tenant-primary-dark) !important; }}
        
        .text-purple-600 {{ color: var(--tenant-secondary) !important; }}
        .bg-purple-600 {{ background-color: var(--tenant-secondary) !important; }}
        .border-purple-600 {{ border-color: var(--tenant-secondary) !important; }}
        
        .text-yellow-500 {{ color: var(--tenant-accent) !important; }}
        .bg-yellow-500 {{ background-color: var(--tenant-accent) !important; }}
        
        .text-green-600 {{ color: var(--tenant-success) !important; }}
        .bg-green-600 {{ background-color: var(--tenant-success) !important; }}
        
        .text-red-600 {{ color: var(--tenant-error) !important; }}
        .bg-red-600 {{ background-color: var(--tenant-error) !important; }}
        
        /* Scrollbar styling */
        ::-webkit-scrollbar {{
            width: 10px;
        }}
        
        ::-webkit-scrollbar-track {{
            background: var(--tenant-light);
        }}
        
        ::-webkit-scrollbar-thumb {{
            background: var(--tenant-primary);
            border-radius: 5px;
        }}
        
        ::-webkit-scrollbar-thumb:hover {{
            background: var(--tenant-primary-dark);
        }}
        """
        
        # Add JavaScript configuration for tenant
        context['tenant_js_config'] = f"""
        window.tenantConfig = {{
            id: '{tenant.id}',
            name: '{tenant.name}',
            company: '{tenant.company_name}',
            domain: '{tenant.primary_domain}',
            subdomain: '{tenant.subdomain}',
            colors: {{
                primary: '{primary_color}',
                secondary: '{secondary_color}',
                accent: '{accent_color}',
                light: '{light_color}',
                dark: '{dark_color}',
                text: '{text_color}',
                success: '{success_color}',
                warning: '{warning_color}',
                error: '{error_color}',
                info: '{info_color}',
                primaryLight: '{primary_light}',
                primaryDark: '{primary_dark}',
                secondaryLight: '{secondary_light}',
                secondaryDark: '{secondary_dark}',
            }},
            contact: {{
                email: '{tenant.contact_email}',
                phone: '{tenant.contact_phone or ''}',
            }},
            branding: {{
                logo: '{tenant.logo.url if tenant.logo else ''}',
            }},
            features: {{
                bandwidthLimit: {tenant.bandwidth_limit},
                clientLimit: {tenant.client_limit},
                autoDisconnect: {str(tenant.auto_disconnect_enabled).lower()},
            }}
        }};
        
        // Apply tenant colors to document
        document.addEventListener('DOMContentLoaded', function() {{
            const root = document.documentElement;
            
            // Update CSS variables
            root.style.setProperty('--tenant-primary', '{primary_color}');
            root.style.setProperty('--tenant-secondary', '{secondary_color}');
            root.style.setProperty('--tenant-accent', '{accent_color}');
            
            // Update meta theme-color for mobile browsers
            const metaThemeColor = document.querySelector('meta[name="theme-color"]');
            if (!metaThemeColor) {{
                const meta = document.createElement('meta');
                meta.name = 'theme-color';
                meta.content = '{primary_color}';
                document.head.appendChild(meta);
            }} else {{
                metaThemeColor.content = '{primary_color}';
            }}
            
            // Add tenant class to body for global targeting
            document.body.classList.add('tenant-' + '{tenant.subdomain or tenant.id}');
        }});
        """
        
        # Add individual color variables for easy use in templates
        context.update({
            'brand_primary': primary_color,
            'brand_secondary': secondary_color,
            'brand_accent': accent_color,
            'brand_light': light_color,
            'brand_dark': dark_color,
            'brand_text': text_color,
            'brand_success': success_color,
            'brand_warning': warning_color,
            'brand_error': error_color,
            'brand_info': info_color,
        })
    
    else:
        # Default values when no tenant is available
        default_primary = '#4361ee'
        default_secondary = '#3a0ca3'
        default_accent = '#f59e0b'
        default_light = '#eff6ff'
        default_dark = '#1e3a8a'
        default_text = '#1f2937'
        default_success = '#10b981'
        default_warning = '#f59e0b'
        default_error = '#ef4444'
        default_info = '#3b82f6'
        
        context.update({
            'tenant': None,
            'tenant_name': 'CloudNetworks',
            'tenant_company': 'CloudNetworks ISP',
            'tenant_contact_email': 'support@cloudnetworks.com',
            'tenant_contact_phone': '+2547090251635',
            'tenant_logo_url': None,
            'brand_primary': default_primary,
            'brand_secondary': default_secondary,
            'brand_accent': default_accent,
            'brand_light': default_light,
            'brand_dark': default_dark,
            'brand_text': default_text,
            'brand_success': default_success,
            'brand_warning': default_warning,
            'brand_error': default_error,
            'brand_info': default_info,
        })
        
        # Default CSS with all required variables
        context['tenant_css'] = f"""
        :root {{
            --tenant-primary: {default_primary};
            --tenant-secondary: {default_secondary};
            --tenant-accent: {default_accent};
            --tenant-light: {default_light};
            --tenant-dark: {default_dark};
            --tenant-text: {default_text};
            --tenant-success: {default_success};
            --tenant-warning: {default_warning};
            --tenant-error: {default_error};
            --tenant-info: {default_info};
        }}
        """
        
        context['tenant_js_config'] = """
        window.tenantConfig = {
            name: 'CloudNetworks',
            company: 'CloudNetworks ISP',
            contact: {
                email: 'support@cloudnetworks.com',
                phone: '+2547090251635',
            }
        };
        """
    
    return context

def isp_navigation(request):
    """
    Context processor for ISP navigation that adds pending approvals count
    """
    context = {}
    
    if hasattr(request, 'user') and request.user.is_authenticated:
        if request.user.role in ['isp_admin', 'isp_staff']:
            tenant = getattr(request.user, 'tenant', None)
            if tenant:
                try:
                    # Safely get pending count with error handling
                    if hasattr(CustomUser, 'registration_status'):
                        pending_count = CustomUser.objects.filter(
                            tenant=tenant, 
                            role='customer',
                            registration_status='pending'
                        ).count()
                    else:
                        # Field doesn't exist yet (during migration)
                        pending_count = 0
                except Exception:
                    # Handle any database errors
                    pending_count = 0
                
                context.update({
                    'pending_count': pending_count,
                    'isp_tenant': tenant,
                })
    
    return context

    # accounts/context_processors.py (create if doesn't exist)
from billing.models import BulkDataPackage, ISPBulkPurchase, CommissionTransaction
from django.db.models import Sum

def superadmin_dashboard_stats(request):
    """Add bulk data statistics to superadmin dashboard"""
    if not request.user.is_superuser:
        return {}
    
    stats = {}
    
    try:
        # Bulk data package stats
        stats['total_bulk_packages'] = BulkDataPackage.objects.count()
        stats['active_bulk_packages'] = BulkDataPackage.objects.filter(is_active=True).count()
        
        # Bulk purchase stats
        bulk_purchase_stats = ISPBulkPurchase.objects.aggregate(
            total_purchases=Sum('total_price') or 0,
            total_commission=Sum('platform_commission') or 0,
            count=count('id')
        )
        stats.update(bulk_purchase_stats)
        
        # Commission stats
        commission_stats = CommissionTransaction.objects.aggregate(
            total_commission=Sum('commission_amount') or 0,
            commission_count=count('id')
        )
        stats.update(commission_stats)
        
    except Exception as e:
        # If models don't exist yet, provide defaults
        stats.update({
            'total_bulk_packages': 0,
            'active_bulk_packages': 0,
            'total_purchases': 0,
            'total_commission': 0,
            'count': 0,
            'commission_count': 0,
        })
    
    return {'bulk_data_stats': stats}