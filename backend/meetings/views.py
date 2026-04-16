from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.http import JsonResponse, HttpResponseRedirect
from django.db.models import Q
from django.core.paginator import Paginator
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_exempt
from django.conf import settings
from django.core.signing import TimestampSigner
import json
import os
import glob
import uuid
from .models import Meeting, UserMeetingPacket, PersonalRoom, MeetingRecording, MeetingTranscript
from .forms import MeetingForm

_moderator_signer = TimestampSigner(salt='moderator-proof')


def _sign_moderator_proof(room_id):
    """Create a signed token proving the user is a verified moderator for this room."""
    return _moderator_signer.sign(room_id)


def home_view(request):
    context = {}
    if request.user.is_authenticated:
        context['organization'] = getattr(request, 'organization', None)
    else:
        from billing.models import Plan
        context['plans'] = Plan.objects.filter(is_active=True).order_by('display_order')
        context['payu_enabled'] = getattr(settings, 'PAYU_ENABLED', False)
    return render(request, 'home.html', context)


def require_organization(view_func):
    """Decorator to ensure user has an organization selected"""
    def wrapper(request, *args, **kwargs):
        if not getattr(request, 'organization', None):
            messages.warning(request, 'Please select or create an organization first.')
            return redirect('organization_list')
        return view_func(request, *args, **kwargs)
    return wrapper


@login_required
@require_organization
def schedule_meeting_view(request):
    from datetime import datetime, timedelta

    if request.method == 'POST':
        form = MeetingForm(request.POST)
        if form.is_valid():
            meeting = form.save(commit=False)
            meeting.author = request.user
            meeting.author_name = request.user.username
            meeting.organization = request.organization

            # Combine date and time fields
            start_date = form.cleaned_data['start_date']
            start_time = form.cleaned_data['start_time']
            end_time = form.cleaned_data['end_time']

            meeting.start_time = timezone.make_aware(datetime.combine(start_date, start_time))
            meeting.end_time = timezone.make_aware(datetime.combine(start_date, end_time))

            # Handle all-day meetings
            if meeting.is_all_day:
                meeting.start_time = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))
                meeting.end_time = timezone.make_aware(datetime.combine(start_date, datetime.max.time().replace(microsecond=0)))

            meeting.save()
            meeting.users.add(request.user)

            messages.success(request, 'Meeting scheduled successfully!')
            return redirect('meeting_details', room_id=meeting.room_id)
    else:
        # Set default values for new meeting
        now = timezone.now()
        default_start = now + timedelta(hours=1)
        default_end = now + timedelta(hours=2)

        form = MeetingForm(initial={
            'start_date': default_start.date(),
            'start_time': default_start.strftime('%H:%M'),
            'end_time': default_end.strftime('%H:%M'),
        })

    return render(request, 'schedulemeeting.html', {
        'form': form,
        'organization': request.organization
    })


@login_required
@require_organization
def meetings_list_view(request):
    # Get meetings in the current organization where user is the author or a participant
    meetings = Meeting.objects.filter(
        organization=request.organization,
        users=request.user
    ).select_related('author', 'organization').distinct().order_by('start_time')

    paginator = Paginator(meetings, 10)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    return render(request, 'meetings.html', {
        'meetings': page_obj,
        'page_obj': page_obj,
        'organization': request.organization
    })


@login_required
def meeting_details_view(request, room_id):
    meeting = get_object_or_404(Meeting.objects.select_related('organization', 'author'), room_id=room_id)

    # Check if user has access to this meeting's organization
    if request.user.is_authenticated:
        org = meeting.organization
        if not org.memberships.filter(user=request.user, is_active=True).exists():
            messages.error(request, 'You do not have access to this meeting.')
            return redirect('home')

    return render(request, 'meetingdetails.html', {
        'meeting': meeting,
        'room_id': room_id,
        'organization': meeting.organization
    })


def _get_plan_context(request):
    """Build plan-related context for meeting room template."""
    plan_limits = getattr(request, 'plan_limits', None)
    return {
        'max_participants': plan_limits.get_participant_limit() if plan_limits else 100,
        'duration_limit_seconds': plan_limits.get_duration_limit_seconds() if plan_limits else None,
        'recording_allowed': plan_limits.can_record() if plan_limits else True,
        'can_use_waiting_room': plan_limits.can_use_waiting_room() if plan_limits else False,
        'breakout_rooms_allowed': plan_limits.can_use_breakout_rooms() if plan_limits else False,
        'plan_tier': getattr(request, 'plan_tier', 'free'),
    }


