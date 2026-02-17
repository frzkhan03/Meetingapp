import json
import csv
import io
import zipfile
import logging
from datetime import timedelta
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.conf import settings
from .models import (
    ConsentRecord, DataDeletionRequest, DataExportRequest,
    AuditLog, DataRetentionPolicy,
)
from .audit import log_audit_event

logger = logging.getLogger(__name__)


# ==================== PRIVACY POLICY ====================

def privacy_policy_view(request):
    return render(request, 'compliance/privacy_policy.html', {
        'organization_name': 'PyTalk',
        'contact_email': getattr(settings, 'COMPLIANCE_CONTACT_EMAIL', 'privacy@pytalk.com'),
        'dpo_email': getattr(settings, 'DPO_EMAIL', 'dpo@pytalk.com'),
    })


def terms_of_service_view(request):
    return render(request, 'compliance/terms_of_service.html')


# ==================== COOKIE CONSENT ====================

@require_POST
def cookie_consent_view(request):
    """Record cookie consent preferences (GDPR Article 7)."""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    essential = True  # Always required
    analytics = data.get('analytics', False)
    marketing = data.get('marketing', False)

    user = request.user if request.user.is_authenticated else None
    session_id = request.session.session_key or ''
    ip = _get_client_ip(request)

    for consent_type, granted in [
        ('cookies_essential', essential),
        ('cookies_analytics', analytics),
        ('cookies_marketing', marketing),
    ]:
        ConsentRecord.objects.create(
            user=user,
            session_id=session_id,
            ip_address=ip,
            consent_type=consent_type,
            granted=granted,
        )

    # Set cookie to remember consent
    response = JsonResponse({'success': True})
    consent_value = json.dumps({
        'essential': essential,
        'analytics': analytics,
        'marketing': marketing,
        'timestamp': timezone.now().isoformat(),
    })
    response.set_cookie(
        'cookie_consent',
        consent_value,
        max_age=365 * 24 * 60 * 60,  # 1 year
        secure=getattr(settings, 'SESSION_COOKIE_SECURE', False),
        httponly=False,  # JS needs to read this
        samesite='Lax',
    )
    return response


# ==================== GDPR: ACCOUNT DELETION ====================

@login_required
def delete_account_view(request):
    """GDPR Article 17 - Right to Erasure."""
    if request.method == 'GET':
        # Check for existing pending request
        existing = DataDeletionRequest.objects.filter(
            user=request.user,
            status__in=['pending', 'processing'],
        ).first()
        return render(request, 'compliance/delete_account.html', {
            'existing_request': existing,
        })

    if request.method == 'POST':
        confirm = request.POST.get('confirm_delete')
        if confirm != 'DELETE':
            return render(request, 'compliance/delete_account.html', {
                'error': 'Please type DELETE to confirm.',
            })

        # Create deletion request
        DataDeletionRequest.objects.create(
            user=request.user,
            user_email=request.user.email,
            username=request.user.username,
            status='pending',
        )

        log_audit_event(
            category='compliance',
            action='deletion_request',
            description=f'Account deletion requested by {request.user.username}',
            request=request,
            resource_type='User',
            resource_id=str(request.user.id),
        )

        return render(request, 'compliance/delete_account.html', {
            'success': True,
        })

    return redirect('delete_account')


# ==================== GDPR: DATA EXPORT ====================

@login_required
def data_export_view(request):
    """GDPR Article 20 - Right to Data Portability."""
    recent_exports = DataExportRequest.objects.filter(
        user=request.user,
    ).order_by('-requested_at')[:5]

    return render(request, 'compliance/data_export.html', {
        'recent_exports': recent_exports,
    })


