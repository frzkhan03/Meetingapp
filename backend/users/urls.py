from django.urls import path
from . import views

urlpatterns = [
    path('register/', views.register_view, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    # Organization management
    path('organizations/', views.organization_list_view, name='organization_list'),
    path('organizations/create/', views.organization_create_view, name='organization_create'),
    path('organizations/<uuid:org_id>/switch/', views.organization_switch_view, name='organization_switch'),
    path('organizations/<uuid:org_id>/settings/', views.organization_settings_view, name='organization_settings'),
    path('organizations/<uuid:org_id>/add-member/', views.organization_add_member_view, name='organization_add_member'),
    path('organizations/<uuid:org_id>/reset-password/<int:user_id>/', views.reset_member_password_view, name='reset_member_password'),
    path('organizations/<uuid:org_id>/deactivate-member/<int:user_id>/', views.deactivate_member_view, name='deactivate_member'),
    path('organizations/<uuid:org_id>/delete-member/<int:user_id>/', views.delete_member_view, name='delete_member'),

    # Branding
    path('organizations/<uuid:org_id>/upload-logo/', views.upload_organization_logo, name='upload_organization_logo'),
    path('organizations/<uuid:org_id>/save-branding/', views.save_organization_branding, name='save_organization_branding'),
    path('organizations/<uuid:org_id>/remove-logo/', views.remove_organization_logo, name='remove_organization_logo'),
    path('organizations/<uuid:org_id>/save-subdomain/', views.save_organization_subdomain, name='save_organization_subdomain'),
]