@login_required
def start_meeting_view(request, room_id):
    meeting = get_object_or_404(Meeting.objects.select_related('organization', 'author'), room_id=room_id)

    # Check if user has access to this meeting's organization
    org = meeting.organization
    if not org.memberships.filter(user=request.user, is_active=True).exists():
        messages.error(request, 'You do not have access to this meeting.')
        return redirect('home')

    # Determine if user is the moderator (meeting author)
    is_moderator = (meeting.author == request.user)

    # Check if user is the author
    if is_moderator:
        # Author can join directly as moderator
        return render(request, 'meeting_room_livekit.html', {
            'room_id': str(room_id),
            'user_id': str(request.user.id),
            'username': request.user.username,
            'organization': org,
            'is_moderator': True,
            'moderator_proof': _sign_moderator_proof(str(room_id)),
            'author_id': str(meeting.author.id),
            'is_locked': meeting.require_approval,
            'recording_to_s3': org.recording_to_s3 if org else False,
            **_get_plan_context(request),
        })

    # Check if meeting requires approval
    if meeting.require_approval:
        is_approved = False

        # Check session-based approval
        approved_key = f'approved_for_{room_id}'
        is_approved = request.session.get(approved_key, False)

        # Check UserMeetingPacket
        if not is_approved:
            packet = UserMeetingPacket.objects.filter(
                user=request.user,
                room_id=room_id
            ).first()
            is_approved = packet is not None

        # Check Redis cache as fallback (survives session race conditions)
        if not is_approved:
            from django.core.cache import cache
            cache_approval_key = f'room_approval:{room_id}:{request.user.id}'
            if cache.get(cache_approval_key):
                is_approved = True
                request.session[approved_key] = True

        if not is_approved:
            # User needs approval - store room info in session and redirect to pending
            request.session['pending_room_id'] = str(room_id)
            request.session['pending_author_id'] = meeting.author.id
            request.session['pending_user_id'] = str(request.user.id)
            request.session['pending_username'] = request.user.username
            request.session['pending_is_scheduled'] = True
            return redirect('pending_room')

    # User is approved or no approval required — join as participant
    return render(request, 'meeting_room_livekit.html', {
        'room_id': str(room_id),
        'user_id': str(request.user.id),
        'username': request.user.username,
        'organization': org,
        'is_moderator': False,
        'author_id': str(meeting.author.id),
        'is_locked': meeting.require_approval,
        'recording_to_s3': org.recording_to_s3 if org else False,
        **_get_plan_context(request),
    })


@ensure_csrf_cookie
def pending_room_view(request):
    room_id = request.session.get('pending_room_id')
    author_id = request.session.get('pending_author_id')

    if not room_id or not author_id:
        messages.error(request, 'No pending meeting request.')
        return redirect('home')

    # Handle both authenticated users and guests
    if request.user.is_authenticated:
        user_id = str(request.user.id)
        username = request.user.username
    else:
        # Get guest info from session (set by join_personal_room_view)
        user_id = request.session.get('pending_user_id', '')
        username = request.session.get('pending_username', 'Guest')

    # Get the token for redirecting back after approval
    pending_token = request.session.get('pending_token', '')
    pending_is_scheduled = request.session.get('pending_is_scheduled', False)

    return render(request, 'pending.html', {
        'room_id': room_id,
        'author_id': author_id,
        'user_id': user_id,
        'username': username,
        'pending_token': pending_token,
        'is_scheduled_meeting': pending_is_scheduled,
    })


@login_required
@require_organization
def organization_meetings_view(request):
    """View all meetings in the organization (for admins)"""
    org = request.organization
    membership = org.memberships.filter(user=request.user, is_active=True).first()

    if not membership or membership.role not in ['owner', 'admin']:
        messages.error(request, 'You do not have permission to view all organization meetings.')
        return redirect('meetings_list')

    meetings = Meeting.objects.filter(
        organization=org
    ).select_related('author').order_by('-start_time')

    paginator = Paginator(meetings, 25)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    return render(request, 'organization_meetings.html', {
        'meetings': page_obj,
        'page_obj': page_obj,
        'organization': org
    })


@login_required
@require_organization
def my_room_view(request):
    """View user's personal room with links"""
    plan_limits = getattr(request, 'plan_limits', None)

    # Check room creation limit for new rooms
    existing = PersonalRoom.objects.filter(
        user=request.user, organization=request.organization
    ).first()
    if not existing:
        if plan_limits and not plan_limits.can_create_room():
            messages.warning(
                request,
                f'Your plan allows a maximum of {plan_limits.max_rooms} room(s). '
                f'Please upgrade to create more rooms.'
            )
            return redirect('pricing')

    personal_room, created = PersonalRoom.objects.get_or_create(
        user=request.user,
        organization=request.organization
    )

    # Set is_locked based on plan (only Business can use waiting rooms)
    if created:
        can_use_waiting_room = plan_limits and plan_limits.can_use_waiting_room()
        personal_room.is_locked = can_use_waiting_room
        personal_room.save(update_fields=['is_locked'])

    # Build full URLs
    base_url = request.build_absolute_uri('/')[:-1]  # Remove trailing slash
    moderator_link = f"{base_url}{personal_room.get_moderator_link()}"
    attendee_link = f"{base_url}{personal_room.get_attendee_link()}"

    return render(request, 'my_room.html', {
        'room': personal_room,
        'moderator_link': moderator_link,
        'attendee_link': attendee_link,
        'organization': request.organization,
        'can_use_waiting_room': plan_limits.can_use_waiting_room() if plan_limits else False,
    })


