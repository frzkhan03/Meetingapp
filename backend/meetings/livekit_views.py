"""
LiveKit API Views
Endpoints for token generation, room management, and recording control
"""

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
import json
import logging

from meetings.models import Meeting, PersonalRoom, MeetingRecording
from meetings.livekit_service import get_livekit_service

logger = logging.getLogger(__name__)


@require_http_methods(["POST"])
def get_livekit_token(request):
    """
    Generate LiveKit access token for joining a meeting

    POST /api/livekit/token/
    Body: {
        "room_id": "abc-defg-hij",
        "is_moderator": false  // optional
    }

    Returns: {
        "token": "eyJhbGc...",
        "url": "wss://your-project.livekit.cloud",
        "room_id": "abc-defg-hij"
    }
    """
    try:
        data = json.loads(request.body)
        room_id = data.get('room_id')
        is_moderator = data.get('is_moderator', False)

        if not room_id:
            return JsonResponse({'error': 'room_id is required'}, status=400)

        # Get user identity
        if request.user.is_authenticated:
            user_id = str(request.user.id)
            username = request.user.username

            # Verify room exists and user has access
            room_access = check_room_access(request.user, room_id)
            if not room_access['allowed']:
                return JsonResponse({'error': room_access['reason']}, status=403)

            if room_access.get('is_host'):
                is_moderator = True
        else:
            # Guest user — get identity from session (set by join_meeting_guest_view)
            user_id = request.session.get(f'guest_id_meeting_{room_id}', f'guest_{room_id[:8]}')
            username = request.session.get(f'display_name_meeting_{room_id}', 'Guest')
            is_moderator = False

        # Generate token
        livekit = get_livekit_service()
        token = livekit.generate_token(
            room_id=room_id,
            user_id=user_id,
            username=username,
            is_moderator=is_moderator
        )

        return JsonResponse({
            'token': token,
            'url': livekit.url,
            'room_id': room_id,
            'user_id': user_id,
            'username': username,
            'is_moderator': is_moderator
        })

    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Token generation failed: {str(e)}")
        return JsonResponse({'error': 'Failed to generate token'}, status=500)


@login_required
@require_http_methods(["POST"])
def create_livekit_room(request):
    """
    Create a LiveKit room with specific settings
    
    POST /api/livekit/room/create/
    Body: {
        "room_id": "abc-defg-hij",
        "max_participants": 100,  // optional
        "empty_timeout": 300  // optional, seconds
    }
    """
    try:
        data = json.loads(request.body)
        room_id = data.get('room_id')
        max_participants = data.get('max_participants', 100)
        empty_timeout = data.get('empty_timeout', 300)
        
        if not room_id:
            return JsonResponse({'error': 'room_id is required'}, status=400)
        
        # Verify user owns this meeting
        room_access = check_room_access(request.user, room_id)
        if not room_access['allowed'] or not room_access.get('is_host'):
            return JsonResponse({'error': 'Only meeting host can create room'}, status=403)
        
        # Create room
        livekit = get_livekit_service()
        room = livekit.create_room(
            room_id=room_id,
            max_participants=max_participants,
            empty_timeout=empty_timeout
        )
        
        return JsonResponse({
            'success': True,
            'room_id': room_id,
            'max_participants': max_participants
        })
        
    except Exception as e:
        logger.error(f"Room creation failed: {str(e)}")
        return JsonResponse({'error': 'Failed to create room'}, status=500)


@login_required
@require_http_methods(["GET"])
def list_participants(request, room_id):
    """
    Get list of current participants in a room
    
    GET /api/livekit/room/<room_id>/participants/
    """
    try:
        # Verify access
        room_access = check_room_access(request.user, room_id)
        if not room_access['allowed']:
            return JsonResponse({'error': room_access['reason']}, status=403)
        
        # Get participants
        livekit = get_livekit_service()
        participants = livekit.list_participants(room_id)
        
        participant_list = [{
            'identity': p.identity,
            'name': p.name,
            'is_publisher': p.permission.can_publish,
            'joined_at': p.joined_at,
        } for p in participants]
        
        return JsonResponse({
            'room_id': room_id,
            'participants': participant_list,
            'count': len(participant_list)
        })
        
    except Exception as e:
        logger.error(f"Failed to list participants: {str(e)}")
        return JsonResponse({'error': 'Failed to list participants'}, status=500)


@login_required
@require_http_methods(["POST"])
def remove_participant(request, room_id):
    """
    Remove a participant from the room (moderator only)
    
    POST /api/livekit/room/<room_id>/remove-participant/
    Body: {
        "participant_identity": "12345"
    }
    """
    try:
        data = json.loads(request.body)
        participant_identity = data.get('participant_identity')
        
        if not participant_identity:
            return JsonResponse({'error': 'participant_identity is required'}, status=400)
        
        # Verify user is moderator
        room_access = check_room_access(request.user, room_id)
        if not room_access['allowed'] or not (room_access.get('is_host') or room_access.get('is_moderator')):
            return JsonResponse({'error': 'Only moderators can remove participants'}, status=403)
        
        # Remove participant
        livekit = get_livekit_service()
        livekit.remove_participant(room_id, participant_identity)
        
        return JsonResponse({'success': True, 'removed': participant_identity})
        
    except Exception as e:
        logger.error(f"Failed to remove participant: {str(e)}")
        return JsonResponse({'error': 'Failed to remove participant'}, status=500)


