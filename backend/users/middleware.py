from django.core.cache import cache
from django.utils.deprecation import MiddlewareMixin
from .models import Organization, Profile


class TenantMiddleware(MiddlewareMixin):
    """
    Middleware to set the current organization (tenant) context for each request.
    Uses Redis caching to avoid hitting the database on every request.
    """

    def process_request(self, request):
        request.organization = None

        # Skip for unauthenticated users
        if not request.user.is_authenticated:
            return

        # Try to get organization from session first
        org_id = request.session.get('current_organization_id')
        if org_id:
            org = self._get_cached_org(org_id)
            if org and self._is_member_cached(request.user.id, org_id):
                request.organization = org
                return

        # Try to get from user's profile
        try:
            profile = request.user.profile
            if profile.current_organization_id:
                co_id = str(profile.current_organization_id)
                org = self._get_cached_org(co_id)
                if org and org.is_active and self._is_member_cached(request.user.id, co_id):
                    request.organization = org
                    request.session['current_organization_id'] = co_id
                    return
        except Profile.DoesNotExist:
            pass

        # Get first organization user belongs to
        membership = request.user.memberships.filter(
            is_active=True
        ).select_related('organization').first()
        if membership:
            request.organization = membership.organization
            request.session['current_organization_id'] = str(membership.organization.id)

            # Update profile if it exists
            try:
                profile = request.user.profile
                profile.current_organization = membership.organization
                profile.save(update_fields=['current_organization', 'updated_at'])
            except Profile.DoesNotExist:
                pass

    def _get_cached_org(self, org_id):
        """Get organization by ID with 5 min cache."""
        cache_key = f'org:{org_id}'
        org = cache.get(cache_key)
        if org is None:
            try:
                org = Organization.objects.get(id=org_id, is_active=True)
                cache.set(cache_key, org, 300)
            except Organization.DoesNotExist:
                return None
        return org

    def _is_member_cached(self, user_id, org_id):
        """Check membership with 5 min cache."""
        cache_key = f'user:{user_id}:org:{org_id}:member'
        result = cache.get(cache_key)
        if result is None:
            from .models import OrganizationMembership
            result = OrganizationMembership.objects.filter(
                user_id=user_id, organization_id=org_id, is_active=True
            ).exists()
            cache.set(cache_key, result, 300)
        return result


def get_current_organization(request):
    """Helper function to get current organization from request"""
    return getattr(request, 'organization', None)