def join_personal_room_view(request, room_id):
    """Join a personal room via token link"""
    import uuid

    token = request.GET.get('token', '') or request.POST.get('token', '')

    if not token:
        messages.error(request, 'Invalid room link. Token is required.')
        return redirect('home')

    personal_room = get_object_or_404(PersonalRoom, room_id=room_id)

    # Determine if user is moderator or attendee
    is_moderator = (token == personal_room.moderator_token)
    is_attendee = (token == personal_room.attendee_token)

    if not is_moderator and not is_attendee:
        messages.error(request, 'Invalid room link. Please check your link and try again.')
        return redirect('home')

    # For attendees, show pre-join screen to enter name
    if is_attendee and request.method == 'GET':
        # Check if they already have a name in session
        name_key = f'display_name_{room_id}'
        if name_key not in request.session:
            # Show pre-join screen
            suggested_name = ''
            if request.user.is_authenticated:
                suggested_name = request.user.username

            return render(request, 'prejoin.html', {
                'room_id': room_id,
                'token': token,
                'room_name': personal_room.room_name,
                'room_owner': personal_room.user.username,
                'is_locked': personal_room.is_locked,
                'suggested_name': suggested_name
            })

    # Process pre-join form submission
    if is_attendee and request.method == 'POST':
        display_name = request.POST.get('display_name', '').strip()
        if display_name:
            name_key = f'display_name_{room_id}'
            request.session[name_key] = display_name

    # Get user ID and username
    if request.user.is_authenticated:
        user_id = str(request.user.id)
        # Use custom display name if set, otherwise use account username
        name_key = f'display_name_{room_id}'
        username = request.session.get(name_key, request.user.username)
    elif is_moderator:
        # Unauthenticated moderator accessing via token link
        # Use room owner's name so they appear as the host
        session_key = f'guest_id_{room_id}'
        if session_key in request.session:
            user_id = request.session[session_key]
        else:
            user_id = f"guest_{uuid.uuid4().hex[:8]}"
            request.session[session_key] = user_id
        username = personal_room.user.username
    else:
        # Use persistent guest ID from session, or generate new one
        session_key = f'guest_id_{room_id}'
        name_key = f'display_name_{room_id}'

        if session_key in request.session:
            user_id = request.session[session_key]
        else:
            user_id = f"guest_{uuid.uuid4().hex[:8]}"
            request.session[session_key] = user_id

        # Use the display name they entered
        username = request.session.get(name_key, f"Guest_{user_id[-4:]}")

    # All attendees ALWAYS need host approval before joining
    if is_attendee:
        # If room is LOCKED — completely blocked
        if personal_room.is_locked:
            messages.error(request, 'This room is locked. The host is not accepting new participants.')
            return redirect('home')

        # Check if host approved this guest in THIS session via Redis (short-lived)
        from django.core.cache import cache
        cache_approval_key = f'room_approval:{room_id}:{user_id}'
        is_approved = cache.get(cache_approval_key, False)

        if not is_approved:
            # Clear any stale session approval from previous meetings
            approved_key = f'approved_for_{room_id}'
            request.session.pop(approved_key, None)

            # User needs approval - redirect to pending/waiting page
            request.session['pending_room_id'] = str(room_id)
            request.session['pending_author_id'] = personal_room.user.id
            request.session['pending_user_id'] = user_id
            request.session['pending_username'] = username
            request.session['pending_token'] = token
            return redirect('pending_room')

    return render(request, 'meeting_room_livekit.html', {
        'room_id': str(room_id),
        'user_id': user_id,
        'username': username,
        'is_moderator': is_moderator,
        'moderator_proof': _sign_moderator_proof(str(room_id)) if is_moderator else '',
        'room_owner': personal_room.user.username,
        'room_owner_id': str(personal_room.user.id),
        'room_name': personal_room.room_name,
        'organization': personal_room.organization,
        'is_locked': personal_room.is_locked,
        'recording_to_s3': personal_room.organization.recording_to_s3,
        **_get_plan_context(request),
    })


def join_meeting_guest_view(request, room_id):
    """Allow anyone (including unregistered users) to join a scheduled meeting via token link"""
    import uuid

    token = request.GET.get('token', '') or request.POST.get('token', '')

    if not token:
        messages.error(request, 'Invalid meeting link. Token is required.')
        return redirect('home')

    meeting = get_object_or_404(Meeting.objects.select_related('organization', 'author'), room_id=room_id)

    # Validate token
    if token != meeting.attendee_token:
        messages.error(request, 'Invalid meeting link. Please check your link and try again.')
        return redirect('home')

    # For unauthenticated users (guests), show pre-join screen to enter name
    if request.method == 'GET':
        name_key = f'display_name_meeting_{room_id}'
        if name_key not in request.session:
            suggested_name = ''
            if request.user.is_authenticated:
                suggested_name = request.user.username

            return render(request, 'prejoin.html', {
                'room_id': room_id,
                'token': token,
                'room_name': meeting.name,
                'room_owner': meeting.author_name,
                'is_locked': meeting.require_approval,
                'suggested_name': suggested_name,
                'is_scheduled_meeting': True,
            })

    # Process pre-join form submission
    if request.method == 'POST':
        display_name = request.POST.get('display_name', '').strip()
        if display_name:
            name_key = f'display_name_meeting_{room_id}'
            request.session[name_key] = display_name

    # Get user ID and username
    if request.user.is_authenticated:
        user_id = str(request.user.id)
        name_key = f'display_name_meeting_{room_id}'
        username = request.session.get(name_key, request.user.username)
    else:
        session_key = f'guest_id_meeting_{room_id}'
        name_key = f'display_name_meeting_{room_id}'

        if session_key in request.session:
            user_id = request.session[session_key]
        else:
            user_id = f"guest_{uuid.uuid4().hex[:8]}"
            request.session[session_key] = user_id

        username = request.session.get(name_key, f"Guest_{user_id[-4:]}")

    # Check if meeting requires approval
    if meeting.require_approval:
        # Check if user has been approved
        is_approved = False

        approved_key = f'approved_for_{room_id}'
        is_approved = request.session.get(approved_key, False)

        if not is_approved and request.user.is_authenticated:
            packet = UserMeetingPacket.objects.filter(
                room_id=room_id,
                user__id=request.user.id
            ).first()
            is_approved = packet is not None

        # Check Redis cache as fallback (survives session race conditions)
        if not is_approved:
            from django.core.cache import cache
            cache_approval_key = f'room_approval:{room_id}:{user_id}'
            if cache.get(cache_approval_key):
                is_approved = True
                request.session[approved_key] = True

        # Meeting author is always approved
        if request.user.is_authenticated and meeting.author == request.user:
            is_approved = True

        if not is_approved:
            request.session['pending_room_id'] = str(room_id)
            request.session['pending_author_id'] = meeting.author.id
            request.session['pending_user_id'] = user_id
            request.session['pending_username'] = username
            request.session['pending_token'] = token
            request.session['pending_is_scheduled'] = True
            return redirect('pending_room')

    is_moderator = request.user.is_authenticated and meeting.author == request.user
    org = meeting.organization

    return render(request, 'meeting_room_livekit.html', {
        'room_id': str(room_id),
        'user_id': user_id,
        'username': username,
        'organization': org,
        'is_moderator': is_moderator,
        'moderator_proof': _sign_moderator_proof(str(room_id)) if is_moderator else '',
        'author_id': str(meeting.author.id),
        'is_locked': meeting.require_approval,
        'recording_to_s3': org.recording_to_s3 if org else False,
        **_get_plan_context(request),
    })


