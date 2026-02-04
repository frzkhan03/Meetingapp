from django.apps import AppConfig


class BillingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'billing'
    verbose_name = 'Billing & Subscriptions'

    def ready(self):
        import billing.signals  # noqa: F401

        # Add billing dashboard URL to admin site
        from django.contrib import admin
        from django.urls import path

        original_get_urls = admin.AdminSite.get_urls

        def patched_get_urls(site_self):
            from billing.admin_views import billing_dashboard_view
            custom_urls = [
                path('billing-dashboard/',
                     site_self.admin_view(billing_dashboard_view),
                     name='billing_dashboard'),
            ]
            return custom_urls + original_get_urls(site_self)

        admin.AdminSite.get_urls = patched_get_urls
