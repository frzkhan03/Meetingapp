"""
SOC 2 / HIPAA: Django signals for audit logging of model changes.
"""
import logging
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.contrib.auth.models import User

logger = logging.getLogger('compliance.signals')


@receiver(user_logged_in)
def on_user_login(sender, request, user, **kwargs):
    from .audit import log_audit_event
    log_audit_event(
        category='auth',
        action='session_start',
        description=f'Session started for {user.username}',
        request=request,
        user=user,
    )


@receiver(user_logged_out)
def on_user_logout(sender, request, user, **kwargs):
    from .audit import log_audit_event
    if user:
        log_audit_event(
            category='auth',
            action='session_end',
            description=f'Session ended for {user.username}',
            request=request,
            user=user,
        )


@receiver(user_login_failed)
def on_login_failed(sender, credentials, request, **kwargs):
    from .audit import log_audit_event
    log_audit_event(
        category='security',
        action='login_failed',
        description=f'Failed login attempt for: {credentials.get("username", "unknown")}',
        request=request,
        success=False,
        metadata={'username': credentials.get('username', '')},
    )


@receiver(post_save, sender=User)
def on_user_saved(sender, instance, created, **kwargs):
    from .audit import log_audit_event
    if created:
        log_audit_event(
            category='user',
            action='user_created',
            description=f'User account created: {instance.username}',
            user=instance,
            resource_type='User',
            resource_id=str(instance.id),
        )


@receiver(post_delete, sender=User)
def on_user_deleted(sender, instance, **kwargs):
    from .audit import log_audit_event
    log_audit_event(
        category='user',
        action='user_deleted',
        description=f'User account deleted: {instance.username} ({instance.email})',
        resource_type='User',
        resource_id=str(instance.id),
    )