@login_required
@require_organization
def all_rooms_view(request):
    """View all personal rooms in the organization (for admins)"""
    org = request.organization
    membership = org.memberships.filter(user=request.user, is_active=True).first()

    if not membership or membership.role not in ['owner', 'admin']:
        messages.error(request, 'You do not have permission to view all rooms.')
        return redirect('my_room')

    rooms = PersonalRoom.objects.filter(
        organization=org,
        is_active=True
    ).select_related('user')

    paginator = Paginator(rooms, 10)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    return render(request, 'all_rooms.html', {
        'rooms': page_obj,
        'page_obj': page_obj,
        'organization': org
    })


@require_POST
def toggle_room_lock_view(request, room_id):
    """Toggle lock state of a personal room or scheduled meeting"""
    try:
        data = json.loads(request.body)
        is_locked = data.get('is_locked', False)
        token = data.get('token', '')

        # Try PersonalRoom first, then Meeting
        personal_room = PersonalRoom.objects.filter(room_id=room_id).first()
        meeting = None
        if not personal_room:
            meeting = Meeting.objects.filter(room_id=room_id).first()

        if not personal_room and not meeting:
            return JsonResponse({'error': 'Room not found'}, status=404)

        if personal_room:
            # Allow authenticated room owner OR valid moderator token
            is_owner = request.user.is_authenticated and personal_room.user == request.user
            is_token_moderator = token and token == personal_room.moderator_token
            if not is_owner and not is_token_moderator:
                return JsonResponse({'error': 'Unauthorized'}, status=403)

            personal_room.is_locked = is_locked
            personal_room.save()

            return JsonResponse({
                'success': True,
                'is_locked': personal_room.is_locked
            })
        else:
            # Scheduled meeting — only author can toggle
            is_author = request.user.is_authenticated and meeting.author == request.user
            if not is_author:
                return JsonResponse({'error': 'Unauthorized'}, status=403)

            if is_locked:
                from billing.plan_limits import get_plan_limits
                org = meeting.organization
                if org:
                    limits = get_plan_limits(org)
                    if not limits.can_use_waiting_room():
                        return JsonResponse({
                            'error': 'Waiting room feature requires a Business plan',
                            'upgrade_required': True
                        }, status=403)

            meeting.require_approval = is_locked
            meeting.save()

            return JsonResponse({
                'success': True,
                'is_locked': meeting.require_approval
            })
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error('toggle_room_lock error: %s', e, exc_info=True)
        return JsonResponse({'error': 'Failed to update room lock status.'}, status=400)


def get_room_lock_status_view(request, room_id):
    """Get lock status of a personal room or scheduled meeting"""
    personal_room = PersonalRoom.objects.filter(room_id=room_id).first()
    if personal_room:
        return JsonResponse({'is_locked': personal_room.is_locked})

    meeting = Meeting.objects.filter(room_id=room_id).first()
    if meeting:
        return JsonResponse({'is_locked': meeting.require_approval})

    return JsonResponse({'error': 'Room not found'}, status=404)


