from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.conf import settings
from django.db import IntegrityError
from django.http import JsonResponse
from django.utils.text import slugify
from django.utils.crypto import get_random_string
from django.core.paginator import Paginator
from django.views.decorators.http import require_POST
from .forms import RegisterForm, LoginForm, OrganizationForm
from .models import Organization, OrganizationMembership, Profile
from .tasks import setup_user_in_org
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
    import re

    if request.user.is_authenticated:
        return redirect('home')

    valid_tiers = ('pro', 'business')
    valid_cycles = ('monthly', 'annual')
    subdomain_error = None

    if request.method == 'POST':
        form = RegisterForm(request.POST)
        org_name = request.POST.get('organization_name', '').strip()
        subdomain = request.POST.get('subdomain', '').strip().lower()

        # Read plan selection from hidden fields
        selected_plan = request.POST.get('selected_plan', '').strip()
        selected_cycle = request.POST.get('selected_cycle', 'monthly').strip()
        if selected_plan not in valid_tiers:
            selected_plan = ''
        if selected_cycle not in valid_cycles:
            selected_cycle = 'monthly'

        # Only validate/use subdomain for business plan (only tier that supports custom subdomains)
        if selected_plan != 'business':
            subdomain = ''

        # Validate subdomain if org name is provided
        if org_name and subdomain:
            subdomain_pattern = re.compile(r'^[a-z0-9]([a-z0-9-]*[a-z0-9])?$')
            reserved = ['www', 'api', 'admin', 'mail', 'ftp', 'smtp', 'pop', 'imap',
                        'test', 'dev', 'staging', 'production', 'app', 'static',
                        'assets', 'cdn', 'ns1', 'ns2', 'pytalk', 'support', 'help']

            if len(subdomain) < 2 or len(subdomain) > 63:
                subdomain_error = 'Subdomain must be 2-63 characters.'
            elif not subdomain_pattern.match(subdomain):
                subdomain_error = 'Only lowercase letters, numbers, and hyphens allowed.'
            elif '--' in subdomain:
                subdomain_error = 'Cannot have consecutive hyphens.'
            elif subdomain in reserved:
                subdomain_error = f'"{subdomain}" is reserved. Please choose another.'
            elif Organization.objects.filter(subdomain=subdomain).exists():
                subdomain_error = 'This subdomain is already taken.'

        if form.is_valid() and not subdomain_error:
            user = form.save()

            # Create profile for user
            profile = Profile.objects.create(user=user)

            # Create or join organization
            if org_name:
                slug = _create_unique_slug(org_name)
                # Only set subdomain for business plan users
                final_subdomain = subdomain if subdomain else ''
                org = Organization.objects.create(name=org_name, slug=slug, subdomain=final_subdomain)
            else:
                slug = _create_unique_slug(f"{user.username}-org")
                org = Organization.objects.create(
                    name=f"{user.username}'s Organization",
                    slug=slug
                )

            OrganizationMembership.objects.create(
                user=user, organization=org, role='owner'
            )
            profile.current_organization = org
            profile.save(update_fields=['current_organization', 'updated_at'])

            # Set session org so TenantMiddleware picks it up on the next request
            request.session['current_organization_id'] = str(org.id)

            # Create personal room in background (not needed for login)
            setup_user_in_org.delay(user.id, str(org.id))

            login(request, user)
            messages.success(request, 'Registration successful!')

            # Redirect to checkout if a paid plan was selected
            # Only redirect to subdomain URL if user selected Business plan (which enables subdomain feature)
            if selected_plan == 'business' and org.subdomain:
                base_domain = getattr(settings, 'BASE_DOMAIN', 'pytalk.veriright.com')
                protocol = 'https' if settings.PRODUCTION else 'http'
                redirect_url = f'{protocol}://{org.subdomain}.{base_domain}/billing/checkout/{selected_plan}/{selected_cycle}/'
                return redirect(redirect_url)
            elif selected_plan:
                return redirect('billing_checkout', plan_tier=selected_plan, billing_cycle=selected_cycle)

            return redirect('home')
        else:
            if not subdomain_error:
                messages.error(request, 'Registration failed. Please check the form.')
    else:
        form = RegisterForm()
        selected_plan = request.GET.get('plan', '').strip()
        selected_cycle = request.GET.get('cycle', 'monthly').strip()
        if selected_plan not in valid_tiers:
            selected_plan = ''
        if selected_cycle not in valid_cycles:
            selected_cycle = 'monthly'

    # Look up plan details for the banner
    selected_plan_obj = None
    if selected_plan:
        from billing.models import Plan
        selected_plan_obj = Plan.objects.filter(tier=selected_plan, is_active=True).first()

    return render(request, 'register.html', {
        'form': form,
        'selected_plan': selected_plan,
        'selected_cycle': selected_cycle,
        'selected_plan_obj': selected_plan_obj,
        'subdomain_error': subdomain_error,
        'organization_name_value': request.POST.get('organization_name', '') if request.method == 'POST' else '',
        'subdomain_value': request.POST.get('subdomain', '') if request.method == 'POST' else '',
    })


