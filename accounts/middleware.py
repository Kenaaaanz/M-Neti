import re
from django.http import HttpResponseForbidden
from .models import Tenant

class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.base_domain = re.compile(r'(.+)\.mneti\.com')

    def __call__(self, request):
        request.tenant = self.get_tenant_from_request(request)
        response = self.get_response(request)
        return response

    def get_tenant_from_request(self, request):
        host = request.get_host().split(':')[0]
        
        # Check custom domains
        try:
            tenant = Tenant.objects.get(custom_domain=host, is_active=True)
            return tenant
        except Tenant.DoesNotExist:
            pass
        
        # Check subdomains
        match = self.base_domain.match(host)
        if match:
            subdomain = match.group(1)
            if subdomain not in ['www', 'admin', 'api', 'app']:
                try:
                    tenant = Tenant.objects.get(subdomain=subdomain, is_active=True)
                    return tenant
                except Tenant.DoesNotExist:
                    pass
        
        return None

class RoleAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        return response

    def process_view(self, request, view_func, view_args, view_kwargs):
        # Skip for admin and auth views
        if request.path.startswith('/admin/') or request.path.startswith('/accounts/login/'):
            return None
            
        user = request.user
        
        # Check tenant access
        if hasattr(request, 'tenant') and request.tenant:
            if user.is_authenticated and user.role in ['isp_admin', 'isp_staff', 'customer']:
                if user.tenant != request.tenant:
                    return HttpResponseForbidden("Access denied - wrong tenant domain")
        
        return None