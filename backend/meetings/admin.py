from django.contrib import admin
from django.db.models import Count
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline
from .models import Meeting, UserMeetingPacket, MeetingRecording, PersonalRoom, BreakoutRoom, MeetingTranscript, ConnectionLog


class MeetingRecordingInline(TabularInline):
    model = MeetingRecording
    extra = 0
    fields = ['recording_name', 'recorded_by', 'formatted_size', 'formatted_duration', 'created_at']
    readonly_fields = ['recording_name', 'recorded_by', 'formatted_size', 'formatted_duration', 'created_at']

    @admin.display(description='Size')
    def formatted_size(self, obj):
        if not obj.file_size:
            return '-'
        if obj.file_size < 1024 * 1024:
            return f"{obj.file_size / 1024:.1f} KB"
        return f"{obj.file_size / (1024 * 1024):.1f} MB"

    @admin.display(description='Duration')
    def formatted_duration(self, obj):
        if not obj.duration:
            return '-'
        if obj.duration < 60:
            return f"{obj.duration}s"
        minutes = obj.duration // 60
        seconds = obj.duration % 60
        return f"{minutes}m {seconds}s"


class BreakoutRoomMeetingInline(TabularInline):
    model = BreakoutRoom
    fk_name = 'parent_meeting'
    extra = 0
    fields = ['name', 'room_id', 'is_active', 'created_at', 'closed_at']
    readonly_fields = ['room_id', 'created_at']


class BreakoutRoomPersonalInline(TabularInline):
    model = BreakoutRoom
    fk_name = 'parent_room'
    extra = 0
    fields = ['name', 'room_id', 'is_active', 'created_at', 'closed_at']
    readonly_fields = ['room_id', 'created_at']


