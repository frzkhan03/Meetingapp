"""
Celery tasks for compliance data retention enforcement.
"""
import logging
from datetime import timedelta
from celery import shared_task
from django.utils import timezone

logger = logging.getLogger('compliance.tasks')


@shared_task
def enforce_data_retention():
    """
    Run data retention policies - delete expired data per configured policies.
    Should be scheduled daily via Celery Beat.
    """
    from .models import DataRetentionPolicy

    policies = DataRetentionPolicy.objects.filter(is_active=True, retention_days__gt=0)

    for policy in policies:
        cutoff = timezone.now() - timedelta(days=policy.retention_days)
        deleted_count = 0

        try:
            if policy.data_type == 'recordings':
                from meetings.models import MeetingRecording
                deleted_count, _ = MeetingRecording.objects.filter(
                    created_at__lt=cutoff
                ).delete()

            elif policy.data_type == 'transcripts':
                from meetings.models import MeetingTranscript
                deleted_count, _ = MeetingTranscript.objects.filter(
                    created_at__lt=cutoff
                ).delete()

            elif policy.data_type == 'connection_logs':
                from meetings.models import ConnectionLog
                deleted_count, _ = ConnectionLog.objects.filter(
                    timestamp__lt=cutoff
                ).delete()

            elif policy.data_type == 'audit_logs':
                from .models import AuditLog
                deleted_count, _ = AuditLog.objects.filter(
                    timestamp__lt=cutoff
                ).delete()

            elif policy.data_type == 'session_data':
                from django.contrib.sessions.models import Session
                deleted_count, _ = Session.objects.filter(
                    expire_date__lt=cutoff
                ).delete()

            elif policy.data_type == 'export_files':
                from .models import DataExportRequest
                expired = DataExportRequest.objects.filter(
                    expires_at__lt=cutoff,
                    status__in=['ready', 'downloaded'],
                )
                deleted_count = expired.count()
                expired.update(status='expired')

            policy.last_cleanup_at = timezone.now()
            policy.records_deleted_last_run = deleted_count
            policy.save()

            if deleted_count > 0:
                logger.info(
                    'Retention policy %s: deleted %d records older than %d days',
                    policy.data_type, deleted_count, policy.retention_days,
                )

        except Exception as e:
            logger.error('Retention policy %s failed: %s', policy.data_type, e)


@shared_task
def process_deletion_requests():
    """
    Process pending account deletion requests (GDPR Article 17).
    Should be scheduled daily via Celery Beat.
    """
    from .models import DataDeletionRequest
    from .audit import log_audit_event

    pending = DataDeletionRequest.objects.filter(status='pending').select_related('user')

    for req in pending:
        if not req.user:
            req.status = 'completed'
            req.completed_at = timezone.now()
            req.notes = 'User already deleted.'
            req.save()
            continue

        req.status = 'processing'
        req.processed_at = timezone.now()
        req.save()

        user = req.user
        deleted_categories = []

        try:
            # Delete meetings
            from meetings.models import Meeting
            Meeting.objects.filter(author=user).delete()
            deleted_categories.append('meetings')

            # Delete recordings
            from meetings.models import MeetingRecording
            MeetingRecording.objects.filter(recorded_by=user).delete()
            deleted_categories.append('recordings')

            # Delete transcripts
            from meetings.models import MeetingTranscript
            MeetingTranscript.objects.filter(created_by=user).delete()
            deleted_categories.append('transcripts')

            # Delete organization memberships
            from users.models import OrganizationMembership
            OrganizationMembership.objects.filter(user=user).delete()
            deleted_categories.append('organization_memberships')

            # Anonymize audit logs (retain for compliance but remove PII)
            from .models import AuditLog
            AuditLog.objects.filter(user=user).update(
                user=None,
                user_email='[deleted]',
                ip_address=None,
            )
            deleted_categories.append('audit_logs_anonymized')

            # Delete the user account
            username = user.username
            user.delete()
            deleted_categories.append('user_account')

            req.status = 'completed'
            req.completed_at = timezone.now()
            req.data_categories_deleted = deleted_categories
            req.save()

            log_audit_event(
                category='compliance',
                action='deletion_completed',
                description=f'Account deletion completed for {username}',
                resource_type='User',
                resource_id=str(req.id),
            )

        except Exception as e:
            logger.error('Deletion request %s failed: %s', req.id, e)
            req.status = 'pending'
            req.notes = f'Processing failed: will retry. Error: {type(e).__name__}'
            req.save()