@login_required
@require_http_methods(["POST"])
def start_recording(request, room_id):
    """
    Start recording a meeting
    
    POST /api/livekit/room/<room_id>/start-recording/
    Body: {
        "filename": "meeting_recording.mp4"  // optional
    }
    """
    try:
        data = json.loads(request.body)
        filename = data.get('filename')
        
        # Verify user is moderator
        room_access = check_room_access(request.user, room_id)
        if not room_access['allowed'] or not (room_access.get('is_host') or room_access.get('is_moderator')):
            return JsonResponse({'error': 'Only moderators can start recording'}, status=403)
        
        # Start recording
        livekit = get_livekit_service()
        egress = livekit.start_recording(room_id, filename)
        
        # Save recording info to database
        meeting = Meeting.objects.filter(room_id=room_id).first()
        if meeting:
            MeetingRecording.objects.create(
                meeting=meeting,
                recorded_by=request.user,
                livekit_egress_id=egress.egress_id,
                status='recording'
            )
        
        return JsonResponse({
            'success': True,
            'egress_id': egress.egress_id,
            'room_id': room_id
        })
        
    except Exception as e:
        logger.error(f"Failed to start recording: {str(e)}")
        return JsonResponse({'error': 'Failed to start recording'}, status=500)


@login_required
@require_http_methods(["POST"])
def stop_recording(request, room_id):
    """
    Stop an ongoing recording
    
    POST /api/livekit/room/<room_id>/stop-recording/
    Body: {
        "egress_id": "EG_xxxxx"  // optional, will use latest if not provided
    }
    """
    try:
        data = json.loads(request.body)
        egress_id = data.get('egress_id')
        
        # Verify user is moderator
        room_access = check_room_access(request.user, room_id)
        if not room_access['allowed'] or not (room_access.get('is_host') or room_access.get('is_moderator')):
            return JsonResponse({'error': 'Only moderators can stop recording'}, status=403)
        
        # Get egress_id from database if not provided
        if not egress_id:
            meeting = Meeting.objects.filter(room_id=room_id).first()
            if meeting:
                recording = MeetingRecording.objects.filter(
                    meeting=meeting,
                    status='recording'
                ).order_by('-created_at').first()
                
                if recording:
                    egress_id = recording.livekit_egress_id
        
        if not egress_id:
            return JsonResponse({'error': 'No active recording found'}, status=404)
        
        # Stop recording
        livekit = get_livekit_service()
        livekit.stop_recording(egress_id)
        
        # Update database
        recording = MeetingRecording.objects.filter(livekit_egress_id=egress_id).first()
        if recording:
            recording.status = 'processing'
            recording.save()
        
        return JsonResponse({
            'success': True,
            'egress_id': egress_id
        })
        
    except Exception as e:
        logger.error(f"Failed to stop recording: {str(e)}")
        return JsonResponse({'error': 'Failed to stop recording'}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def livekit_webhook(request):
    """
    Webhook endpoint for LiveKit events (recording completed, etc.)
    
    POST /api/livekit/webhook/
    
    Configure this URL in LiveKit dashboard under Settings > Webhooks
    """
    try:
        # Verify webhook signature (important for security)
        # TODO: Implement signature verification
        
        data = json.loads(request.body)
        event_type = data.get('event')
        
        logger.info(f"LiveKit webhook received: {event_type}")
        
        if event_type == 'egress_ended':
            # Recording completed
            egress_id = data.get('egressInfo', {}).get('egressId')
            file_url = data.get('egressInfo', {}).get('fileResults', [{}])[0].get('downloadUrl')
            
            # Update recording in database
            recording = MeetingRecording.objects.filter(livekit_egress_id=egress_id).first()
            if recording:
                recording.status = 'completed'
                recording.file_url = file_url
                recording.save()
                
                logger.info(f"Recording {egress_id} completed: {file_url}")
        
        return JsonResponse({'success': True})
        
    except Exception as e:
        logger.error(f"Webhook processing failed: {str(e)}")
        return JsonResponse({'error': 'Webhook processing failed'}, status=500)


def check_room_access(user, room_id):
    """
    Check if user has access to a room
    
    Returns:
        dict: {
            'allowed': bool,
            'reason': str,
            'is_host': bool,
            'is_moderator': bool
        }
    """
    # Check if room exists in Meeting or PersonalRoom
    meeting = Meeting.objects.filter(room_id=room_id).first()
    personal_room = PersonalRoom.objects.filter(room_id=room_id).first()
    
    if not meeting and not personal_room:
        return {'allowed': False, 'reason': 'Room not found'}
    
    # Check Meeting access
    if meeting:
        is_host = meeting.author == user
        is_participant = meeting.users.filter(id=user.id).exists()
        # Check org membership
        is_same_org = False
        if meeting.organization:
            is_same_org = meeting.organization.memberships.filter(user=user, is_active=True).exists()

        if is_host or is_participant or is_same_org:
            return {
                'allowed': True,
                'reason': '',
                'is_host': is_host,
                'is_moderator': is_host
            }
        else:
            return {'allowed': False, 'reason': 'Access denied to this meeting'}

    # Check PersonalRoom access
    if personal_room:
        is_host = personal_room.user == user
        is_same_org = False
        if personal_room.organization:
            is_same_org = personal_room.organization.memberships.filter(user=user, is_active=True).exists()

        if is_host or is_same_org:
            return {
                'allowed': True,
                'reason': '',
                'is_host': is_host,
                'is_moderator': is_host
            }
        else:
            return {'allowed': False, 'reason': 'Access denied to this room'}
    
    return {'allowed': False, 'reason': 'Unknown error'}