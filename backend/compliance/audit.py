"""
SOC 2 Audit Trail - Utility functions for logging audit events.
"""
import logging
from django.utils import timezone

logger = logging.getLogger('compliance.audit')


def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


def log_audit_event(
    category,
    action,
    description,
    request=None,
    user=None,
    resource_type='',
    resource_id='',
    organization_id=None,
    metadata=None,
    success=True,
):
    """
    Log an audit event to the database.
    Call this from views, signals, or middleware for SOC 2 compliance.
    """
    from .models import AuditLog

    if request and not user:
        user = request.user if request.user.is_authenticated else None

    try:
        AuditLog.objects.create(
            timestamp=timezone.now(),
            user=user,
            user_email=getattr(user, 'email', '') if user else '',
            ip_address=get_client_ip(request) if request else None,
            user_agent=(request.META.get('HTTP_USER_AGENT', '')[:500] if request else ''),
            category=category,
            action=action,
            description=description,
            resource_type=resource_type,
            resource_id=str(resource_id),
            organization_id=organization_id,
            metadata=metadata or {},
            success=success,
        )
    except Exception as e:
        logger.error('Failed to write audit log: %s', e)


def log_phi_access(
    access_type,
    resource_type,
    resource_id,
    description,
    request=None,
    user=None,
    organization_id=None,
    justification='',
):
    """
    HIPAA: Log access to Protected Health Information.
    """
    from .models import PHIAccessLog

    if request and not user:
        user = request.user if request.user.is_authenticated else None

    try:
        PHIAccessLog.objects.create(
            timestamp=timezone.now(),
            user=user,
            user_email=getattr(user, 'email', '') if user else '',
            ip_address=get_client_ip(request) if request else None,
            access_type=access_type,
            resource_type=resource_type,
            resource_id=str(resource_id),
            description=description,
            organization_id=organization_id,
            justification=justification,
        )
    except Exception as e:
        logger.error('Failed to write PHI access log: %s', e)