@ensure_csrf_cookie
@require_POST
def send_join_alert_view(request, room_id):
    """Send a join request alert to the room moderator via channel layer (HTTP-based)"""
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync

        # Verify room exists (could be PersonalRoom or Meeting)
        room_exists = PersonalRoom.objects.filter(room_id=room_id).exists() or \
                      Meeting.objects.filter(room_id=room_id).exists()
        if not room_exists:
            return JsonResponse({'error': 'Room not found'}, status=404)

        # Get user info from session (set by join view)
        author_id = request.session.get('pending_author_id', '')
        user_id = request.session.get('pending_user_id', '')
        alert_username = request.session.get('pending_username', 'Guest')

        if request.user.is_authenticated:
            user_id = str(request.user.id)
            alert_username = request.user.username

        if not author_id or not user_id:
            return JsonResponse({'error': 'Missing session data'}, status=400)

        # Store pending request in Redis so host can poll it via HTTP
        from django.core.cache import cache
        pending_key = f'pending_join:{room_id}'
        pending_list = cache.get(pending_key, [])
        # Add if not already in list
        if not any(p['user_id'] == user_id for p in pending_list):
            pending_list.append({'user_id': user_id, 'username': alert_username})
        cache.set(pending_key, pending_list, 300)  # 5 min TTL

        # Also try channel layer (works when WebSocket is connected)
        try:
            channel_layer = get_channel_layer()
            room_group_name = f'room_{room_id}'
            async_to_sync(channel_layer.group_send)(
                room_group_name,
                {
                    'type': 'join_request',
                    'user_id': user_id,
                    'username': alert_username,
                }
            )
            async_to_sync(channel_layer.group_send)(
                f'user_{author_id}',
                {
                    'type': 'alert_request',
                    'user_id': user_id,
                    'username': alert_username,
                    'room_id': str(room_id),
                }
            )
        except Exception:
            pass  # Channel layer is optional — Redis polling is the primary method

        return JsonResponse({'success': True})
    except Exception as e:
        import logging
        logging.getLogger(__name__).error('send_join_alert error: %s', e, exc_info=True)
        return JsonResponse({'error': 'Failed to send join alert.'}, status=400)


@require_POST
def mark_guest_approved_view(request, room_id):
    """Mark a guest as approved for a room (stores in session)"""
    try:
        # Verify the room exists (could be PersonalRoom or Meeting)
        room_exists = PersonalRoom.objects.filter(room_id=room_id).exists() or \
                      Meeting.objects.filter(room_id=room_id).exists()
        if not room_exists:
            return JsonResponse({'error': 'Room not found'}, status=404)

        # Verify the pending session matches this room
        pending_room_id = request.session.get('pending_room_id')
        if str(pending_room_id) != str(room_id):
            return JsonResponse({'error': 'Invalid approval request'}, status=403)

        # Verify server-side approval exists in Redis (set by moderator via WebSocket)
        user_id = request.session.get('pending_user_id', '')
        if request.user.is_authenticated:
            user_id = str(request.user.id)

        from django.core.cache import cache
        approval_key = f'room_approval:{room_id}:{user_id}'
        if not cache.get(approval_key):
            return JsonResponse({'error': 'Approval not found. Please wait for the moderator.'}, status=403)

        # Set approval in session
        approved_key = f'approved_for_{room_id}'
        request.session[approved_key] = True

        # Clean up pending session data (keep Redis approval key as fallback
        # against session race conditions — it expires naturally after 1 hour)
        for key in ['pending_room_id', 'pending_author_id', 'pending_user_id', 'pending_username', 'pending_token', 'pending_is_scheduled']:
            request.session.pop(key, None)

        return JsonResponse({'success': True})
    except Exception as e:
        import logging
        logging.getLogger(__name__).error('mark_guest_approved error: %s', e, exc_info=True)
        return JsonResponse({'error': 'Failed to process approval.'}, status=400)


def get_pending_requests_view(request, room_id):
    """Get pending join requests for a room (host polls this)"""
    from django.core.cache import cache
    pending_key = f'pending_join:{room_id}'
    pending_list = cache.get(pending_key, [])
    return JsonResponse({'requests': pending_list})


def check_approval_view(request, room_id):
    """Guest polls this to check if they've been approved"""
    from django.core.cache import cache
    user_id = request.session.get('pending_user_id', '')
    if not user_id:
        return JsonResponse({'approved': False})
    approval_key = f'room_approval:{room_id}:{user_id}'
    is_approved = bool(cache.get(approval_key))
    return JsonResponse({'approved': is_approved})


@require_POST
def approve_guest_view(request, room_id):
    """Host approves or denies a guest via HTTP (no WebSocket needed)"""
    try:
        data = json.loads(request.body)
        user_id = data.get('user_id', '')
        approved = data.get('approved', False)

        from django.core.cache import cache

        if approved:
            # Store approval in Redis
            approval_key = f'room_approval:{room_id}:{user_id}'
            cache.set(approval_key, True, 3600)

            # Create meeting packet
            try:
                from .tasks import create_meeting_packet
                create_meeting_packet.delay(user_id, room_id)
            except Exception:
                pass

        # Remove from pending list
        pending_key = f'pending_join:{room_id}'
        pending_list = cache.get(pending_key, [])
        pending_list = [p for p in pending_list if p['user_id'] != user_id]
        cache.set(pending_key, pending_list, 300)

        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@login_required
