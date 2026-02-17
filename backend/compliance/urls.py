from django.urls import path
from . import views

urlpatterns = [
    # Public pages
    path('privacy/', views.privacy_policy_view, name='privacy_policy'),
    path('terms/', views.terms_of_service_view, name='terms_of_service'),

    # Cookie consent (anonymous users too)
    path('cookie-consent/', views.cookie_consent_view, name='cookie_consent'),

    # GDPR: User self-service
    path('settings/', views.compliance_settings_view, name='compliance_settings'),
    path('update-consent/', views.update_consent_view, name='update_consent'),
    path('delete-account/', views.delete_account_view, name='delete_account'),
    path('export/', views.data_export_view, name='data_export'),
    path('export/request/', views.request_data_export, name='request_data_export'),
    path('export/download/<uuid:export_id>/', views.download_data_export, name='download_data_export'),

    # PCI DSS documentation
    path('pci-compliance/', views.pci_compliance_view, name='pci_compliance'),

    # Admin compliance dashboard
    path('admin-dashboard/', views.admin_compliance_dashboard, name='compliance_dashboard'),
]
