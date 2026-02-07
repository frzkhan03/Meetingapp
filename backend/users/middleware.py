from django.core.cache import cache
from django.http import Http404
from django.utils.deprecation import MiddlewareMixin
from .models import Organization, Profile


class TenantMiddleware(MiddlewareMixin):
    """
    Middleware to set the current organization (tenant) context for each request.
    Uses Redis caching to avoid hitting the database on every request.
    Supports custom subdomains (e.g., acme.pytalk.veriright.com).
    """

    # Main domain - subdomains of this are checked for org resolution
    MAIN_DOMAIN = 'pytalk.veriright.com'

    def process_request(self, request):
        request.organization = None
        request.subdomain_org = None  # Org from subdomain (for branding even when not logged in)
        request.is_subdomain_request = False  # Track if this is a subdomain request

        # Check for custom subdomain first (works for both authenticated and anonymous users)
        subdomain_result = self._get_org_from_subdomain(request)

        if subdomain_result == 'invalid':
            # Subdomain was requested but doesn't exist - return 404
            raise Http404("Organization not found")

        if subdomain_result:
            request.subdomain_org = subdomain_result
            request.is_subdomain_request = True

        # Skip further processing for unauthenticated users
        if not request.user.is_authenticated:
            return

        # If subdomain org exists and user is a member, use it
        if request.subdomain_org:
            if self._is_member_cached(request.user.id, str(request.subdomain_org.id)):
                request.organization = request.subdomain_org
                request.session['current_organization_id'] = str(request.subdomain_org.id)
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

    def _get_org_from_subdomain(self, request):
        """
        Extract subdomain from host and resolve to Organization.
        Returns:
            - Organization if subdomain matches and org has Business plan
            - 'invalid' if subdomain was requested but doesn't exist
            - None if not a subdomain request (main domain)
        """
        host = request.get_host().split(':')[0]  # Remove port if present

        # Check if host is a subdomain of the main domain
        if not host.endswith('.' + self.MAIN_DOMAIN):
            return None  # Not a subdomain request

        # Extract subdomain
        subdomain = host[:-len('.' + self.MAIN_DOMAIN)]
        if not subdomain or '.' in subdomain:  # Ignore multi-level subdomains
            return None  # Main domain or invalid format

        # Look up organization by subdomain (or slug as fallback)
        cache_key = f'org:subdomain:{subdomain}'
        org = cache.get(cache_key)
        if org is None:
            try:
                # Try subdomain field first, then fall back to slug
                org = Organization.objects.get(subdomain=subdomain, is_active=True)
            except Organization.DoesNotExist:
                try:
                    org = Organization.objects.get(slug=subdomain, is_active=True)
                except Organization.DoesNotExist:
                    cache.set(cache_key, 'invalid', 300)  # Cache miss as invalid
                    return 'invalid'
            cache.set(cache_key, org, 300)
        elif org == 'invalid':  # Cached invalid subdomain
            return 'invalid'

        # Check if org has Business plan (subdomain feature)
        try:
            from billing.plan_limits import get_plan_limits
            limits = get_plan_limits(org)
            if not limits.can_use_custom_subdomain():
                return 'invalid'  # Org exists but doesn't have subdomain feature
        except ImportError:
            return 'invalid'

        return org


def get_current_organization(request):
    """Helper function to get current organization from request"""
    return getattr(request, 'organization', None)
