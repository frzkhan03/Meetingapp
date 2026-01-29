from django.contrib import admin
from .models import Meeting, UserMeetingPacket, MeetingRecording


@admin.register(Meeting)
class MeetingAdmin(admin.ModelAdmin):
    list_display = ['name', 'organization', 'room_id', 'author_name', 'start_time', 'end_time', 'is_private']
    list_filter = ['organization', 'start_time', 'is_private', 'require_approval']
    search_fields = ['name', 'author_name', 'organization__name']
    readonly_fields = ['room_id', 'created_at', 'updated_at']


@admin.register(UserMeetingPacket)
class UserMeetingPacketAdmin(admin.ModelAdmin):
    list_display = ['user', 'room_id', 'meeting_name', 'created_at']
    list_filter = ['created_at']
    search_fields = ['user__username', 'meeting_name']


@admin.register(MeetingRecording)
class MeetingRecordingAdmin(admin.ModelAdmin):
    list_display = ['meeting', 'recorded_by', 'duration', 'file_size', 'created_at']
    list_filter = ['created_at', 'meeting__organization']
    search_fields = ['meeting__name']