@require_POST
def upload_recording_view(request):
    """Upload a meeting recording to S3"""
    try:
        import boto3
        from botocore.exceptions import ClientError

        recording_file = request.FILES.get('recording')
        room_id = request.POST.get('room_id', '')
        try:
            duration = int(request.POST.get('duration', 0))
            if duration < 0 or duration > 86400:  # Max 24 hours
                duration = 0
        except (ValueError, TypeError):
            duration = 0

        if not recording_file:
            return JsonResponse({'error': 'No recording file provided'}, status=400)

        # Validate file type - only allow video formats
        allowed_types = ['video/webm', 'video/mp4', 'video/x-matroska']
        if recording_file.content_type not in allowed_types:
            return JsonResponse({'error': 'Invalid file type. Only video recordings are allowed.'}, status=400)

        # Limit file size (500 MB max)
        max_size = 500 * 1024 * 1024
        if recording_file.size > max_size:
            return JsonResponse({'error': 'Recording file too large. Maximum size is 500MB.'}, status=400)

        # Get user's current organization
        org = getattr(request, 'organization', None)
        if not org:
            return JsonResponse({'error': 'No organization context'}, status=400)

        # Check plan allows recording
        plan_limits = getattr(request, 'plan_limits', None)
        if plan_limits and not plan_limits.can_record():
            return JsonResponse({'error': 'Recording requires a Pro plan or higher.'}, status=403)

        if not org.recording_to_s3:
            return JsonResponse({'error': 'Cloud recording is not enabled for this organization'}, status=400)

        # Check AWS config
        if not settings.AWS_ACCESS_KEY_ID or not settings.AWS_SECRET_ACCESS_KEY:
            return JsonResponse({'error': 'S3 storage is not configured'}, status=500)

        # Generate unique S3 key
        timestamp = timezone.now().strftime('%Y%m%d-%H%M%S')
        short_uuid = uuid.uuid4().hex[:8]
        s3_key = f"{org.slug}/{request.user.username}/{timestamp}-{short_uuid}.webm"
        recording_name = f"{room_id}-{timestamp}.webm"

        # Upload to S3
        s3_client = boto3.client(
            's3',
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_S3_REGION,
        )

        s3_client.upload_fileobj(
            recording_file,
            settings.AWS_S3_BUCKET_NAME,
            s3_key,
            ExtraArgs={'ContentType': 'video/webm'}
        )

        # Create database record
        recording = MeetingRecording.objects.create(
            organization=org,
            recorded_by=request.user,
            file_path='',
            s3_key=s3_key,
            recording_name=recording_name,
            file_size=recording_file.size,
            duration=duration,
        )

        return JsonResponse({
            'success': True,
            'recording_id': recording.id,
            'recording_name': recording_name,
        })

    except ClientError as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error('S3 upload failed for room %s: %s', room_id, e, exc_info=True)
        return JsonResponse({'error': 'Recording upload failed. Please try again later.'}, status=500)
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error('Unexpected error in upload_recording for room %s: %s', room_id, e, exc_info=True)
        return JsonResponse({'error': 'An unexpected error occurred.'}, status=500)


@login_required
def my_recordings_view(request):
    """View user's recordings and screenshots"""
    from datetime import datetime

    org = getattr(request, 'organization', None)

    # Show recordings by this user — with or without org
    filters = Q(recorded_by=request.user)
    if org:
        filters = filters | Q(organization=org, recorded_by=request.user)

    recordings = MeetingRecording.objects.filter(filters).distinct().order_by('-created_at')

    paginator = Paginator(recordings, 10)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    # Scan screenshots directory for this user's screenshots
    screenshots = []
    screenshots_dir = os.path.join(settings.MEDIA_ROOT, 'screenshots')
    if os.path.exists(screenshots_dir):
        username = request.user.username
        for filepath in sorted(glob.glob(os.path.join(screenshots_dir, '*.png')), reverse=True):
            filename = os.path.basename(filepath)
            # Include screenshots by this user or from rooms they own
            if username.lower() in filename.lower() or not request.user.is_authenticated:
                stat = os.stat(filepath)
                screenshots.append({
                    'filename': filename,
                    'url': f'/media/screenshots/{filename}',
                    'size': stat.st_size,
                    'created_at': datetime.fromtimestamp(stat.st_mtime),
                })

        # Also include screenshots where room belongs to user
        if not screenshots:
            user_rooms = PersonalRoom.objects.filter(user=request.user).values_list('room_id', flat=True)
            for filepath in sorted(glob.glob(os.path.join(screenshots_dir, '*.png')), reverse=True):
                filename = os.path.basename(filepath)
                for rid in user_rooms:
                    if rid in filename:
                        stat = os.stat(filepath)
                        screenshots.append({
                            'filename': filename,
                            'url': f'/media/screenshots/{filename}',
                            'size': stat.st_size,
                            'created_at': datetime.fromtimestamp(stat.st_mtime),
                        })
                        break

    return render(request, 'my_recordings.html', {
        'recordings': page_obj,
        'page_obj': page_obj,
        'organization': org,
        'screenshots': screenshots,
    })


