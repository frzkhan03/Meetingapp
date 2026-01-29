from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.db import IntegrityError
from django.http import JsonResponse
from django.utils.text import slugify
from django.utils.crypto import get_random_string
from django.core.paginator import Paginator
from django.views.decorators.http import require_POST
from .forms import RegisterForm, LoginForm, OrganizationForm
from .models import Organization, OrganizationMembership, Profile
from meetings.models import PersonalRoom


def _create_unique_slug(base_name):
    """Generate a unique organization slug, retrying on collision."""
    base_slug = slugify(base_name)
    slug = base_slug
    counter = 1
    while Organization.objects.filter(slug=slug).exists():
        slug = f"{base_slug}-{counter}"
        counter += 1
        if counter > 20:
            slug = f"{base_slug}-{get_random_string(6)}"
            break
    return slug


def register_view(request):
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':
        form = RegisterForm(request.POST)
        org_name = request.POST.get('organization_name', '').strip()

        if form.is_valid():
            user = form.save()

            # Create profile for user
            profile = Profile.objects.create(user=user)

            # Create or join organization
            if org_name:
                # Create new organization
                slug = _create_unique_slug(org_name)
                org = Organization.objects.create(
                    name=org_name,
                    slug=slug
                )
                OrganizationMembership.objects.create(
                    user=user,
                    organization=org,
                    role='owner'
                )
                # Create personal room for the user
                PersonalRoom.objects.create(
                    user=user,
                    organization=org
                )
                profile.current_organization = org
                profile.save()
            else:
                # Create a personal organization
                slug = _create_unique_slug(f"{user.username}-org")
                org = Organization.objects.create(
                    name=f"{user.username}'s Organization",
                    slug=slug
                )
                OrganizationMembership.objects.create(
                    user=user,
                    organization=org,
                    role='owner'
                )
                # Create personal room for the user
                PersonalRoom.objects.create(
                    user=user,
                    organization=org
                )
                profile.current_organization = org
                profile.save()

            login(request, user)
            messages.success(request, 'Registration successful!')
            return redirect('home')
        else:
            messages.error(request, 'Registration failed. Please check the form.')
    else:
        form = RegisterForm()

    return render(request, 'register.html', {'form': form})


def login_view(request):
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(username=username, password=password)
            if user is not None:
                login(request, user)
                messages.success(request, f'Welcome back, {username}!')
                next_url = request.GET.get('next', 'home')
                return redirect(next_url)
        messages.error(request, 'Invalid username or password.')
    else:
        form = LoginForm()

    return render(request, 'login.html', {'form': form})


def logout_view(request):
    logout(request)
    messages.info(request, 'You have been logged out.')
    return redirect('home')


@login_required
def organization_list_view(request):
    """List all organizations the user belongs to"""
    memberships = request.user.memberships.filter(is_active=True).select_related('organization')
    paginator = Paginator(memberships, 10)
    page_obj = paginator.get_page(request.GET.get('page', 1))
    return render(request, 'organizations.html', {'memberships': page_obj, 'page_obj': page_obj})


@login_required
def organization_create_view(request):
    """Create a new organization"""
    if request.method == 'POST':
        form = OrganizationForm(request.POST)
        if form.is_valid():
            org = form.save(commit=False)
            org.slug = _create_unique_slug(org.name)
            org.save()

            # Add creator as owner
            OrganizationMembership.objects.create(
                user=request.user,
                organization=org,
                role='owner'
            )

            messages.success(request, f'Organization "{org.name}" created successfully!')
            return redirect('organization_switch', org_id=org.id)
    else:
        form = OrganizationForm()

    return render(request, 'organization_create.html', {'form': form})


@login_required
def organization_switch_view(request, org_id):
    """Switch to a different organization"""
    org = get_object_or_404(Organization, id=org_id, is_active=True)

    # Verify user is a member
    if not org.memberships.filter(user=request.user, is_active=True).exists():
        messages.error(request, 'You are not a member of this organization.')
        return redirect('organization_list')

    # Update session and profile
    request.session['current_organization_id'] = str(org.id)

    try:
        profile = request.user.profile
        profile.current_organization = org
        profile.save()
    except Profile.DoesNotExist:
        Profile.objects.create(user=request.user, current_organization=org)

    messages.success(request, f'Switched to {org.name}')
    return redirect('home')


@login_required
def organization_settings_view(request, org_id):
    """Organization settings (for owners/admins)"""
    org = get_object_or_404(Organization, id=org_id, is_active=True)

    # Check if user has admin/owner role
    membership = org.memberships.filter(user=request.user, is_active=True).first()
    if not membership or membership.role not in ['owner', 'admin']:
        messages.error(request, 'You do not have permission to manage this organization.')
        return redirect('organization_list')

    if request.method == 'POST':
        org.name = request.POST.get('name', org.name)
        org.save()
        messages.success(request, 'Organization updated successfully!')
        return redirect('organization_settings', org_id=org.id)

    members_qs = org.memberships.select_related('user').order_by('-is_active', '-joined_at')

    # Search filter
    search_query = request.GET.get('q', '').strip()
    if search_query:
        members_qs = members_qs.filter(user__username__icontains=search_query)

    paginator = Paginator(members_qs, 10)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    # Attach room links — only load rooms for the current page of members
    base_url = request.build_absolute_uri('/')[:-1]
    page_user_ids = [m.user_id for m in page_obj]
    rooms_by_user = {}
    rooms = PersonalRoom.objects.filter(
        organization=org, user_id__in=page_user_ids
    ).select_related('user')
    for room in rooms:
        rooms_by_user[room.user_id] = room

    for m in page_obj:
        room = rooms_by_user.get(m.user_id)
        if room:
            m.moderator_link = f"{base_url}{room.get_moderator_link()}"
            m.attendee_link = f"{base_url}{room.get_attendee_link()}"
        else:
            m.moderator_link = ''
            m.attendee_link = ''

    return render(request, 'organization_settings.html', {
        'organization': org,
        'members': page_obj,
        'page_obj': page_obj,
        'total_members': paginator.count,
        'search_query': search_query,
        'is_owner': membership.role == 'owner',
        'is_admin': membership.role in ['owner', 'admin'],
    })


