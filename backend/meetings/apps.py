from django.apps import AppConfig


class MeetingsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'meetings'
    verbose_name = 'Meetings & Rooms'

    def ready(self):
        # Add connection analytics dashboard URL to admin site
        from django.contrib import admin
        from django.urls import path

        original_get_urls = admin.AdminSite.get_urls

        def patched_get_urls(site_self):
            from meetings.admin_views import connection_analytics_view
            custom_urls = [
                path('connection-analytics/',
                     site_self.admin_view(connection_analytics_view),
                     name='connection_analytics'),
            ]
            return custom_urls + original_get_urls(site_self)

        admin.AdminSite.get_urls = patched_get_urls