@login_required
def download_recording_view(request, recording_id):
    """Download a recording — serves local file or generates S3 presigned URL"""
    import os

    recording = get_object_or_404(MeetingRecording, id=recording_id)

    # Verify ownership
    if recording.recorded_by != request.user:
        return JsonResponse({'error': 'Access denied'}, status=403)

    # Verify user still has access to the organization
    if recording.organization:
        if not recording.organization.memberships.filter(user=request.user, is_active=True).exists():
            return JsonResponse({'error': 'Access denied - no longer a member of this organization'}, status=403)

    # Local file — serve directly
    if recording.file_path and os.path.exists(recording.file_path):
        from django.http import FileResponse
        import re
        safe_name = re.sub(r'[^\w\-.]', '_', recording.recording_name or 'recording.webm')
        response = FileResponse(open(recording.file_path, 'rb'), content_type='video/webm')
        response['Content-Disposition'] = f'attachment; filename="{safe_name}"'
        return response

    # S3 file
    if not recording.s3_key:
        return JsonResponse({'error': 'No file associated with this recording'}, status=404)

    try:
        import boto3
        from botocore.exceptions import ClientError

        # Check AWS config
        if not settings.AWS_ACCESS_KEY_ID or not settings.AWS_SECRET_ACCESS_KEY:
            return JsonResponse({'error': 'S3 storage is not configured'}, status=500)

        s3_client = boto3.client(
            's3',
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_S3_REGION,
        )

        # Sanitize filename for Content-Disposition header
        import re
        safe_name = re.sub(r'[^\w\-.]', '_', recording.recording_name or 'recording.webm')

        presigned_url = s3_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': settings.AWS_S3_BUCKET_NAME,
                'Key': recording.s3_key,
                'ResponseContentDisposition': f'attachment; filename="{safe_name}"',
            },
            ExpiresIn=3600,  # 1 hour
        )

        return HttpResponseRedirect(presigned_url)

    except ClientError as e:
        import logging
        logging.getLogger(__name__).error('S3 download failed for recording %s: %s', recording_id, e, exc_info=True)
        return JsonResponse({'error': 'Failed to generate download link. Please try again later.'}, status=500)


# ==================== SCREENSHOT VIEWS ====================

@require_POST
@csrf_exempt
def save_screenshot_view(request):
    """Save a meeting screenshot captured from video frame."""
    import base64
    import os
    import logging
    logger = logging.getLogger(__name__)

    try:
        data = json.loads(request.body)
        image_data = data.get('image', '')
        room_id = data.get('room_id', '')

        if not image_data or not room_id:
            return JsonResponse({'error': 'Missing image data or room_id'}, status=400)

        # Strip data URL prefix
        if ',' in image_data:
            image_data = image_data.split(',')[1]

        image_bytes = base64.b64decode(image_data)

        # Limit size (10 MB max)
        if len(image_bytes) > 10 * 1024 * 1024:
            return JsonResponse({'error': 'Screenshot too large'}, status=400)

        # Save to media/screenshots/
        timestamp = timezone.now().strftime('%Y%m%d-%H%M%S')
        username = request.user.username if request.user.is_authenticated else 'guest'
        filename = f'{room_id}_{username}_{timestamp}.png'
        filepath = os.path.join(settings.MEDIA_ROOT, 'screenshots', filename)

        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'wb') as f:
            f.write(image_bytes)

        return JsonResponse({
            'success': True,
            'filename': filename,
            'path': f'/media/screenshots/{filename}',
        })

    except Exception as e:
        logger.error('Screenshot save failed: %s', e, exc_info=True)
        return JsonResponse({'error': 'Failed to save screenshot'}, status=500)


# ==================== LOCAL RECORDING VIEWS ====================

@require_POST
@csrf_exempt
def save_local_recording_view(request):
    """Save a client-side MediaRecorder recording to local storage."""
    import os
    import logging
    logger = logging.getLogger(__name__)

    try:
        recording_file = request.FILES.get('recording')
        room_id = request.POST.get('room_id', '')
        try:
            duration = int(request.POST.get('duration', 0))
            if duration < 0 or duration > 86400:
                duration = 0
        except (ValueError, TypeError):
            duration = 0

        if not recording_file:
            return JsonResponse({'error': 'No recording file provided'}, status=400)

        # Validate file type
        allowed_types = ['video/webm', 'video/mp4', 'audio/webm']
        if recording_file.content_type not in allowed_types:
            return JsonResponse({'error': 'Invalid file type'}, status=400)

        # Limit file size (500 MB max)
        if recording_file.size > 500 * 1024 * 1024:
            return JsonResponse({'error': 'Recording too large. Max 500MB.'}, status=400)

        # Save to media/recordings/
        timestamp = timezone.now().strftime('%Y%m%d-%H%M%S')
        username = request.user.username if request.user.is_authenticated else 'guest'
        short_id = uuid.uuid4().hex[:8]
        filename = f'{room_id}_{username}_{timestamp}_{short_id}.webm'
        filepath = os.path.join(settings.MEDIA_ROOT, 'recordings', filename)

        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'wb') as f:
            for chunk in recording_file.chunks():
                f.write(chunk)

        # Create database record — find the room owner for recorded_by
        org = getattr(request, 'organization', None)
        meeting = None
        recorded_by = request.user if request.user.is_authenticated else None

        try:
            meeting = Meeting.objects.get(room_id=room_id)
            if not recorded_by:
                recorded_by = meeting.author
            if not org:
                org = meeting.organization
        except Meeting.DoesNotExist:
            pass

        # Also check PersonalRoom
        if not recorded_by or not org:
            try:
                personal_room = PersonalRoom.objects.select_related('user').get(room_id=room_id)
                if not recorded_by:
                    recorded_by = personal_room.user
                if not org:
                    org = personal_room.user.memberships.filter(is_active=True).first()
                    if org:
                        org = org.organization
            except PersonalRoom.DoesNotExist:
                pass

        recording = MeetingRecording.objects.create(
            meeting=meeting,
            organization=org,
            recorded_by=recorded_by,
            file_path=filepath,
            recording_name=filename,
            file_size=recording_file.size,
            duration=duration,
        )

        return JsonResponse({
            'success': True,
            'recording_id': recording.id,
            'filename': filename,
            'path': f'/media/recordings/{filename}',
        })

    except Exception as e:
        logger.error('Recording save failed: %s', e, exc_info=True)
        return JsonResponse({'error': 'Failed to save recording'}, status=500)


