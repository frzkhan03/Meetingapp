from django.contrib import admin
from .models import (
    AuditLog, ConsentRecord, DataDeletionRequest,
    DataExportRequest, DataRetentionPolicy, PHIAccessLog, BAARecord,
)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'category', 'action', 'user_email', 'ip_address', 'success')
    list_filter = ('category', 'success', 'timestamp')
    search_fields = ('user_email', 'action', 'description', 'ip_address')
    readonly_fields = (
        'id', 'timestamp', 'user', 'user_email', 'ip_address', 'user_agent',
        'category', 'action', 'description', 'resource_type', 'resource_id',
        'organization_id', 'metadata', 'success',
    )
    date_hierarchy = 'timestamp'
    ordering = ('-timestamp',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ConsentRecord)
class ConsentRecordAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'user', 'consent_type', 'granted', 'ip_address')
    list_filter = ('consent_type', 'granted', 'timestamp')
    search_fields = ('user__username', 'user__email', 'session_id')
    readonly_fields = (
        'id', 'user', 'session_id', 'ip_address', 'consent_type',
        'granted', 'timestamp', 'version', 'metadata',
    )
    date_hierarchy = 'timestamp'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(DataDeletionRequest)
class DataDeletionRequestAdmin(admin.ModelAdmin):
    list_display = ('username', 'user_email', 'status', 'requested_at', 'completed_at')
    list_filter = ('status', 'requested_at')
    search_fields = ('username', 'user_email')
    readonly_fields = ('id', 'user', 'user_email', 'username', 'requested_at')


@admin.register(DataExportRequest)
class DataExportRequestAdmin(admin.ModelAdmin):
    list_display = ('user', 'status', 'requested_at', 'completed_at', 'expires_at')
    list_filter = ('status', 'requested_at')
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('id', 'user', 'requested_at')


@admin.register(DataRetentionPolicy)
class DataRetentionPolicyAdmin(admin.ModelAdmin):
    list_display = ('data_type', 'retention_days', 'is_active', 'last_cleanup_at', 'records_deleted_last_run')
    list_filter = ('is_active',)
    list_editable = ('retention_days', 'is_active')


@admin.register(PHIAccessLog)
class PHIAccessLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'user_email', 'access_type', 'resource_type', 'resource_id')
    list_filter = ('access_type', 'resource_type', 'timestamp')
    search_fields = ('user_email', 'resource_id', 'description')
    readonly_fields = (
        'id', 'timestamp', 'user', 'user_email', 'ip_address',
        'access_type', 'resource_type', 'resource_id', 'description',
        'organization_id', 'justification',
    )
    date_hierarchy = 'timestamp'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(BAARecord)
class BAARecordAdmin(admin.ModelAdmin):
    list_display = ('organization_name', 'contact_email', 'status', 'effective_date', 'expiration_date')
    list_filter = ('status',)
    search_fields = ('organization_name', 'contact_email')
