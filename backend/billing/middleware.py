from django.utils.deprecation import MiddlewareMixin


class SubscriptionMiddleware(MiddlewareMixin):
    """
    Injects plan limits into every request that has an organization context.
    Must run AFTER TenantMiddleware.
    """

    def process_request(self, request):
        request.plan_limits = None
        request.plan_tier = 'free'

        org = getattr(request, 'organization', None)
        if org:
            from .plan_limits import get_plan_limits
            limits = get_plan_limits(org)
            request.plan_limits = limits
            request.plan_tier = limits.tier
