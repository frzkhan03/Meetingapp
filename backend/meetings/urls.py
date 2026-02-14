from django.urls import path, re_path
from . import views

# Meeting code pattern: abc-defg-hij (3 letters - 4 letters - 3 letters)
# Also accepts old UUID format for backwards compatibility
MEETING_CODE_PATTERN = r'[a-z]{3}-[a-z]{4}-[a-z]{3}(?:-\d+)?|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'

urlpatterns = [
    path('schedule/', views.schedule_meeting_view, name='schedule_meeting'),
    path('meetings/', views.meetings_list_view, name='meetings_list'),
    re_path(rf'^meetingdetails/(?P<room_id>{MEETING_CODE_PATTERN})/$', views.meeting_details_view, name='meeting_details'),
    re_path(rf'^startmeeting/(?P<room_id>{MEETING_CODE_PATTERN})/$', views.start_meeting_view, name='start_meeting'),
    re_path(rf'^join/(?P<room_id>{MEETING_CODE_PATTERN})/$', views.join_meeting_guest_view, name='join_meeting_guest'),
    path('pendingroom/', views.pending_room_view, name='pending_room'),
    path('organization-meetings/', views.organization_meetings_view, name='organization_meetings'),

    # Personal room routes
    path('my-room/', views.my_room_view, name='my_room'),
    re_path(rf'^room/(?P<room_id>{MEETING_CODE_PATTERN})/join/$', views.join_personal_room_view, name='join_personal_room'),
    re_path(rf'^room/(?P<room_id>{MEETING_CODE_PATTERN})/toggle-lock/$', views.toggle_room_lock_view, name='toggle_room_lock'),
    re_path(rf'^room/(?P<room_id>{MEETING_CODE_PATTERN})/lock-status/$', views.get_room_lock_status_view, name='room_lock_status'),
    re_path(rf'^room/(?P<room_id>{MEETING_CODE_PATTERN})/send-alert/$', views.send_join_alert_view, name='send_join_alert'),
    re_path(rf'^room/(?P<room_id>{MEETING_CODE_PATTERN})/mark-approved/$', views.mark_guest_approved_view, name='mark_guest_approved'),
    path('all-rooms/', views.all_rooms_view, name='all_rooms'),

    # Recording routes
    path('upload-recording/', views.upload_recording_view, name='upload_recording'),
    path('my-recordings/', views.my_recordings_view, name='my_recordings'),
    path('recording/<int:recording_id>/download/', views.download_recording_view, name='download_recording'),

    # Transcript routes
    re_path(rf'^room/(?P<room_id>{MEETING_CODE_PATTERN})/save-transcript/$', views.save_transcript_view, name='save_transcript'),
    path('transcript/<int:transcript_id>/', views.view_transcript_view, name='view_transcript'),
]
