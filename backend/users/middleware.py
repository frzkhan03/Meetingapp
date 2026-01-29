from django.utils.deprecation import MiddlewareMixin
from .models import Organization, Profile


class TenantMiddleware(MiddlewareMixin):
    """
    Middleware to set the current organization (tenant) context for each request.
    The tenant can be determined by:
    1. Subdomain (e.g., acme.pytalk.com)
    2. User's current_organization in their profile
    3. Session variable
    """

    def process_request(self, request):
        request.organization = None

        # Skip for unauthenticated users
        if not request.user.is_authenticated:
            return

        # Try to get organization from session first
        org_id = request.session.get('current_organization_id')
        if org_id:
            try:
                org = Organization.objects.get(id=org_id, is_active=True)
                # Verify user is a member
                if org.memberships.filter(user=request.user, is_active=True).exists():
                    request.organization = org
                    return
            except Organization.DoesNotExist:
                pass

        # Try to get from user's profile
        try:
            profile = request.user.profile
            if profile.current_organization and profile.current_organization.is_active:
                if profile.current_organization.memberships.filter(
                    user=request.user, is_active=True
                ).exists():
                    request.organization = profile.current_organization
                    request.session['current_organization_id'] = str(profile.current_organization.id)
                    return
        except Profile.DoesNotExist:
            pass

        # Get first organization user belongs to
        membership = request.user.memberships.filter(is_active=True).first()
        if membership:
            request.organization = membership.organization
            request.session['current_organization_id'] = str(membership.organization.id)

            # Update profile if it exists
            try:
                profile = request.user.profile
                profile.current_organization = membership.organization
                profile.save()
            except Profile.DoesNotExist:
                pass


def get_current_organization(request):
    """Helper function to get current organization from request"""
    return getattr(request, 'organization', None)
