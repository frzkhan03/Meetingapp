from django.urls import path
from . import views, webhooks

urlpatterns = [
    path('pricing/', views.pricing_view, name='pricing'),
    path('checkout/<str:plan_tier>/<str:billing_cycle>/',
         views.create_checkout_view, name='billing_checkout'),
    path('checkout/success/', views.checkout_success_view, name='billing_checkout_success'),
    path('checkout/cancel/', views.checkout_cancel_view, name='billing_checkout_cancel'),
    path('manage/', views.billing_manage_view, name='billing_manage'),
    path('portal/', views.customer_portal_view, name='billing_portal'),
    path('cancel/', views.cancel_subscription_view, name='billing_cancel'),
    path('resume/', views.resume_subscription_view, name='billing_resume'),
    path('webhooks/stripe/', webhooks.stripe_webhook_view, name='stripe_webhook'),
]