# ==================== TRANSCRIPT VIEWS ====================

@require_POST
def save_transcript_view(request, room_id):
    """Flush Redis-buffered transcript entries to database."""
    from django.core.cache import cache

    key = f'transcript:entries:{room_id}'
    raw_entries = cache.get(key) or []

    entries = []
    for raw in raw_entries:
        if isinstance(raw, str):
            try:
                entries.append(json.loads(raw))
            except (json.JSONDecodeError, ValueError):
                continue
        else:
            entries.append(raw)

    if not entries:
        return JsonResponse({'error': 'No transcript data available'}, status=404)

    # Determine meeting and org
    org = getattr(request, 'organization', None)
    meeting = None
    try:
        meeting = Meeting.objects.get(room_id=room_id)
        if not org:
            org = meeting.organization
    except Meeting.DoesNotExist:
        try:
            room = PersonalRoom.objects.get(room_id=room_id)
            if not org:
                org = room.organization
        except PersonalRoom.DoesNotExist:
            pass

    created_by = request.user if request.user.is_authenticated else None

    transcript = MeetingTranscript.objects.create(
        meeting=meeting,
        room_id=room_id,
        organization=org,
        entries=entries,
        status='completed',
        created_by=created_by,
    )

    # Clear Redis buffer
    cache.delete(key)

    return JsonResponse({
        'success': True,
        'transcript_id': transcript.id,
        'entry_count': len(entries),
    })


@require_POST
@csrf_exempt
def save_caption_transcript_view(request, room_id):
    """Save transcript entries from Web Speech API captions directly."""
    import logging
    logger = logging.getLogger(__name__)

    try:
        data = json.loads(request.body)
        entries = data.get('entries', [])

        if not entries:
            return JsonResponse({'error': 'No transcript entries'}, status=400)

        # Validate entries format
        for entry in entries:
            if not isinstance(entry, dict) or 'text' not in entry:
                return JsonResponse({'error': 'Invalid entry format'}, status=400)

        org = getattr(request, 'organization', None)
        meeting = None
        try:
            meeting = Meeting.objects.get(room_id=room_id)
            if not org:
                org = meeting.organization
        except Meeting.DoesNotExist:
            try:
                room = PersonalRoom.objects.get(room_id=room_id)
                if not org:
                    org = room.organization
            except PersonalRoom.DoesNotExist:
                pass

        created_by = request.user if request.user.is_authenticated else None

        transcript = MeetingTranscript.objects.create(
            meeting=meeting,
            room_id=room_id,
            organization=org,
            entries=entries,
            status='completed',
            created_by=created_by,
        )

        # Also save as text file
        import os
        timestamp = timezone.now().strftime('%Y%m%d-%H%M%S')
        txt_filename = f'{room_id}_transcript_{timestamp}.txt'
        txt_filepath = os.path.join(settings.MEDIA_ROOT, 'transcripts', txt_filename)
        os.makedirs(os.path.dirname(txt_filepath), exist_ok=True)

        with open(txt_filepath, 'w', encoding='utf-8') as f:
            for entry in entries:
                ts = entry.get('timestamp', '')
                speaker = entry.get('speaker', 'Unknown')
                text = entry.get('text', '')
                f.write(f'[{ts}] {speaker}: {text}\n')

        return JsonResponse({
            'success': True,
            'transcript_id': transcript.id,
            'entry_count': len(entries),
            'file_path': f'/media/transcripts/{txt_filename}',
        })

    except Exception as e:
        logger.error('Caption transcript save failed: %s', e, exc_info=True)
        return JsonResponse({'error': 'Failed to save transcript'}, status=500)


@login_required
def view_transcript_view(request, transcript_id):
    """View transcript as JSON or plain text download."""
    transcript = get_object_or_404(MeetingTranscript, id=transcript_id)

    # Access control - always enforce for org transcripts
    if transcript.organization:
        from users.models import OrganizationMembership
        if not OrganizationMembership.objects.filter(
            user=request.user, organization=transcript.organization, is_active=True
        ).exists() and not request.user.is_staff:
            return JsonResponse({'error': 'Access denied'}, status=403)

    fmt = request.GET.get('format', 'json')

    if fmt == 'text':
        from django.http import HttpResponse
        from datetime import datetime
        lines = []
        for entry in transcript.entries:
            ts = entry.get('timestamp', '')
            speaker = entry.get('speaker', 'Unknown')
            text = entry.get('text', '')
            if ts:
                try:
                    dt = datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc)
                    ts_str = dt.strftime('%H:%M:%S')
                except (ValueError, TypeError, OSError):
                    ts_str = str(ts)
            else:
                ts_str = '??:??:??'
            lines.append(f'[{ts_str}] {speaker}: {text}')
        content = '\n'.join(lines)
        response = HttpResponse(content, content_type='text/plain; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="transcript-{transcript.room_id}.txt"'
        return response

    return JsonResponse({
        'id': transcript.id,
        'room_id': transcript.room_id,
        'status': transcript.status,
        'entries': transcript.entries,
        'created_at': transcript.created_at.isoformat(),
    })
