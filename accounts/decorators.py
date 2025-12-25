# accounts/decorators.py
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.contrib import messages
from functools import wraps

def isp_required(view_func):
    @wraps(view_func)
    @login_required
    def _wrapped_view(request, *args, **kwargs):
        if request.user.role not in ['isp_admin', 'isp_staff']:
            messages.error(request, 'Access denied. ISP admin or staff privileges required.')
            return redirect('dashboard')
        return view_func(request, *args, **kwargs)
    return _wrapped_view