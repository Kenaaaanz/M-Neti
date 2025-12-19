"""
URL configuration for M-Neti project.
"""
from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from accounts import views as account_views
from accounts.admin_views import superadmin_dashboard, analytics_detail
from django.conf import settings
from django.conf.urls.static import static
from accounts.views import dashboard

urlpatterns = [
    # Django Admin
    path('admin/', admin.site.urls),

    # App URLs
    path('accounts/', include('accounts.urls')),
    path('billing/', include('billing.urls')),
    path('router/', include('router_manager.urls')),
    
    
    # Core URLs
    path('', account_views.dashboard, name='dashboard'),
    path('dashboard/', dashboard, name='dashboard'),
    
    # Authentication URLs
    path('register/', account_views.register, name='register'),
    path('login/', auth_views.LoginView.as_view(template_name='accounts/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    
    # Profile
    path('profile/', account_views.profile, name='profile'),
    
    # Password Reset
    path('password_reset/', auth_views.PasswordResetView.as_view(), name='password_reset'),
    path('password_reset/done/', auth_views.PasswordResetDoneView.as_view(), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(), name='password_reset_complete'),
    
    # Admin dashboard (legacy)
    path('admin/analytics/<str:chart_type>/', admin.site.admin_view(analytics_detail), name='analytics_detail'),
] + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)