@login_required
@require_POST
def request_data_export(request):
    """Initiate a data export request."""
    # Rate limit: max 1 export per 24 hours
    recent = DataExportRequest.objects.filter(
        user=request.user,
        requested_at__gte=timezone.now() - timedelta(hours=24),
    ).exists()

    if recent:
        return JsonResponse({
            'error': 'You can only request one export per 24 hours.',
        }, status=429)

    export_req = DataExportRequest.objects.create(
        user=request.user,
        status='processing',
    )

    log_audit_event(
        category='data',
        action='data_export_request',
        description=f'Data export requested by {request.user.username}',
        request=request,
        resource_type='DataExportRequest',
        resource_id=str(export_req.id),
    )

    # Generate export immediately (for small datasets)
    try:
        _generate_data_export(request.user, export_req)
        return JsonResponse({'success': True, 'export_id': str(export_req.id)})
    except Exception as e:
        logger.error('Data export failed for user %s: %s', request.user.id, e)
        export_req.status = 'pending'
        export_req.save()
        return JsonResponse({'error': 'Export is being processed. Please check back later.'})


@login_required
def download_data_export(request, export_id):
    """Download a completed data export."""
    export_req = DataExportRequest.objects.filter(
        id=export_id,
        user=request.user,
        status='ready',
    ).first()

    if not export_req:
        return JsonResponse({'error': 'Export not found or not ready.'}, status=404)

    # Check expiry
    if export_req.expires_at and export_req.expires_at < timezone.now():
        export_req.status = 'expired'
        export_req.save()
        return JsonResponse({'error': 'Export has expired. Please request a new one.'}, status=410)

    # Generate the ZIP in memory
    user = request.user
    buffer = io.BytesIO()

    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        # User profile
        profile_data = {
            'username': user.username,
            'email': user.email,
            'date_joined': user.date_joined.isoformat(),
            'last_login': user.last_login.isoformat() if user.last_login else None,
        }
        zf.writestr('profile.json', json.dumps(profile_data, indent=2))

        # Organization memberships
        from users.models import OrganizationMembership
        memberships = list(OrganizationMembership.objects.filter(
            user=user
        ).values('organization__name', 'role', 'joined_at', 'is_active'))
        for m in memberships:
            m['joined_at'] = m['joined_at'].isoformat() if m['joined_at'] else None
        zf.writestr('organizations.json', json.dumps(memberships, indent=2, default=str))

        # Meetings
        from meetings.models import Meeting
        meetings = list(Meeting.objects.filter(
            author=user
        ).values('name', 'room_id', 'start_time', 'end_time', 'created_at'))
        for m in meetings:
            for k in ('start_time', 'end_time', 'created_at'):
                if m[k]:
                    m[k] = m[k].isoformat()
        zf.writestr('meetings.json', json.dumps(meetings, indent=2, default=str))

        # Recordings metadata
        from meetings.models import MeetingRecording
        recordings = list(MeetingRecording.objects.filter(
            recorded_by=user
        ).values('recording_name', 'file_size', 'duration', 'created_at'))
        for r in recordings:
            if r['created_at']:
                r['created_at'] = r['created_at'].isoformat()
        zf.writestr('recordings.json', json.dumps(recordings, indent=2, default=str))

        # Transcripts
        from meetings.models import MeetingTranscript
        transcripts = list(MeetingTranscript.objects.filter(
            created_by=user
        ).values('room_id', 'created_at', 'entries'))
        for t in transcripts:
            if t['created_at']:
                t['created_at'] = t['created_at'].isoformat()
        zf.writestr('transcripts.json', json.dumps(transcripts, indent=2, default=str))

        # Consent records
        consents = list(ConsentRecord.objects.filter(
            user=user
        ).values('consent_type', 'granted', 'timestamp', 'version'))
        for c in consents:
            if c['timestamp']:
                c['timestamp'] = c['timestamp'].isoformat()
        zf.writestr('consent_records.json', json.dumps(consents, indent=2, default=str))

    export_req.status = 'downloaded'
    export_req.save()

    log_audit_event(
        category='data',
        action='data_export_downloaded',
        description=f'Data export downloaded by {user.username}',
        request=request,
        resource_type='DataExportRequest',
        resource_id=str(export_req.id),
    )

    buffer.seek(0)
    response = HttpResponse(buffer.read(), content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="pytalk_data_export_{user.username}.zip"'
    return response


def _generate_data_export(user, export_req):
    """Mark export as ready (actual download generates data on-the-fly)."""
    export_req.status = 'ready'
    export_req.completed_at = timezone.now()
    export_req.expires_at = timezone.now() + timedelta(days=7)
    export_req.save()


# ==================== COMPLIANCE DASHBOARD ====================

@login_required
def compliance_settings_view(request):
    """User-facing compliance/privacy settings page."""
    consents = {}
    for ct in ['cookies_analytics', 'cookies_marketing', 'communications', 'recording', 'transcript']:
        latest = ConsentRecord.objects.filter(
            user=request.user,
            consent_type=ct,
        ).order_by('-timestamp').first()
        consents[ct] = latest.granted if latest else False

    deletion_request = DataDeletionRequest.objects.filter(
        user=request.user,
        status__in=['pending', 'processing'],
    ).first()

    return render(request, 'compliance/settings.html', {
        'consents': consents,
        'deletion_request': deletion_request,
    })


@login_required
@require_POST
def update_consent_view(request):
    """Update user consent preferences."""
    consent_type = request.POST.get('consent_type')
    granted = request.POST.get('granted') == 'true'

    valid_types = ['cookies_analytics', 'cookies_marketing', 'communications', 'recording', 'transcript']
    if consent_type not in valid_types:
        return JsonResponse({'error': 'Invalid consent type.'}, status=400)

    ConsentRecord.objects.create(
        user=request.user,
        ip_address=_get_client_ip(request),
        consent_type=consent_type,
        granted=granted,
    )

    log_audit_event(
        category='compliance',
        action='consent_updated',
        description=f'{request.user.username} {"granted" if granted else "withdrew"} consent for {consent_type}',
        request=request,
    )

    return JsonResponse({'success': True})


# ==================== ADMIN COMPLIANCE DASHBOARD ====================

@login_required
def admin_compliance_dashboard(request):
    """Admin-facing compliance overview dashboard."""
    if not request.user.is_staff:
        return JsonResponse({'error': 'Access denied'}, status=403)

    # Gather compliance statistics
    from django.contrib.auth.models import User
    from .models import PHIAccessLog, BAARecord

    now = timezone.now()
    last_30_days = now - timedelta(days=30)

    stats = {
        'total_users': User.objects.count(),
        'audit_logs_30d': AuditLog.objects.filter(timestamp__gte=last_30_days).count(),
        'failed_logins_30d': AuditLog.objects.filter(
            category='security', action='login_failed', timestamp__gte=last_30_days
        ).count(),
        'deletion_requests_pending': DataDeletionRequest.objects.filter(status='pending').count(),
        'export_requests_pending': DataExportRequest.objects.filter(status__in=['pending', 'processing']).count(),
        'phi_access_30d': PHIAccessLog.objects.filter(timestamp__gte=last_30_days).count(),
        'active_baas': BAARecord.objects.filter(status='active').count(),
        'retention_policies': list(DataRetentionPolicy.objects.values(
            'data_type', 'retention_days', 'is_active', 'last_cleanup_at'
        )),
    }

    recent_audit = AuditLog.objects.order_by('-timestamp')[:20]
    recent_phi = PHIAccessLog.objects.order_by('-timestamp')[:10]

    return render(request, 'compliance/admin_dashboard.html', {
        'stats': stats,
        'recent_audit': recent_audit,
        'recent_phi': recent_phi,
    })


def pci_compliance_view(request):
    """PCI DSS SAQ A compliance documentation page."""
    return render(request, 'compliance/pci_compliance.html')


def _get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')