def _get_subdomain_redirect_url(request, org):
    """Build redirect URL for organization's subdomain if it has one."""
    if not org or not org.subdomain:
        return None

    # Build subdomain URL
    scheme = 'https' if request.is_secure() else 'http'
    # Get base domain from settings or request
    base_domain = getattr(settings, 'BASE_DOMAIN', 'pytalk.veriright.com')
    subdomain_url = f"{scheme}://{org.subdomain}.{base_domain}/"
    return subdomain_url


def _get_post_login_redirect(request, user):
    """Determine where to redirect user after login."""
    from billing.plan_limits import get_plan_limits

    # Get user's organizations
    memberships = user.memberships.filter(is_active=True).select_related('organization')
    # Only consider orgs that have a subdomain AND an active plan that supports it
    orgs_with_subdomain = []
    for m in memberships:
        if m.organization.subdomain:
            plan_limits = get_plan_limits(m.organization)
            if plan_limits.can_use_custom_subdomain():
                orgs_with_subdomain.append(m.organization)

    if len(orgs_with_subdomain) == 1:
        # User has exactly one org with active subdomain support - redirect there
        org = orgs_with_subdomain[0]
        # Set session and profile
        request.session['current_organization_id'] = str(org.id)
        try:
            profile = user.profile
            profile.current_organization = org
            profile.save()
        except Profile.DoesNotExist:
            Profile.objects.create(user=user, current_organization=org)

        subdomain_url = _get_subdomain_redirect_url(request, org)
        if subdomain_url:
            return subdomain_url

    elif len(memberships) == 1:
        # User has exactly one org (without subdomain) - set it as current
        org = memberships[0].organization
        request.session['current_organization_id'] = str(org.id)
        try:
            profile = user.profile
            profile.current_organization = org
            profile.save()
        except Profile.DoesNotExist:
            Profile.objects.create(user=user, current_organization=org)

    # Multiple orgs or no subdomain - go to home
    return None


def login_view(request):
    from django.utils.http import url_has_allowed_host_and_scheme

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
                next_url = request.GET.get('next', '')
                # Validate redirect URL to prevent open redirect attacks
                if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
                    return redirect(next_url)

                # Check for subdomain redirect
                subdomain_redirect = _get_post_login_redirect(request, user)
                if subdomain_redirect:
                    return redirect(subdomain_redirect)

                return redirect('home')
        messages.error(request, 'Invalid username or password.')
    else:
        form = LoginForm()

    return render(request, 'login.html', {'form': form})


