"""
SOC 2 Audit Middleware - Automatically logs security-relevant HTTP actions.
"""
from django.conf import settings
from django.utils.deprecation import MiddlewareMixin
from .audit import log_audit_event, get_client_ip


class AuditTrailMiddleware(MiddlewareMixin):
    """
    Automatically logs security-relevant actions for SOC 2 compliance.
    Covers authentication, admin access, data operations, and billing.
    """

    # Paths and their audit categories
    AUDIT_PATHS = {
        '/user/login/': ('auth', 'login'),
        '/user/logout/': ('auth', 'logout'),
        '/user/register/': ('auth', 'register'),
    }

    def process_response(self, request, response):
        path = request.path

        # Log authentication events
        if path in self.AUDIT_PATHS and request.method == 'POST':
            category, action = self.AUDIT_PATHS[path]
            success = response.status_code in (200, 302)

            if action == 'login':
                username = request.POST.get('username', 'unknown')
                if response.status_code == 302:
                    desc = f'Successful login for user: {username}'
                else:
                    desc = f'Failed login attempt for user: {username}'
                    success = False
                log_audit_event(
                    category=category,
                    action=action,
                    description=desc,
                    request=request,
                    success=success,
                    metadata={'username': username},
                )
            elif action == 'register':
                if response.status_code == 302:
                    username = request.POST.get('username', 'unknown')
                    log_audit_event(
                        category=category,
                        action=action,
                        description=f'New user registered: {username}',
                        request=request,
                        metadata={'username': username},
                    )
            elif action == 'logout':
                log_audit_event(
                    category=category,
                    action=action,
                    description='User logged out',
                    request=request,
                )

        # Log admin access
        admin_path = f'/{getattr(settings, "ADMIN_URL", "secure-admin/").strip("/")}'
        if path.startswith(admin_path) and request.method in ('POST', 'DELETE'):
            log_audit_event(
                category='admin',
                action='admin_change',
                description=f'Admin action: {request.method} {path}',
                request=request,
                metadata={'status_code': response.status_code},
            )

        # Log organization management
        if '/organizations/' in path and request.method == 'POST':
            if 'add-member' in path:
                log_audit_event(
                    category='org',
                    action='add_member',
                    description=f'Member added via {path}',
                    request=request,
                )
            elif 'reset-password' in path:
                log_audit_event(
                    category='user',
                    action='password_reset',
                    description=f'Password reset via {path}',
                    request=request,
                )
            elif 'delete-member' in path:
                log_audit_event(
                    category='org',
                    action='delete_member',
                    description=f'Member deleted via {path}',
                    request=request,
                )

        # Log recording operations
        if '/upload-recording/' in path and request.method == 'POST':
            log_audit_event(
                category='recording',
                action='upload',
                description='Recording uploaded',
                request=request,
                success=response.status_code == 200,
            )
        if '/download-recording/' in path:
            log_audit_event(
                category='recording',
                action='download',
                description=f'Recording download: {path}',
                request=request,
            )

        # Log data exports
        if '/compliance/export/' in path and request.method == 'POST':
            log_audit_event(
                category='data',
                action='data_export_request',
                description='User requested data export (GDPR)',
                request=request,
            )

        # Log account deletion requests
        if '/compliance/delete-account/' in path and request.method == 'POST':
            log_audit_event(
                category='compliance',
                action='deletion_request',
                description='User requested account deletion (GDPR)',
                request=request,
            )

        return response
