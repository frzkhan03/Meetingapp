import uuid
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


# ==================== SOC 2: AUDIT TRAIL ====================

class AuditLog(models.Model):
    """
    SOC 2 compliant audit trail for all security-relevant actions.
    Immutable log - entries are never updated or deleted.
    """
    ACTION_CATEGORIES = [
        ('auth', 'Authentication'),
        ('user', 'User Management'),
        ('org', 'Organization Management'),
        ('meeting', 'Meeting Operations'),
        ('recording', 'Recording Operations'),
        ('billing', 'Billing Operations'),
        ('admin', 'Admin Operations'),
        ('data', 'Data Access/Export'),
        ('compliance', 'Compliance Actions'),
        ('security', 'Security Events'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    user_email = models.CharField(max_length=255, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)

    category = models.CharField(max_length=20, choices=ACTION_CATEGORIES, db_index=True)
    action = models.CharField(max_length=100, db_index=True)
    description = models.TextField()

    resource_type = models.CharField(max_length=100, blank=True)
    resource_id = models.CharField(max_length=255, blank=True)

    organization_id = models.UUIDField(null=True, blank=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)

    success = models.BooleanField(default=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['category', 'timestamp']),
            models.Index(fields=['user', 'timestamp']),
            models.Index(fields=['action', 'timestamp']),
        ]

    def __str__(self):
        return f"[{self.timestamp:%Y-%m-%d %H:%M}] {self.category}:{self.action} by {self.user_email or 'system'}"


# ==================== GDPR: CONSENT MANAGEMENT ====================

class ConsentRecord(models.Model):
    """
    GDPR Article 7 - Records of consent for data processing.
    Each consent action is logged immutably.
    """
    CONSENT_TYPES = [
        ('cookies_essential', 'Essential Cookies'),
        ('cookies_analytics', 'Analytics Cookies'),
        ('cookies_marketing', 'Marketing Cookies'),
        ('data_processing', 'Data Processing'),
        ('communications', 'Marketing Communications'),
        ('recording', 'Meeting Recording Consent'),
        ('transcript', 'Transcript Processing'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    session_id = models.CharField(max_length=255, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    consent_type = models.CharField(max_length=30, choices=CONSENT_TYPES)
    granted = models.BooleanField()
    timestamp = models.DateTimeField(default=timezone.now)

    version = models.CharField(max_length=20, default='1.0')
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['user', 'consent_type']),
            models.Index(fields=['session_id', 'consent_type']),
        ]

    def __str__(self):
        status = 'granted' if self.granted else 'withdrawn'
        return f"{self.consent_type} {status} at {self.timestamp:%Y-%m-%d %H:%M}"


class DataDeletionRequest(models.Model):
    """
    GDPR Article 17 - Right to Erasure requests.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('denied', 'Denied'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    user_email = models.EmailField()
    username = models.CharField(max_length=150)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    requested_at = models.DateTimeField(default=timezone.now)
    processed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    data_categories_deleted = models.JSONField(default=list, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-requested_at']

    def __str__(self):
        return f"Deletion request by {self.username} ({self.status})"


class DataExportRequest(models.Model):
    """
    GDPR Article 20 - Right to Data Portability.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('ready', 'Ready for Download'),
        ('downloaded', 'Downloaded'),
        ('expired', 'Expired'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    requested_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    file_path = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ['-requested_at']

    def __str__(self):
        return f"Export for {self.user.username} ({self.status})"


# ==================== SOC 2 / HIPAA: DATA RETENTION ====================

class DataRetentionPolicy(models.Model):
    """
    Configurable data retention policies for automatic cleanup.
    """
    DATA_TYPES = [
        ('recordings', 'Meeting Recordings'),
        ('transcripts', 'Meeting Transcripts'),
        ('connection_logs', 'Connection Logs'),
        ('audit_logs', 'Audit Logs'),
        ('chat_messages', 'Chat Messages'),
        ('session_data', 'Session Data'),
        ('export_files', 'Data Export Files'),
    ]

    data_type = models.CharField(max_length=30, choices=DATA_TYPES, unique=True)
    retention_days = models.IntegerField(help_text='Number of days to retain data. 0 = indefinite.')
    is_active = models.BooleanField(default=True)
    description = models.TextField(blank=True)
    last_cleanup_at = models.DateTimeField(null=True, blank=True)
    records_deleted_last_run = models.IntegerField(default=0)

    class Meta:
        verbose_name_plural = 'Data retention policies'

    def __str__(self):
        return f"{self.get_data_type_display()}: {self.retention_days} days"


# ==================== HIPAA: PHI ACCESS LOG ====================

class PHIAccessLog(models.Model):
    """
    HIPAA-required logging of access to Protected Health Information.
    Records who accessed what PHI data, when, and why.
    """
    ACCESS_TYPES = [
        ('view', 'Viewed'),
        ('create', 'Created'),
        ('update', 'Updated'),
        ('delete', 'Deleted'),
        ('export', 'Exported'),
        ('share', 'Shared'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    user_email = models.CharField(max_length=255)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    access_type = models.CharField(max_length=10, choices=ACCESS_TYPES)
    resource_type = models.CharField(max_length=100)
    resource_id = models.CharField(max_length=255)
    description = models.TextField()

    organization_id = models.UUIDField(null=True, blank=True)
    justification = models.TextField(blank=True, help_text='Reason for accessing PHI')

    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'PHI Access Log'
        verbose_name_plural = 'PHI Access Logs'

    def __str__(self):
        return f"[{self.timestamp:%Y-%m-%d %H:%M}] {self.access_type} {self.resource_type} by {self.user_email}"


# ==================== HIPAA: BAA TRACKING ====================

class BAARecord(models.Model):
    """
    Track Business Associate Agreements for HIPAA compliance.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending Signature'),
        ('active', 'Active'),
        ('expired', 'Expired'),
        ('terminated', 'Terminated'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization_name = models.CharField(max_length=255)
    organization_id = models.UUIDField(null=True, blank=True)
    contact_email = models.EmailField()

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    effective_date = models.DateField(null=True, blank=True)
    expiration_date = models.DateField(null=True, blank=True)
    signed_at = models.DateTimeField(null=True, blank=True)

    version = models.CharField(max_length=20, default='1.0')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'BAA Record'
        verbose_name_plural = 'BAA Records'
        ordering = ['-created_at']

    def __str__(self):
        return f"BAA: {self.organization_name} ({self.status})"
