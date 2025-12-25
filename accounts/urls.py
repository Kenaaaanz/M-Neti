# accounts/urls.py - Complete URL configuration
from django.urls import path
#from billing.views import (
        #bulk_data_marketplace, 
        #purchase_bulk_data,
        #isp_bulk_data_dashboard
    #)
from . import views, views_superadmin, views_isp, views_maps
from .admin_views import superadmin_dashboard
from django.contrib.auth import views as auth_views
from django.urls import include
from billing import views as billing_views
from accounts.views_isp import (
    api_bulk_create_customers, api_validate_customer_import, download_import_template, isp_customer_payments, isp_import_customers, isp_import_preview, isp_import_results, mark_payment_completed, delete_payment, download_payment_receipt,
    bulk_mark_payments_completed, export_payments_csv, isp_create_manual_payment
)

urlpatterns = [
    # ============================================
    # AUTHENTICATION & CORE URLs
    # ============================================
path('login/', views.login_view, name='login'),
path('logout/', views.logout_view, name='logout'),
path('register/', views.register, name='register'),
path('dashboard/', views.dashboard_router, name='dashboard_router'),

# Payment API endpoints
path('api/payments/<int:payment_id>/details/', views_isp.api_payment_details, name='api_payment_details'),
path('api/payments/<int:payment_id>/update-status/', views_isp.api_update_payment_status, name='api_update_payment_status'),
path('api/payments/bulk-action/', views_isp.api_bulk_payment_action, name='api_bulk_payment_action'),
path('api/payments/<int:payment_id>/receipt/', views_isp.api_payment_receipt, name='api_payment_receipt'),
path('api/payments/export/', views_isp.api_export_payments, name='api_export_payments'),
path('api/payments/bulk-update-status/', views_isp.api_bulk_update_payment_status, name='api_bulk_update_payment_status'),
path('api/payments/export-selected/', views_isp.api_export_selected_payments, name='api_export_selected_payments'),
path('api/payments/send-receipts/', views_isp.api_send_selected_receipts, name='api_send_selected_receipts'),
path('api/payments/delete-selected/', views_isp.api_delete_selected_payments, name='api_delete_selected_payments'),


# ============================================
# USER PROFILE & SETTINGS
# ============================================
path('profile/', views.profile, name='profile'),
path('change-password/', views.change_password, name='change_password'),
path('update-notifications/', views.update_notifications, name='update_notifications'),
path('update-preferences/', views.update_preferences, name='update_preferences'),
path('update-billing-address/', views.update_billing_address, name='update_billing_address'),
path('export-data/', views.export_data, name='export_data'),
path('delete-account/', views.delete_account, name='delete_account'),
path('sessions/revoke/<int:session_id>/', views.revoke_session, name='revoke_session'),

# Dark mode
path('toggle-dark-mode/', views.toggle_dark_mode, name='toggle_dark_mode'),
    
# 2FA URLs
path('setup-2fa/', views.setup_2fa, name='setup_2fa'),
path('verify-2fa-setup/', views.verify_2fa_setup, name='verify_2fa_setup'),
path('resend-2fa-otp/', views.resend_2fa_otp, name='resend_2fa_otp'),  # Add this line
path('verify-2fa-login/', views.verify_2fa_login, name='verify_2fa_login'),
path('disable-2fa/', views.disable_2fa, name='disable_2fa'),
path('regenerate-backup-codes/', views.regenerate_backup_codes, name='regenerate_backup_codes'),

# ============================================
# PAYMENT & SUBSCRIPTION
# ============================================
path('plans/', views.plan_selection, name='plan_selection'),
path('paystack/subscribe/', views.paystack_subscribe, name='paystack_subscribe'),
path('paystack/subscribe/<int:plan_id>/', views.paystack_subscribe_with_plan, name='paystack_subscribe_with_plan'),
path('paystack/verify/<str:reference>/', views.paystack_verify_payment, name='paystack_verify_payment'),
path('api/initiate-payment/<int:plan_id>/', views.initiate_paystack_payment, name='initiate_paystack_payment'),

# ============================================
# SUPPORT SYSTEM
# ============================================
path('support/', views.support_chat, name='support_chat'),
path('support/create/', views.support_create_conversation, name='support_create_conversation'),
path('support/operator/', views.support_operator_dashboard, name='support_operator_dashboard'),
path('support/conversation/<int:conversation_id>/', views.support_conversation_detail, name='support_conversation_detail'),

# Support API endpoints
path('api/support/conversations/', views.api_support_get_conversations, name='api_support_get_conversations'),
path('api/support/messages/<int:conversation_id>/', views.api_support_get_messages, name='api_support_get_messages'),
path('api/support/send/<int:conversation_id>/', views.api_support_send_message, name='api_support_send_message'),
path('api/support/unread-count/', views.api_support_get_unread_count, name='api_support_get_unread_count'),
path('api/support/conversation/<int:conversation_id>/update/', views.api_support_update_conversation, name='api_support_update_conversation'),

# ============================================
# SUPERADMIN URLs - CORE DASHBOARD
# ============================================
path('superadmin/dashboard/', views_superadmin.superadmin_dashboard, name='superadmin_dashboard'),
path('superadmin/analytics/', views_superadmin.superadmin_analytics, name='superadmin_analytics'),
path('superadmin/settings/', views_superadmin.superadmin_settings, name='superadmin_settings'),
path('superadmin/kill-switch/', views_superadmin.superadmin_kill_switch, name='superadmin_kill_switch'),

# ============================================
# SUPERADMIN - USER MANAGEMENT
# ============================================
path('superadmin/users/', views_superadmin.superadmin_users, name='superadmin_users'),
path('superadmin/users/create/', views_superadmin.superadmin_create_user, name='superadmin_create_user'),
path('superadmin/users/<int:user_id>/', views_superadmin.superadmin_view_user_details, name='superadmin_user_detail'),
path('superadmin/users/<int:user_id>/edit/', views_superadmin.superadmin_edit_user, name='superadmin_edit_user'),
path('superadmin/users/export/', views_superadmin.superadmin_export_users, name='superadmin_export_users'),

# User Actions
path('superadmin/users/<int:user_id>/approve/', views_superadmin.approve_user, name='approve_user'),
path('superadmin/users/<int:user_id>/reject/', views_superadmin.reject_user, name='reject_user'),
path('superadmin/users/<int:user_id>/toggle-status/', views_superadmin.toggle_user_status, name='toggle_user_status'),
path('superadmin/users/<int:user_id>/delete/', views_superadmin.delete_user, name='delete_user'),
path('superadmin/users/<int:user_id>/revoke-approval/', views_superadmin.revoke_approval, name='revoke_approval'),
path('superadmin/users/bulk-approve/', views_superadmin.bulk_approve_users, name='bulk_approve_users'),
path('superadmin/users/bulk-reject/', views_superadmin.bulk_reject_users, name='bulk_reject_users'),
path('superadmin/username-availability/', views_superadmin.check_username_availability, name='superadmin_username_availability'),

# ============================================
# SUPERADMIN - ISP/TENANT MANAGEMENT
# ============================================
path('superadmin/tenants/', views_superadmin.superadmin_tenants, name='superadmin_tenants'),
path('superadmin/tenants/create/', views_superadmin.superadmin_create_tenant, name='superadmin_create_tenant'),
path('superadmin/tenants/export/', views_superadmin.superadmin_export_tenants, name='superadmin_export_tenants'),

# Tenant Detail Views
path('superadmin/tenants/<uuid:tenant_id>/', views_superadmin.superadmin_tenant_detail, name='superadmin_tenant_detail'),
path('superadmin/tenants/<uuid:tenant_id>/edit/', views_superadmin.superadmin_tenant_edit, name='superadmin_tenant_edit'),
path('superadmin/tenants/<uuid:tenant_id>/delete/', views_superadmin.superadmin_tenant_delete, name='superadmin_tenant_delete'),
path('superadmin/tenants/<uuid:tenant_id>/verify/', views_superadmin.superadmin_tenant_verify, name='superadmin_tenant_verify'),
path('superadmin/tenants/<uuid:tenant_id>/analytics/', views_superadmin.superadmin_tenant_analytics, name='superadmin_tenant_analytics'),
path('superadmin/tenants/<uuid:tenant_id>/customers/', views_superadmin.superadmin_tenant_customers, name='superadmin_tenant_customers'),
path('superadmin/tenants/<uuid:tenant_id>/payments/', views_superadmin.superadmin_tenant_payments, name='superadmin_tenant_payments'),

# Tenant Payment Management API Endpoints
path('superadmin/tenants/<uuid:tenant_id>/payments/export/', views_superadmin.export_tenant_payments, name='export_tenant_payments'),
path('superadmin/tenants/<uuid:tenant_id>/payments/report/', views_superadmin.generate_payment_report, name='generate_payment_report'),
path('superadmin/tenants/<uuid:tenant_id>/send-payment-reminders/', views_superadmin.send_payment_reminders, name='send_payment_reminders'),

# Tenant Payment API Actions
path('superadmin/tenants/<uuid:tenant_id>/payments/<int:payment_id>/mark-completed/', 
        views_superadmin.mark_payment_completed, name='mark_payment_completed'),
path('superadmin/tenants/<uuid:tenant_id>/payments/<int:payment_id>/refund/', 
        views_superadmin.refund_payment, name='refund_payment'),
path('superadmin/tenants/<uuid:tenant_id>/payments/<int:payment_id>/resend-receipt/', 
        views_superadmin.resend_payment_receipt, name='resend_payment_receipt'),
path('superadmin/tenants/<uuid:tenant_id>/payments/<int:payment_id>/logs/', 
        views_superadmin.view_payment_logs, name='view_payment_logs'),
path('superadmin/tenants/<uuid:tenant_id>/payments/<int:payment_id>/delete/', 
        views_superadmin.delete_payment, name='delete_payment'),
path('superadmin/tenants/<uuid:tenant_id>/payments/<int:payment_id>/retry/', 
        views_superadmin.retry_failed_payment, name='retry_failed_payment'),
path('superadmin/tenants/<uuid:tenant_id>/payments/<int:payment_id>/details/', 
        views_superadmin.payment_details, name='payment_details'),

# Unified Payment API Handler (for all actions)
path('superadmin/tenants/<uuid:tenant_id>/payments/<int:payment_id>/<str:action>/', 
        views_superadmin.payment_api_handler, name='payment_api_handler'),

# ============================================
# SUPERADMIN - ISP ADMIN MANAGEMENT
# ============================================
path('superadmin/tenants/<uuid:tenant_id>/admins/', views_superadmin.superadmin_tenant_admins, name='superadmin_tenant_admins'),
path('superadmin/tenants/<uuid:tenant_id>/admins/create/', views_superadmin.superadmin_create_tenant_admin, name='superadmin_create_tenant_admin'),
path('superadmin/tenants/<uuid:tenant_id>/admins/<uuid:admin_id>/toggle-status/', 
        views_superadmin.toggle_admin_status, name='superadmin_toggle_admin_status'),
path('superadmin/tenants/<uuid:tenant_id>/admins/<uuid:admin_id>/remove/', 
        views_superadmin.remove_admin_from_tenant, name='superadmin_remove_admin'),
path('superadmin/tenants/<uuid:tenant_id>/admins/<uuid:admin_id>/send-password-reset/', 
        views_superadmin.send_admin_password_reset, name='send_admin_password_reset'),
path('superadmin/tenants/<uuid:tenant_id>/admins/export/', 
        views_superadmin.export_tenant_admins, name='superadmin_export_tenant_admins'),

# ============================================
# SUPERADMIN - BULK DATA MARKETPLACE MANAGEMENT
# ============================================
path('superadmin/bulk-data/', views_superadmin.superadmin_bulk_data_management, name='superadmin_bulk_data'),
path('superadmin/bulk-data/management/', views_superadmin.superadmin_bulk_data_management, name='superadmin_bulk_data_management'),
path('superadmin/bulk-data/create/', views_superadmin.superadmin_create_bulk_package, name='superadmin_create_bulk_package'),
path('superadmin/bulk-data/commissions/', views_superadmin.superadmin_commission_settings, name='superadmin_commission_settings'),
path('superadmin/bulk-data/purchases-report/', views_superadmin.superadmin_bulk_purchases_report, name='superadmin_bulk_purchases_report'),
path('superadmin/bulk-data/commission-report/', views_superadmin.superadmin_commission_report, name='superadmin_commission_report'),
path('superadmin/bulk-data/vendors/', views_superadmin.superadmin_manage_data_vendors, name='superadmin_data_vendors'),
path('superadmin/bulk-data/export-bulk-purchases/', views_superadmin.superadmin_export_bulk_data_purchases, name='superadmin_export_bulk_data_purchases'),
path('superadmin/bulk-data/export-purchases/', 
     views_superadmin.superadmin_export_bulk_data_purchases, 
     name='superadmin_export_bulk_purchases'),  # Changed from superadmin_export_bulk_data_purchases

path('superadmin/bulk-data/export-commissions/', 
     views_superadmin.superadmin_export_commissions, 
     name='superadmin_export_commissions'), 

# Bandwidth Management URLs
path('bulk-bandwidth/', views_superadmin.superadmin_bulk_bandwidth_management, name='superadmin_bulk_bandwidth'),
path('bulk-bandwidth/create/', views_superadmin.superadmin_create_bandwidth_package, name='superadmin_create_bandwidth_package'),
path('bulk-bandwidth/report/', views_superadmin.superadmin_bandwidth_purchases_report, name='superadmin_bandwidth_report'),
path('bandwidth-package/<uuid:package_id>/toggle/', views_superadmin.toggle_bandwidth_package_status, name='toggle_bandwidth_package'),
path('bandwidth-purchase/<uuid:purchase_id>/activate/', views_superadmin.activate_bandwidth_purchase, name='activate_bandwidth_purchase'),
path('bandwidth-purchases/export/', views_superadmin.export_bandwidth_purchases, name='export_bandwidth_purchases'),



# ============================================
# SUPERADMIN - PAYSTACK CONFIGURATION
# ============================================
path('superadmin/tenants/<uuid:tenant_id>/configure-paystack/', 
        views_superadmin.superadmin_configure_paystack_admin, name='superadmin_configure_paystack_admin'),
path('superadmin/tenants/<uuid:tenant_id>/configure-paystack-admin/',  
        views_superadmin.superadmin_configure_paystack_admin, name='superadmin_configure_paystack_admin'), 
path('superadmin/tenants/<uuid:tenant_id>/reset-paystack-config/', 
        views_superadmin.reset_paystack_config, name='reset_paystack_config'),

# ============================================
# SUPERADMIN - API ENDPOINTS
# ============================================
path('superadmin/tenants/<uuid:tenant_id>/verify-api/', 
        views_superadmin.superadmin_tenant_verify_api, name='superadmin_tenant_verify_api'),
path('superadmin/tenants/<uuid:tenant_id>/request-document/', 
        views_superadmin.superadmin_request_document, name='superadmin_request_document'),
path('superadmin/tenants/<uuid:tenant_id>/verification-logs/export/', 
        views_superadmin.superadmin_verification_log_export, name='superadmin_verification_log_export'),

# ============================================
# ISP ADMIN URLs
# ============================================
path('isp/dashboard/', views_isp.isp_dashboard, name='isp_dashboard'),
path('isp/dashboard/api/summary/', views_isp.isp_dashboard_api, name='isp_dashboard_api'),
path('isp/customers/', views_isp.isp_customer_management, name='isp_customers'),
path('isp/customers/add/', views_isp.isp_add_customer, name='isp_add_customer'),
path('isp/customers/<int:customer_id>/', views_isp.isp_customer_detail, name='isp_customer_detail'),
path('isp/customers/<int:customer_id>/edit/', views_isp.isp_edit_customer, name='isp_edit_customer'),
path('isp/customers/<int:customer_id>/delete/', views_isp.isp_delete_customer, name='isp_delete_customer'),
path('isp/customers/<int:customer_id>/logs/', views_isp.isp_customer_logs, name='isp_customer_logs'),
path('isp/customers/<int:customer_id>/payments/', views_isp.isp_customer_payments, name='isp_customer_payments'),
path('isp/customers/<int:customer_id>/extend/', views_isp.isp_extend_subscription, name='isp_extend_subscription'),

# Plan Management
path('isp/plans/', views_isp.isp_plan_management, name='isp_plans'),

# Router Management
path('isp/routers/', views_isp.isp_router_management, name='isp_routers'),
path('isp/routers/add/', views_isp.isp_add_customer_router, name='isp_add_customer_router'),
path('isp/routers/<int:router_id>/edit/', views_isp.isp_edit_customer_router, name='isp_edit_customer_router'),
path('isp/routers/<int:router_id>/delete/', views_isp.isp_delete_customer_router, name='isp_delete_customer_router'),
path('isp/routers/add/generic/', views_isp.isp_add_router, name='isp_add_router'),
#path('isp/router-config/add/', views_isp.isp_router_type_selection, name='isp_add_router'),
#path('isp/router-config/<int:router_id>/edit/', views_isp.isp_edit_router, name='isp_edit_router'),
#path('isp/router-config/<int:router_id>/delete/', views_isp.isp_delete_router, name='isp_delete_router'),
#path('isp/routers/port-forwarding/', views_isp.isp_port_forwarding, name='isp_port_forwarding'),
#path('isp/routers/add-port-forwarding/', views_isp.isp_add_port_forwarding, name='isp_add_port_forwarding'),
#path('isp/routers/<int:pf_id>/delete-port-forwarding/', views_isp.isp_delete_port_forwarding, name='isp_delete_port_forwarding'),

# Payment Management
path('isp/payments/', views_isp.isp_payment_management, name='isp_payments'),
path('isp/payments/generate-invoice/', views_isp.isp_generate_invoice, name='isp_generate_invoice'),
#path('api/payments/<int:payment_id>/details/', views_isp.api_payment_details, name='api_payment_details'),
#path('api/payments/<int:payment_id>/update-status/', views_isp.api_update_payment_status, name='api_update_payment_status'),
#path('api/payments/<int:payment_id>/receipt/', views_isp.api_payment_receipt, name='api_payment_receipt'),
#path('api/payments/bulk-action/', views_isp.api_bulk_payment_action, name='api_bulk_payment_action'),
 # Payment actions
#path('customers/<int:customer_id>/payments/', isp_customer_payments, name='isp_customer_payments'),
#path('customers/<int:customer_id>/payments/mark-completed/<int:payment_id>/', 
        #mark_payment_completed, name='mark_payment_completed'),
#path('customers/<int:customer_id>/payments/delete/<int:payment_id>/', 
        #delete_payment, name='delete_payment'),
#path('customers/<int:customer_id>/payments/receipt/<int:payment_id>/', 
        #download_payment_receipt, name='download_payment_receipt'),
#path('customers/<int:customer_id>/payments/export/', 
        #, name='export_payments_csv'),

# Manual payment actions
path('payments/<int:payment_id>/mark-completed/', views_isp.mark_payment_completed, name='mark_payment_completed'),
path('payments/<int:payment_id>/delete/', views_isp.delete_payment, name='delete_payment'),
path('payments/bulk-mark-completed/', views_isp.bulk_mark_payments_completed, name='bulk_mark_payments_completed'),
path('payments/<int:payment_id>/download-receipt/', views_isp.download_payment_receipt, name='download_payment_receipt'),
path('customers/<int:customer_id>/payments/export/', views_isp.export_payments_csv, name='export_payments_csv'),
path('customers/<int:customer_id>/create-manual-payment/', views_isp.isp_create_manual_payment, name='isp_create_manual_payment'),
# Data Wallet
path('isp/data-wallet/', views_isp.isp_data_wallet, name='isp_data_wallet'),

# Support & Approvals
path('isp/pending-approvals/', views_isp.isp_pending_approvals, name='isp_pending_approvals'),
path('isp/support-chat/', views_isp.isp_support_chat, name='isp_support_chat'),
path('isp/support-chat/send/', views_isp.isp_support_chat_send, name='isp_support_chat_send'),
path('isp/support-chat/<int:conv_id>/messages/', views_isp.isp_support_chat_messages, name='isp_support_chat_messages'),
path('isp/support-chat/operator/', views_isp.isp_support_operator, name='isp_support_operator'),

# Paystack Configuration
path('isp/configure-paystack/', views_isp.isp_configure_paystack, name='isp_configure_paystack'),

# Vendor Marketplace
path('marketplace/', views_isp.isp_vendor_marketplace, name='isp_vendor_marketplace'),
path('marketplace/purchase/<str:package_type>/<int:package_id>/', views_isp.isp_purchase_package, name='isp_purchase_package'),
path('marketplace/payment/<int:purchase_id>/', views_isp.isp_package_payment, name='isp_package_payment'),
path('marketplace/payment-callback/<int:purchase_id>/', views_isp.isp_package_payment_callback, name='isp_package_payment_callback'),
path('marketplace/purchase/<int:purchase_id>/', views_isp.isp_purchase_detail, name='isp_purchase_detail'),
path('marketplace/history/', views_isp.isp_purchase_history, name='isp_purchase_history'),
path('marketplace/allocate-bandwidth/<int:purchase_id>/', views_isp.isp_allocate_bandwidth, name='allocate_bandwidth'),

# API endpoints
path('api/marketplace/packages/', views_isp.api_marketplace_packages, name='api_marketplace_packages'),
path('api/marketplace/calculate/', views_isp.api_calculate_purchase, name='api_calculate_purchase'),

# ============================================
# CUSTOMER LOCATION & MAP URLs
# ============================================
path('customer/map/', views_maps.customer_map, name='customer_map'),
path('isp/map/', views_maps.isp_customer_map, name='isp_customer_map'),

# Map API endpoints
path('api/get-customer-locations/', views_maps.get_customer_locations, name='get_customer_locations'),
path('api/save-customer-location/', views_maps.save_customer_location, name='save_customer_location'),
path('api/customer/<int:customer_id>/verify-location/', views_maps.verify_customer_location, name='verify_customer_location'),
path('api/customer/<int:customer_id>/location-history/', views_maps.get_customer_location_history, name='get_customer_location_history'),
path('api/bulk-update-locations/', views_maps.bulk_update_customer_locations, name='bulk_update_customer_locations'),

# Customer details
path('isp/customer/<int:customer_id>/details/', views_maps.customer_details, name='customer_details'),

# ============================================
# LEGACY PAYMENT API ENDPOINTS (for backward compatibility)
# ============================================
path('api/payments/<int:payment_id>/<str:action>/', 
        views_superadmin.legacy_payment_api_handler, name='legacy_payment_api_handler'),

# Payment management URLs that point to billing views
path('customers/<int:customer_id>/payments/approve/', 
         billing_views.approve_manual_payment, name='approve_manual_payment'),
path('customers/<int:customer_id>/payments/create-auto/', 
         billing_views.create_auto_payment, name='create_auto_payment'),

# Import URLs
path('customers/import/', isp_import_customers, name='isp_import_customers'),
path('customers/import/preview/', isp_import_preview, name='isp_import_preview'),
path('customers/import/results/', isp_import_results, name='isp_import_results'),
path('customers/import/download-template/', download_import_template, name='download_import_template'),
path('customers/import/validate/', api_validate_customer_import, name='api_validate_customer_import'),
path('customers/import/bulk-create/', api_bulk_create_customers, name='api_bulk_create_customers'),

# ============================================
path('password-reset/', auth_views.PasswordResetView.as_view(), name='password_reset'),
path('password-reset/done/', auth_views.PasswordResetDoneView.as_view(), name='password_reset_done'),
path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
path('reset/done/', auth_views.PasswordResetCompleteView.as_view(), name='password_reset_complete'),

# SMS Management URLs
path('isp/sms/', views_isp.isp_sms_management, name='isp_sms_management'),
path('isp/sms/compose/', views_isp.isp_sms_compose, name='isp_sms_compose'),
path('isp/sms/campaign/<int:campaign_id>/', views_isp.isp_sms_campaign_detail, name='isp_sms_campaign_detail'),
path('isp/sms/templates/', views_isp.isp_sms_templates, name='isp_sms_templates'),
path('isp/sms/configure-provider/', views_isp.isp_configure_sms_provider, name='isp_configure_sms_provider'),
path('isp/sms/logs/', views_isp.isp_sms_logs, name='isp_sms_logs'),

# SMS API endpoints
path('api/sms/quick-send/', views_isp.api_send_quick_sms, name='api_send_quick_sms'),
path('api/sms/customers/', views_isp.api_get_customers_for_sms, name='api_get_customers_for_sms'),

# PayStack callback for package purchases
path('isp/marketplace/purchase/<int:purchase_id>/callback/', 
        views_isp.isp_package_payment_callback, 
        name='isp_package_payment_callback'),

# Geocoding API endpoints
path('api/search-address/', views_maps.search_address, name='search_address'),
path('api/reverse-geocode/', views_maps.reverse_geocode, name='reverse_geocode'),
path('api/geocode/', views_maps.GeocodeView.as_view(), name='geocode'),
path('api/mapbox-geocode/', views_maps.mapbox_geocode, name='mapbox_geocode'),

]