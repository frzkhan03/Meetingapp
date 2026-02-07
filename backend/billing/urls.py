from django.urls import path
from . import views, webhooks

urlpatterns = [
    path('pricing/', views.pricing_view, name='pricing'),
    path('checkout/<str:plan_tier>/<str:billing_cycle>/',
         views.create_checkout_view, name='billing_checkout'),
    path('checkout/success/', views.checkout_success_view, name='billing_checkout_success'),
    path('checkout/cancel/', views.checkout_cancel_view, name='billing_checkout_cancel'),
    path('manage/', views.billing_manage_view, name='billing_manage'),
    path('cancel/', views.cancel_subscription_view, name='billing_cancel'),
    path('resume/', views.resume_subscription_view, name='billing_resume'),
    path('webhooks/payu/', webhooks.payu_webhook_view, name='payu_webhook'),
    path('api/currency-rates/', views.currency_rates_api, name='currency_rates'),

    # Billing Info
    path('api/billing-info/', views.get_billing_info_view, name='billing_info_get'),
    path('api/billing-info/save/', views.save_billing_info_view, name='billing_info_save'),
    path('api/tax-label/', views.get_tax_label_api, name='tax_label_api'),

    # Invoices
    path('invoices/', views.invoice_list_view, name='invoice_list'),
    path('invoices/<uuid:invoice_id>/', views.invoice_detail_view, name='invoice_detail'),
    path('invoices/<uuid:invoice_id>/download/', views.invoice_download_view, name='invoice_download'),
    path('api/invoices/', views.invoices_api, name='invoices_api'),
]
