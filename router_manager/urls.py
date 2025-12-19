# router_manager/urls.py (updated)
from django.urls import path
from . import views

urlpatterns = [
    path('setup/', views.customer_router_setup, name='router_setup'),
    path('settings/', views.router_settings, name='router_settings'),
    path('password/', views.change_wifi_password, name='change_wifi_password'),
    path('devices/', views.connected_devices, name='connected_devices'),
    path('advanced/', views.advanced_settings, name='advanced_settings'),
    path('security/', views.security_settings, name='security_settings'),
    path('status/', views.router_status, name='router_status'),
    path('reboot/', views.reboot_router, name='reboot_router'),
    path('devices/block/<int:device_id>/', views.block_device, name='block_device'),
    path('devices/unblock/<int:device_id>/', views.unblock_device, name='unblock_device'),
]