@login_required
def organization_add_member_view(request, org_id):
    """Add a user/member to the organization"""
    org = get_object_or_404(Organization, id=org_id, is_active=True)

    # Check if user has admin/owner role
    membership = org.memberships.filter(user=request.user, is_active=True).first()
    if not membership or membership.role not in ['owner', 'admin']:
        messages.error(request, 'You do not have permission to add members.')
        return redirect('organization_settings', org_id=org.id)

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        role = request.POST.get('role', 'member')

        # Validate inputs
        if not username or not email:
            messages.error(request, 'Username and email are required.')
            return redirect('organization_settings', org_id=org.id)

        # Check if username already exists
        existing_user = User.objects.filter(username__iexact=username).first()
        if existing_user:
            if org.memberships.filter(user=existing_user).exists():
                messages.warning(request, f'{username} is already a member of this organization.')
            else:
                # Add existing user to organization
                OrganizationMembership.objects.create(
                    user=existing_user,
                    organization=org,
                    role=role
                )
                PersonalRoom.objects.get_or_create(user=existing_user, organization=org)
                # Update user's current organization
                profile, _ = Profile.objects.get_or_create(user=existing_user)
                profile.current_organization = org
                profile.save()
                messages.success(request, f'{username} has been added to the organization.')
            return redirect('organization_settings', org_id=org.id)

        # Check if email already exists
        if User.objects.filter(email__iexact=email).exists():
            messages.error(request, f'A user with email "{email}" already exists with a different username.')
            return redirect('organization_settings', org_id=org.id)

        # Create new user with auto-generated password
        temp_password = get_random_string(12)
        user = User.objects.create_user(
            username=username,
            email=email,
            password=temp_password
        )

        # Create profile with current organization
        Profile.objects.create(user=user, current_organization=org)

        # Create membership
        OrganizationMembership.objects.create(
            user=user,
            organization=org,
            role=role
        )

        # Create personal room for the new member
        PersonalRoom.objects.get_or_create(user=user, organization=org)

        messages.success(
            request,
            f'Member "{username}" created successfully! Temporary password: {temp_password} (Please share this securely with the user)'
        )

    return redirect('organization_settings', org_id=org.id)


@login_required
@require_POST
def reset_member_password_view(request, org_id, user_id):
    """Reset a member's password (owner/admin only)"""
    org = get_object_or_404(Organization, id=org_id, is_active=True)

    # Check caller is owner/admin
    caller_membership = org.memberships.filter(user=request.user, is_active=True).first()
    if not caller_membership or caller_membership.role not in ['owner', 'admin']:
        return JsonResponse({'error': 'Permission denied.'}, status=403)

    # Check target user is a member
    target_membership = org.memberships.filter(user_id=user_id, is_active=True).first()
    if not target_membership:
        return JsonResponse({'error': 'User is not a member of this organization.'}, status=404)

    # Prevent non-owners from resetting owner passwords
    if target_membership.role == 'owner' and caller_membership.role != 'owner':
        return JsonResponse({'error': 'Only owners can reset other owner passwords.'}, status=403)

    target_user = target_membership.user
    new_password = get_random_string(12)
    target_user.set_password(new_password)
    target_user.save()

    return JsonResponse({'password': new_password, 'username': target_user.username})


@login_required
@require_POST
def deactivate_member_view(request, org_id, user_id):
    """Toggle a member's active status (owner/admin only)"""
    org = get_object_or_404(Organization, id=org_id, is_active=True)

    caller_membership = org.memberships.filter(user=request.user, is_active=True).first()
    if not caller_membership or caller_membership.role not in ['owner', 'admin']:
        return JsonResponse({'error': 'Permission denied.'}, status=403)

    target_membership = org.memberships.filter(user_id=user_id).first()
    if not target_membership:
        return JsonResponse({'error': 'User is not a member of this organization.'}, status=404)

    if target_membership.role == 'owner' and caller_membership.role != 'owner':
        return JsonResponse({'error': 'Only owners can deactivate other owners.'}, status=403)

    target_membership.is_active = not target_membership.is_active
    target_membership.save()

    status = 'activated' if target_membership.is_active else 'deactivated'
    return JsonResponse({'status': status, 'username': target_membership.user.username})


@login_required
@require_POST
def delete_member_view(request, org_id, user_id):
    """Permanently delete a member's account (owner/admin only)"""
    org = get_object_or_404(Organization, id=org_id, is_active=True)

    caller_membership = org.memberships.filter(user=request.user, is_active=True).first()
    if not caller_membership or caller_membership.role not in ['owner', 'admin']:
        return JsonResponse({'error': 'Permission denied.'}, status=403)

    target_membership = org.memberships.filter(user_id=user_id).first()
    if not target_membership:
        return JsonResponse({'error': 'User is not a member of this organization.'}, status=404)

    if target_membership.role == 'owner' and caller_membership.role != 'owner':
        return JsonResponse({'error': 'Only owners can delete other owners.'}, status=403)

    target_user = target_membership.user
    username = target_user.username
    target_user.delete()

    return JsonResponse({'status': 'deleted', 'username': username})