@require_POST
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

            # Create personal room in background
            setup_user_in_org.delay(request.user.id, str(org.id))

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

    # Invalidate cached org data for this user
    Profile.invalidate_org_cache(request.user.id, str(org.id))

    messages.success(request, f'Switched to {org.name}')

    # Redirect to subdomain if org has one
    subdomain_url = _get_subdomain_redirect_url(request, org)
    if subdomain_url:
        return redirect(subdomain_url)

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
        from meet.validators import sanitize_input
        name = request.POST.get('name', org.name)
        org.name = sanitize_input(name, max_length=255) or org.name
        org.recording_to_s3 = request.POST.get('recording_to_s3') == 'on'
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

    # Get plan limits for branding gating
    plan_limits = getattr(request, 'plan_limits', None)
    can_use_branding = plan_limits.can_use_custom_branding() if plan_limits else False
    can_use_subdomain = plan_limits.can_use_custom_subdomain() if plan_limits else False

    return render(request, 'organization_settings.html', {
        'organization': org,
        'members': page_obj,
        'page_obj': page_obj,
        'total_members': paginator.count,
        'search_query': search_query,
        'is_owner': membership.role == 'owner',
        'is_admin': membership.role in ['owner', 'admin'],
        'can_use_branding': can_use_branding,
        'can_use_subdomain': can_use_subdomain,
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
                # Create personal room and update profile in background
                setup_user_in_org.delay(existing_user.id, str(org.id))
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

        # Create profile and membership (required immediately)
        Profile.objects.create(user=user, current_organization=org)
        OrganizationMembership.objects.create(
            user=user, organization=org, role=role
        )

        # Create personal room in background
        setup_user_in_org.delay(user.id, str(org.id))

        # Send temporary password via email to the new user
        try:
            from django.core.mail import send_mail
            send_mail(
                'Your PyTalk Account',
                f'Hello {username},\n\nYour account has been created.\nTemporary password: {temp_password}\n\nPlease change your password after first login.',
                settings.EMAIL_HOST_USER or 'noreply@pytalk.com',
                [email],
                fail_silently=True,
            )
            messages.success(request, f'Member "{username}" created successfully! Temporary password sent to {email}.')
        except Exception:
            messages.success(request, f'Member "{username}" created successfully! Please reset their password from the settings page.')

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

    # Invalidate cached membership/role data for the affected user
    Profile.invalidate_org_cache(user_id, str(org.id))

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

    # Invalidate cached data before deletion
    Profile.invalidate_org_cache(user_id, str(org.id))

    target_user.delete()

    return JsonResponse({'status': 'deleted', 'username': username})


@login_required
@require_POST
def upload_organization_logo(request, org_id):
    """Upload organization logo to S3 (Business plan only)"""
    import re
    import uuid as uuid_module
    from django.conf import settings

    org = get_object_or_404(Organization, id=org_id, is_active=True)

    # Check if user is owner/admin
    membership = org.memberships.filter(user=request.user, is_active=True).first()
    if not membership or membership.role not in ['owner', 'admin']:
        return JsonResponse({'error': 'Permission denied.'}, status=403)

    # Check plan allows custom branding
    plan_limits = getattr(request, 'plan_limits', None)
    if not plan_limits or not plan_limits.can_use_custom_branding():
        return JsonResponse({'error': 'Custom branding requires a Business plan.'}, status=403)

    logo_file = request.FILES.get('logo')
    if not logo_file:
        return JsonResponse({'error': 'No logo file provided.'}, status=400)

    # Validate file type
    allowed_types = ['image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/svg+xml']
    if logo_file.content_type not in allowed_types:
        return JsonResponse({'error': 'Invalid file type. Allowed: PNG, JPG, GIF, WebP, SVG'}, status=400)

    # Limit file size (2MB)
    if logo_file.size > 2 * 1024 * 1024:
        return JsonResponse({'error': 'Logo file too large. Max 2MB.'}, status=400)

    # Check AWS config
    if not settings.AWS_ACCESS_KEY_ID or not settings.AWS_SECRET_ACCESS_KEY:
        return JsonResponse({'error': 'S3 storage is not configured.'}, status=500)

    try:
        import boto3

        # Determine file extension from content type
        ext_map = {
            'image/png': 'png',
            'image/jpeg': 'jpg',
            'image/gif': 'gif',
            'image/webp': 'webp',
            'image/svg+xml': 'svg',
        }
        ext = ext_map.get(logo_file.content_type, 'png')

        s3_key = f"organizations/{org.id}/branding/logo.{ext}"

        s3_client = boto3.client(
            's3',
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_S3_REGION,
        )

        s3_client.upload_fileobj(
            logo_file,
            settings.AWS_S3_BUCKET_NAME,
            s3_key,
            ExtraArgs={'ContentType': logo_file.content_type}
        )

        # Build the public URL
        logo_url = f"https://{settings.AWS_S3_BUCKET_NAME}.s3.{settings.AWS_S3_REGION}.amazonaws.com/{s3_key}"

        # Save to organization
        org.logo = logo_url
        org.save(update_fields=['logo', 'updated_at'])

        return JsonResponse({'success': True, 'logo_url': logo_url})

    except Exception as e:
        return JsonResponse({'error': f'Upload failed: {str(e)}'}, status=500)


@login_required
@require_POST
def save_organization_branding(request, org_id):
    """Save organization branding colors (Business plan only)"""
    import re
    import json

    org = get_object_or_404(Organization, id=org_id, is_active=True)

    # Check if user is owner/admin
    membership = org.memberships.filter(user=request.user, is_active=True).first()
    if not membership or membership.role not in ['owner', 'admin']:
        return JsonResponse({'error': 'Permission denied.'}, status=403)

    # Check plan allows custom branding
    plan_limits = getattr(request, 'plan_limits', None)
    if not plan_limits or not plan_limits.can_use_custom_branding():
        return JsonResponse({'error': 'Custom branding requires a Business plan.'}, status=403)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON.'}, status=400)

    primary_color = data.get('primary_color', '').strip()
    secondary_color = data.get('secondary_color', '').strip()

    # Validate hex color format
    hex_pattern = re.compile(r'^#[0-9A-Fa-f]{6}$')

    if primary_color and not hex_pattern.match(primary_color):
        return JsonResponse({'error': 'Invalid primary color format. Use #RRGGBB.'}, status=400)

    if secondary_color and not hex_pattern.match(secondary_color):
        return JsonResponse({'error': 'Invalid secondary color format. Use #RRGGBB.'}, status=400)

    org.primary_color = primary_color
    org.secondary_color = secondary_color
    org.save(update_fields=['primary_color', 'secondary_color', 'updated_at'])

    return JsonResponse({'success': True})


@login_required
@require_POST
def remove_organization_logo(request, org_id):
    """Remove organization logo (Business plan only)"""
    org = get_object_or_404(Organization, id=org_id, is_active=True)

    # Check if user is owner/admin
    membership = org.memberships.filter(user=request.user, is_active=True).first()
    if not membership or membership.role not in ['owner', 'admin']:
        return JsonResponse({'error': 'Permission denied.'}, status=403)

    # Check plan allows custom branding (for consistency with upload)
    plan_limits = getattr(request, 'plan_limits', None)
    if not plan_limits or not plan_limits.can_use_custom_branding():
        return JsonResponse({'error': 'Custom branding requires a Business plan.'}, status=403)

    org.logo = None
    org.save(update_fields=['logo', 'updated_at'])

    return JsonResponse({'success': True})


@login_required
@require_POST
def save_organization_subdomain(request, org_id):
    """Save custom subdomain for organization (Business plan only)"""
    import re
    import json

    org = get_object_or_404(Organization, id=org_id, is_active=True)

    # Check if user is owner/admin
    membership = org.memberships.filter(user=request.user, is_active=True).first()
    if not membership or membership.role not in ['owner', 'admin']:
        return JsonResponse({'error': 'Permission denied.'}, status=403)

    # Check plan allows custom subdomain
    plan_limits = getattr(request, 'plan_limits', None)
    if not plan_limits or not plan_limits.can_use_custom_subdomain():
        return JsonResponse({'error': 'Custom subdomain requires a Business plan.'}, status=403)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON.'}, status=400)

    subdomain = data.get('subdomain', '').strip().lower()

    # Validate subdomain
    if not subdomain:
        return JsonResponse({'error': 'Subdomain cannot be empty.'}, status=400)

    if len(subdomain) < 2 or len(subdomain) > 63:
        return JsonResponse({'error': 'Subdomain must be 2-63 characters.'}, status=400)

    # Only lowercase alphanumeric and hyphens, must start/end with alphanumeric
    subdomain_pattern = re.compile(r'^[a-z0-9]([a-z0-9-]*[a-z0-9])?$')
    if not subdomain_pattern.match(subdomain):
        return JsonResponse({'error': 'Only lowercase letters, numbers, and hyphens allowed. Must start and end with a letter or number.'}, status=400)

    # No consecutive hyphens
    if '--' in subdomain:
        return JsonResponse({'error': 'Cannot have consecutive hyphens.'}, status=400)

    # Reserved subdomains
    reserved = ['www', 'api', 'admin', 'mail', 'ftp', 'smtp', 'pop', 'imap',
                'test', 'dev', 'staging', 'production', 'app', 'static',
                'assets', 'cdn', 'ns1', 'ns2', 'pytalk', 'support', 'help']
    if subdomain in reserved:
        return JsonResponse({'error': f'"{subdomain}" is a reserved subdomain. Please choose another.'}, status=400)

    # Check uniqueness (excluding current org)
    if Organization.objects.filter(subdomain=subdomain).exclude(id=org_id).exists():
        return JsonResponse({'error': 'This subdomain is already taken. Please choose another.'}, status=400)

    org.subdomain = subdomain
    org.save(update_fields=['subdomain', 'updated_at'])

    return JsonResponse({'success': True, 'subdomain': subdomain})
