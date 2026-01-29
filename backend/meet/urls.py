"""
URL configuration for gmeet project.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from meetings.views import home_view, pending_room_view

urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),
    path('', home_view, name='home'),
    path('user/', include('users.urls')),
    path('meeting/', include('meetings.urls')),
    path('pendingroom/', pending_room_view, name='pending_room'),
]

# Serve static files during development
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])