@admin.register(Meeting)
class MeetingAdmin(ModelAdmin):
    list_display = [
        'name', 'organization', 'room_id', 'author_name',
        'meeting_time', 'recurrence', 'is_private',
        'require_approval', 'max_participants', 'recording_count',
    ]
    list_filter = [
        'organization', 'is_private', 'require_approval',
        'recurrence', 'is_all_day', 'start_time',
    ]
    search_fields = ['name', 'author_name', 'room_id', 'organization__name']
    readonly_fields = ['room_id', 'attendee_token', 'guest_join_link', 'created_at', 'updated_at']
    autocomplete_fields = ['organization', 'author']
    filter_horizontal = ['users']
    date_hierarchy = 'start_time'
    list_per_page = 25
    inlines = [MeetingRecordingInline, BreakoutRoomMeetingInline]

    fieldsets = (
        ('Meeting Info', {
            'fields': ('name', 'description', 'organization', 'room_id'),
        }),
        ('Schedule', {
            'fields': ('start_time', 'end_time', 'is_all_day', 'recurrence', 'location'),
        }),
        ('Host & Participants', {
            'fields': ('author', 'author_name', 'users', 'attendees_emails', 'max_participants'),
        }),
        ('Settings', {
            'fields': ('is_private', 'require_approval'),
        }),
        ('Access Links', {
            'fields': ('attendee_token', 'guest_join_link'),
            'classes': ('collapse',),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _recording_count=Count('recordings', distinct=True)
        )

    @admin.display(description='Time')
    def meeting_time(self, obj):
        if obj.is_all_day:
            return format_html('<em>All Day</em> {}', obj.start_time.strftime('%b %d, %Y'))
        return format_html(
            '{} - {}',
            obj.start_time.strftime('%b %d %H:%M'),
            obj.end_time.strftime('%H:%M'),
        )

    @admin.display(description='Recs', ordering='_recording_count')
    def recording_count(self, obj):
        return obj._recording_count

    @admin.display(description='Guest Join Link')
    def guest_join_link(self, obj):
        link = obj.get_guest_join_link()
        return format_html('<a href="{}" target="_blank">{}</a>', link, link)


@admin.register(PersonalRoom)
class PersonalRoomAdmin(ModelAdmin):
    list_display = [
        'user', 'organization', 'room_name', 'room_id',
        'is_active', 'is_locked', 'created_at',
    ]
    list_filter = ['is_active', 'is_locked', 'organization']
    search_fields = ['user__username', 'room_name', 'room_id', 'organization__name']
    readonly_fields = [
        'room_id', 'moderator_token', 'attendee_token',
        'moderator_link', 'attendee_link', 'created_at', 'updated_at',
    ]
    autocomplete_fields = ['user', 'organization']
    list_per_page = 25
    inlines = [BreakoutRoomPersonalInline]

    fieldsets = (
        ('Room Info', {
            'fields': ('user', 'organization', 'room_name', 'room_id'),
        }),
        ('Settings', {
            'fields': ('is_active', 'is_locked'),
        }),
        ('Access Tokens & Links', {
            'fields': ('moderator_token', 'attendee_token', 'moderator_link', 'attendee_link'),
            'classes': ('collapse',),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    @admin.display(description='Moderator Link')
    def moderator_link(self, obj):
        link = obj.get_moderator_link()
        return format_html('<a href="{}" target="_blank">{}</a>', link, link)

    @admin.display(description='Attendee Link')
    def attendee_link(self, obj):
        link = obj.get_attendee_link()
        return format_html('<a href="{}" target="_blank">{}</a>', link, link)


@admin.register(BreakoutRoom)
class BreakoutRoomAdmin(ModelAdmin):
    list_display = ['name', 'room_id', 'parent_room', 'parent_meeting', 'is_active', 'created_at', 'closed_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'room_id']
    readonly_fields = ['id', 'room_id', 'created_at']

    fieldsets = (
        ('Breakout Room', {
            'fields': ('id', 'name', 'room_id'),
        }),
        ('Parent', {
            'fields': ('parent_room', 'parent_meeting'),
        }),
        ('Status', {
            'fields': ('is_active', 'created_at', 'closed_at'),
        }),
    )


@admin.register(UserMeetingPacket)
class UserMeetingPacketAdmin(ModelAdmin):
    list_display = ['user', 'room_id', 'meeting_name', 'author', 'created_at']
    list_filter = ['created_at']
    search_fields = ['user__username', 'meeting_name', 'room_id']
    autocomplete_fields = ['user', 'meeting', 'author']
    readonly_fields = ['created_at']


@admin.register(MeetingRecording)
class MeetingRecordingAdmin(ModelAdmin):
    list_display = [
        'recording_name_display', 'meeting', 'organization',
        'recorded_by', 'formatted_duration', 'formatted_size',
        'storage_location', 'created_at',
    ]
    list_filter = ['created_at', 'organization']
    search_fields = ['recording_name', 'meeting__name', 'organization__name']
    autocomplete_fields = ['meeting', 'organization', 'recorded_by']
    readonly_fields = ['created_at']

    fieldsets = (
        ('Recording Info', {
            'fields': ('recording_name', 'meeting', 'organization', 'recorded_by'),
        }),
        ('File Details', {
            'fields': ('file_path', 's3_key', 'file_size', 'duration'),
        }),
        ('Timestamps', {
            'fields': ('created_at',),
        }),
    )

    @admin.display(description='Name')
    def recording_name_display(self, obj):
        if obj.recording_name:
            return obj.recording_name
        if obj.s3_key:
            return obj.s3_key.split('/')[-1]
        return obj.file_path.split('/')[-1] if obj.file_path else '-'

    @admin.display(description='Duration')
    def formatted_duration(self, obj):
        if obj.duration < 60:
            return f"{obj.duration}s"
        minutes = obj.duration // 60
        seconds = obj.duration % 60
        if minutes >= 60:
            hours = minutes // 60
            minutes = minutes % 60
            return f"{hours}h {minutes}m"
        return f"{minutes}m {seconds}s"

    @admin.display(description='Size')
    def formatted_size(self, obj):
        if obj.file_size == 0:
            return '-'
        if obj.file_size < 1024 * 1024:
            return f"{obj.file_size / 1024:.1f} KB"
        if obj.file_size < 1024 * 1024 * 1024:
            return f"{obj.file_size / (1024 * 1024):.1f} MB"
        return f"{obj.file_size / (1024 * 1024 * 1024):.2f} GB"

    @admin.display(description='Storage')
    def storage_location(self, obj):
        if obj.s3_key:
            return format_html('<span style="color:#22c55e;">{}</span>', 'S3')
        return format_html('<span style="color:#6b7280;">{}</span>', 'Local')


@admin.register(MeetingTranscript)
class MeetingTranscriptAdmin(ModelAdmin):
    list_display = ['room_id', 'meeting', 'organization', 'status', 'entry_count', 'created_by', 'created_at']
    list_filter = ['status', 'created_at', 'organization']
    search_fields = ['room_id', 'meeting__name', 'organization__name']
    autocomplete_fields = ['meeting', 'organization', 'created_by']
    readonly_fields = ['created_at', 'updated_at']
    list_per_page = 25

    @admin.display(description='Entries')
    def entry_count(self, obj):
        return len(obj.entries) if obj.entries else 0


@admin.register(ConnectionLog)
class ConnectionLogAdmin(ModelAdmin):
    list_display = [
        'room_id', 'user_id', 'organization', 'avg_bitrate_kbps',
        'avg_rtt_ms', 'packet_loss_display', 'duration_seconds',
        'reconnection_count', 'browser', 'device_type', 'created_at',
    ]
    list_filter = ['organization', 'device_type', 'created_at']
    search_fields = ['room_id', 'user_id', 'browser']
    readonly_fields = ['created_at']
    date_hierarchy = 'created_at'
    list_per_page = 50

    @admin.display(description='Packet Loss')
    def packet_loss_display(self, obj):
        pct = obj.packet_loss_pct
        if pct > 5:
            color = '#ef4444'
        elif pct > 1:
            color = '#f59e0b'
        else:
            color = '#22c55e'
        return format_html('<span style="color:{};">{}%</span>', color, round(pct, 2))
