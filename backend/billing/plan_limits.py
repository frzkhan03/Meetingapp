"""
Central module for checking plan limits.
All feature checks funnel through here.
"""
from django.core.cache import cache
from django.conf import settings


class PlanLimits:
    """
    Resolved plan limits for an organization.
    Cached for 5 minutes.
    """

    def __init__(self, organization):
        self.organization = organization
        self._limits = self._resolve_limits()

    def _resolve_limits(self):
        cache_key = f'billing:limits:{self.organization.pk}'
        limits = cache.get(cache_key)
        if limits is not None:
            return limits

        # Default free-tier limits
        defaults = {
            'tier': 'free',
            'max_rooms': 1,
            'max_participants': 4,
            'max_meeting_duration_minutes': 30,
            'recording_enabled': False,
            'custom_branding': False,
            'custom_subdomain': False,
            'breakout_rooms': False,
            'waiting_rooms': False,
        }

        if not getattr(settings, 'PAYU_ENABLED', False):
            cache.set(cache_key, defaults, 300)
            return defaults

        try:
            from billing.models import Subscription
            sub = Subscription.objects.select_related('plan').get(
                organization=self.organization
            )
            if sub.is_active_subscription:
                plan = sub.plan
                limits = {
                    'tier': plan.tier,
                    'max_rooms': plan.max_rooms,
                    'max_participants': plan.max_participants,
                    'max_meeting_duration_minutes': plan.max_meeting_duration_minutes,
                    'recording_enabled': plan.recording_enabled,
                    'custom_branding': plan.custom_branding,
                    'custom_subdomain': plan.custom_subdomain,
                    'breakout_rooms': plan.breakout_rooms,
                    'waiting_rooms': plan.waiting_rooms,
                }
            else:
                limits = defaults
        except Exception:
            limits = defaults

        cache.set(cache_key, limits, 300)
        return limits

    @property
    def tier(self):
        return self._limits['tier']

    @property
    def max_rooms(self):
        return self._limits['max_rooms']

    @property
    def max_participants(self):
        return self._limits['max_participants']

    @property
    def max_meeting_duration_minutes(self):
        return self._limits['max_meeting_duration_minutes']

    @property
    def recording_enabled(self):
        return self._limits['recording_enabled']

    @property
    def has_unlimited_rooms(self):
        return self.max_rooms == -1

    @property
    def has_unlimited_duration(self):
        return self.max_meeting_duration_minutes == -1

    def can_create_room(self):
        if self.has_unlimited_rooms:
            return True
        from meetings.models import PersonalRoom
        current_count = PersonalRoom.objects.filter(
            organization=self.organization, is_active=True
        ).count()
        return current_count < self.max_rooms

    def can_record(self):
        return self.recording_enabled

    def can_use_waiting_room(self):
        return self._limits['waiting_rooms']

    def can_use_custom_branding(self):
        return self._limits['custom_branding']

    def can_use_custom_subdomain(self):
        return self._limits['custom_subdomain']

    def can_use_breakout_rooms(self):
        return self._limits['breakout_rooms']

    def get_participant_limit(self):
        return self.max_participants

    def get_duration_limit_seconds(self):
        if self.has_unlimited_duration:
            return None
        return self.max_meeting_duration_minutes * 60


def get_plan_limits(organization):
    return PlanLimits(organization)


def invalidate_plan_cache(organization_id):
    cache.delete(f'billing:limits:{organization_id}')
