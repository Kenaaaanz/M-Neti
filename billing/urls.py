from django.urls import path

from accounts import views_isp
from . import views, views_admin
from accounts.views_isp import admin_configure_paystack_subaccount
from billing.views import payment_success

urlpatterns = [
    # ==================== DATA WALLET URLS ====================
    path('isp/data-wallet/', views.isp_data_wallet, name='isp_data_wallet'),
    path('isp/allocate-from-wallet/', views.isp_allocate_from_wallet, name='isp_allocate_from_wallet'),
    path('isp/sync-wallet-from-purchases/', views.sync_wallet_from_purchases, name='sync_wallet_from_purchases'),
    
    # ==================== BULK DATA URLS ====================
    path('bulk-data/marketplace/', views.bulk_data_marketplace, name='bulk_data_marketplace'),
    path('bulk-data/purchase/<int:package_id>/', views.purchase_bulk_data, name='purchase_bulk_data'),
    path('bulk-data/payment/<int:purchase_id>/', views.process_bulk_data_payment, name='process_bulk_data_payment'),
    path('bulk-data/paystack/<int:purchase_id>/', views.paystack_bulk_data_payment, name='paystack_bulk_data_payment'),
    path('bulk-data/callback/<int:purchase_id>/', views.paystack_bulk_data_callback, name='paystack_bulk_data_callback'),
    path('bulk-data/purchase/<int:purchase_id>/detail/', views.bulk_purchase_detail, name='bulk_purchase_detail'),
    path('bulk-data/history/', views.bulk_purchase_history, name='bulk_purchase_history'),
    
    # ==================== COMMISSION URLS ====================
    path('commissions/isp-dashboard/', views.isp_commission_dashboard, name='isp_commission_dashboard'),
    
    # ==================== CUSTOMER PAYMENT URLS ====================
    path('plans/', views.plan_selection, name='plan_selection'),
    path('plan-list/', views.plan_selection, name='plan_list'),  # Alias for your templates
    
    # Paystack checkout endpoints (for AJAX/inline checkout) - UUID version
    path('payment/initiate/<uuid:plan_id>/', views.initiate_payment, name='initiate_payment'),
    path('payment/api/verify/', views.verify_payment_api, name='verify_payment_api'),
    
    # Payment verification and success (both old and new flows)
    path('payment/verify/<str:reference>/', views.payment_verify, name='payment_verify'),
    path('payment/success/<str:reference>/', views.payment_success, name='payment_success'),
    
    # Old redirect flow (kept for backward compatibility) - UUID version
    path('subscribe/<uuid:plan_id>/', views.paystack_subscribe_with_plan, name='paystack_subscribe_with_plan'),
    path('subscribe/', views.paystack_subscribe, name='paystack_subscribe'),
    path('payment/confirmation/<int:payment_id>/', views.payment_confirmation, name='payment_confirmation'),
    
    # ==================== PAYMENT HISTORY URLS ====================
    path('payment/history/', views.payment_history, name='payment_history'),
    path('api/payment/<int:payment_id>/details/', views.api_payment_details, name='api_payment_details'),
    
    # ==================== WEBHOOK URLS ====================
    path('webhook/paystack/', views.paystack_webhook, name='paystack_webhook'),
    
    # ==================== ADMIN URLS ====================
    path('admin/configure-paystack/<uuid:tenant_id>/', admin_configure_paystack_subaccount, name='configure_paystack'),
    path('admin/bulk-data/packages/', views_admin.admin_bulk_data_packages, name='admin_bulk_data_packages'),
    path('admin/commissions/settings/', views_admin.admin_commission_settings, name='admin_commission_settings'),
    path('admin/bulk-purchases/report/', views_admin.admin_bulk_purchases_report, name='admin_bulk_purchases_report'),
    path('admin/commissions/report/', views_admin.admin_platform_commission_report, name='admin_platform_commission_report'),
    path('admin/data-vendors/', views_admin.admin_data_vendors, name='admin_data_vendors'),
    
    # External data management
    path('external-data/upload/', views.external_data_upload, name='external_data_upload'),
    path('external-data/upload-csv/', views.upload_data_csv, name='upload_data_csv'),
    path('external-data/sync-source/<int:source_id>/', views.sync_external_source, name='sync_external_source'),
    
    # External sources management
    path('external-sources/', views.manage_external_sources, name='manage_external_sources'),
    path('external-sources/add/', views.add_external_source, name='add_external_source'),
    path('external-sources/edit/<int:source_id>/', views.edit_external_source, name='edit_external_source'),
    path('external-sources/delete/<int:source_id>/', views.delete_external_source, name='delete_external_source'),
    path('external-sources/toggle/<int:source_id>/', views.toggle_external_source, name='toggle_external_source'),
    path('external-sources/test/<int:source_id>/', views.test_external_source, name='test_external_source'),
    
    # Data import/export
    path('data-import/', views.data_import_tool, name='data_import_tool'),
    path('data-import/history/', views.data_import_history, name='data_import_history'),
    path('data-import/template/<str:format_type>/', views.export_data_template, name='export_data_template'),
    
    # Scheduled tasks
    path('run-scheduled-syncs/', views.run_scheduled_syncs, name='run_scheduled_syncs'),
    
    # External source sync
    path('sync-external-source/<int:source_id>/', views.sync_external_source, name='sync_external_source'),

    # Payment automation webhooks
    path('webhook/payment/', views.auto_payment_webhook, name='payment_webhook'),
    path('webhook/paystack/', views.paystack_webhook, name='paystack_webhook'),
    
    # Manual payment approval
    path('customers/<int:customer_id>/payments/approve/', 
         views.approve_manual_payment, name='approve_manual_payment'),
    
    # Automatic payment creation
    path('customers/<int:customer_id>/payments/create-auto/', 
         views.create_auto_payment, name='create_auto_payment'),
    
    # Payment verification endpoint
    path('api/verify-payment/', views.verify_payment_api, name='verify_payment_api'),

    path('ajax/allocate-bandwidth/', views.ajax_allocate_bandwidth, name='ajax_allocate_bandwidth'),
    ]

