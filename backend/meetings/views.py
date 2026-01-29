from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.views.decorators.http import require_POST
import json
from .models import Meeting, UserMeetingPacket, PersonalRoom
from .forms import MeetingForm


def home_view(request):
    context = {}
    if request.user.is_authenticated:
        context['organization'] = getattr(request, 'organization', None)
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

            meeting.start_time = datetime.combine(start_date, start_time)
            meeting.end_time = datetime.combine(start_date, end_time)

            # Handle all-day meetings
            if meeting.is_all_day:
                meeting.start_time = datetime.combine(start_date, datetime.min.time())
                meeting.end_time = datetime.combine(start_date, datetime.max.time().replace(microsecond=0))

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
        return render(request, 'room.html', {
            'room_id': str(room_id),
            'user_id': str(request.user.id),
            'username': request.user.username,
            'organization': org,
            'is_moderator': True,
            'author_id': str(meeting.author.id)
        })

    # Check if user has been approved (has a packet)
    packet = UserMeetingPacket.objects.filter(
        user=request.user,
        room_id=room_id
    ).first()

    if packet:
        # User has been approved, can join as participant
        return render(request, 'room.html', {
            'room_id': str(room_id),
            'user_id': str(request.user.id),
            'username': request.user.username,
            'organization': org,
            'is_moderator': False,
            'author_id': str(meeting.author.id)
        })

    # Check if meeting requires approval
    if not meeting.require_approval:
        # No approval required, join directly as participant
        return render(request, 'room.html', {
            'room_id': str(room_id),
            'user_id': str(request.user.id),
            'username': request.user.username,
            'organization': org,
            'is_moderator': False,
            'author_id': str(meeting.author.id)
        })

    # User needs approval - store room info in session and redirect to pending
    request.session['pending_room_id'] = str(room_id)
    request.session['pending_author_id'] = meeting.author.id
    return redirect('pending_room')


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

    return render(request, 'pending.html', {
        'room_id': room_id,
        'author_id': author_id,
        'user_id': user_id,
        'username': username,
        'pending_token': pending_token
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
    personal_room, created = PersonalRoom.objects.get_or_create(
        user=request.user,
        organization=request.organization
    )

    # Build full URLs
    base_url = request.build_absolute_uri('/')[:-1]  # Remove trailing slash
    moderator_link = f"{base_url}{personal_room.get_moderator_link()}"
    attendee_link = f"{base_url}{personal_room.get_attendee_link()}"

    return render(request, 'my_room.html', {
        'room': personal_room,
        'moderator_link': moderator_link,
        'attendee_link': attendee_link,
        'organization': request.organization
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

    # Check if room is locked and user is not moderator
    if personal_room.is_locked and is_attendee:
        # Check if user has been approved
        is_approved = False

        # For authenticated users, check UserMeetingPacket
        if request.user.is_authenticated:
            packet = UserMeetingPacket.objects.filter(
                room_id=room_id,
                user__id=request.user.id
            ).first()
            is_approved = packet is not None
        else:
            # For guests, check session for approval
            approved_key = f'approved_for_{room_id}'
            is_approved = request.session.get(approved_key, False)

        if not is_approved:
            # User needs approval - store room info in session and redirect to pending
            request.session['pending_room_id'] = str(room_id)
            request.session['pending_author_id'] = personal_room.user.id
            request.session['pending_user_id'] = user_id
            request.session['pending_username'] = username
            request.session['pending_token'] = token
            return redirect('pending_room')

    return render(request, 'room.html', {
        'room_id': str(room_id),
        'user_id': user_id,
        'username': username,
        'is_moderator': is_moderator,
        'room_owner': personal_room.user.username,
        'room_name': personal_room.room_name,
        'organization': personal_room.organization,
        'is_locked': personal_room.is_locked
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
    """Toggle lock state of a personal room"""
    try:
        data = json.loads(request.body)
        is_locked = data.get('is_locked', False)
        token = data.get('token', '')

        personal_room = get_object_or_404(PersonalRoom, room_id=room_id)

        # Verify the request is from the moderator
        if token != personal_room.moderator_token:
            return JsonResponse({'error': 'Unauthorized'}, status=403)

        personal_room.is_locked = is_locked
        personal_room.save()

        return JsonResponse({
            'success': True,
            'is_locked': personal_room.is_locked
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


def get_room_lock_status_view(request, room_id):
    """Get lock status of a personal room"""
    personal_room = get_object_or_404(PersonalRoom, room_id=room_id)
    return JsonResponse({
        'is_locked': personal_room.is_locked
    })


@require_POST
def mark_guest_approved_view(request, room_id):
    """Mark a guest as approved for a room (stores in session)"""
    try:
        # Verify the room exists
        personal_room = get_object_or_404(PersonalRoom, room_id=room_id)

        # Verify approval token from the pending session
        # This ensures only users who went through the approval flow can be marked approved
        pending_room_id = request.session.get('pending_room_id')
        if str(pending_room_id) != str(room_id):
            return JsonResponse({'error': 'Invalid approval request'}, status=403)

        # Set approval in session
        approved_key = f'approved_for_{room_id}'
        request.session[approved_key] = True

        # Clean up pending session data
        for key in ['pending_room_id', 'pending_author_id', 'pending_user_id', 'pending_username', 'pending_token']:
            request.session.pop(key, None)

        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)
