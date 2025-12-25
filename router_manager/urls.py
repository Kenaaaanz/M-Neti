# router_manager/urls.py
from django.urls import path
from . import views
from accounts import views_isp
from . import views_assignment


urlpatterns = [
    # ============================================
    # CUSTOMER ROUTER VIEWS
    # ============================================
    path('settings/', views.router_settings, name='router_settings'),
    path('settings/devices/', views.connected_devices, name='connected_devices'),
    path('settings/security/', views.security_settings, name='security_settings'),
    path('settings/advanced/', views.advanced_settings, name='advanced_settings'),
    path('settings/status/', views.router_status, name='router_status'),
    path('settings/guest-network/', views.guest_network, name='guest_network'),
    path('settings/firmware/', views.firmware_update, name='firmware_update'),
    path('settings/parental/', views.parental_controls, name='parental_controls'),
    path('settings/reboot/', views.reboot_router, name='reboot_router'),
    path('settings/devices/<int:device_id>/block/', views.block_device, name='block_device'),
    path('settings/devices/<int:device_id>/unblock/', views.unblock_device, name='unblock_device'),

    # ============================================
    # ISP ROUTER MANAGEMENT (USE views_isp FUNCTIONS)
    # ============================================
    path('isp/routers/', views_isp.isp_router_management, name='isp_routers'),
    path('isp/routers/add/', views_isp.isp_router_type_selection, name='isp_router_type_selection'),
    path('isp/routers/<int:router_id>/edit/', views_isp.isp_edit_router, name='isp_edit_router'),
    path('isp/routers/<int:router_id>/delete/', views_isp.isp_delete_router, name='isp_delete_router'),
    path('isp/routers/port-forwarding/', views_isp.isp_port_forwarding, name='isp_port_forwarding'),
    path('isp/routers/add-port-forwarding/', views_isp.isp_add_port_forwarding, name='isp_add_port_forwarding'),
    path('isp/routers/<int:pf_id>/delete-port-forwarding/', views_isp.isp_delete_port_forwarding, name='isp_delete_port_forwarding'),
    
    # ============================================
    # ISP ROUTER OPERATIONS (USE router_manager.views)
    # ============================================
    path('isp/routers/<int:router_id>/test/', views.isp_test_router_connection, name='isp_test_router_connection'),
    path('isp/routers/<int:router_id>/sync/', views.isp_sync_router, name='isp_sync_router'),
    path('isp/routers/<int:router_id>/update-wifi/', views.isp_update_router_wifi, name='isp_update_router_wifi'),
    path('isp/routers/<int:router_id>/reboot/', views.isp_remote_reboot, name='isp_remote_reboot'),
    path('isp/routers/bulk-sync/', views.isp_bulk_sync, name='isp_bulk_sync'),

    # ============================================
    # BRAND-SPECIFIC SETUP (router_manager.views)
    # ============================================
    path('isp/routers/setup/huawei/', views.isp_router_setup_huawei, name='isp_router_setup_huawei'),
    path('isp/routers/setup/mikrotik/', views.isp_router_setup_mikrotik, name='isp_router_setup_mikrotik'),
    path('isp/routers/setup/tenda/', views.isp_router_setup_tenda, name='isp_router_setup_tenda'),
    path('isp/routers/setup/tplink/', views.isp_router_setup_tplink, name='isp_router_setup_tplink'),
    path('isp/routers/setup/ubiquiti/', views.isp_router_setup_ubiquiti, name='isp_router_setup_ubiquiti'),
    path('isp/routers/setup/other/', views.isp_router_setup_other, name='isp_router_setup_other'),

    # ============================================
    # CUSTOMER PARENTAL CONTROLS
    # ============================================
    path('settings/parental/controls/', views.parental_controls, name='parental_controls'),
    path('settings/parental/unblock/<int:device_id>/', views.unblock_device_parental, name='unblock_device_parental'),
    path('settings/parental/schedule/delete/<int:schedule_id>/', views.delete_schedule, name='delete_schedule'),
    path('settings/parental/toggle-filter/', views.toggle_content_filter, name='toggle_content_filter'),
    path('settings/parental/pause-all/', views.pause_all_devices, name='pause_all_devices'),
    
    # ============================================
    # CUSTOMER FIRMWARE UPDATES
    # ============================================
    path('settings/firmware/', views.firmware_update, name='firmware_update'),
    path('settings/firmware/check/', views.check_for_updates, name='check_for_updates'),
    path('settings/firmware/status/', views.get_update_status, name='get_update_status'),
    path('settings/firmware/cancel/<int:update_id>/', views.cancel_scheduled_update, name='cancel_scheduled_update'),

    # ============================================
    # ADMIN ROUTER MANAGEMENT (superadmin/staff only)
    # ============================================
    path('admin/router/status/', views.admin_router_status, name='admin_router_status'),
    path('admin/router/control/', views.admin_router_control, name='admin_router_control'),
    path('admin/router/discover/', views.admin_discover_routers, name='admin_discover_routers'),

    # ============================================
    # ROUTER ASSIGNMENT URLs
    # ============================================
    path('isp/assignments/dashboard/', views_assignment.router_assignment_dashboard, 
         name='router_assignment_dashboard'),
    path('isp/assignments/', views_assignment.router_assignment_list, 
         name='router_assignment_list'),
    path('isp/assignments/assign/<int:config_id>/', views_assignment.assign_router_to_customer, 
         name='assign_router_to_customer'),
    path('isp/assignments/unassign/<int:config_id>/', views_assignment.unassign_router, 
         name='unassign_router'),
    path('isp/assignments/quick-assign/', views_assignment.quick_assign_router, 
         name='quick_assign_router'),
    path('isp/assignments/bulk/', views_assignment.bulk_assignment, 
         name='bulk_assignment'),
    path('isp/assignments/bulk/results/', views_assignment.bulk_assignment_results, 
         name='bulk_assignment_results'),
    path('isp/assignments/template/', views_assignment.download_assignment_template, 
         name='download_assignment_template'),
    path('isp/assignments/api/available/', views_assignment.available_routers_api, 
         name='available_routers_api'),
    path('isp/assignments/customer/<int:customer_id>/', views_assignment.customer_router_details, 
         name='customer_router_details'),
    path('isp/assignments/test/<int:config_id>/', views_assignment.test_router_connection, 
         name='test_router_connection'),
]