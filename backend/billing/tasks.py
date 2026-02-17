import logging
from datetime import timedelta

from celery import shared_task
from django.db.models import Sum
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task
def process_recurring_billing():
    """
    Daily task: charge subscriptions where next_billing_date has passed.
    Uses stored PayU card tokens for server-initiated recurring charges.
    Retries failed payments for up to 3 days, then cancels after 7 days.
    """
    from .models import Plan, Subscription
    from .plan_limits import invalidate_plan_cache
    from .services import create_payu_recurring_order

    now = timezone.now()

    # Find active subscriptions due for billing
    due_subs = Subscription.objects.filter(
        next_billing_date__lte=now,
        cancel_at_period_end=False,
        is_complimentary=False,
        payu_card_token__gt='',
        status__in=['active', 'past_due'],
    ).exclude(plan__tier='free').select_related('plan', 'organization')

    charged = 0
    failed = 0

    for sub in due_subs:
        result = create_payu_recurring_order(sub)
        if result and result.get('order_id'):
            charged += 1
            logger.info(
                'Recurring charge initiated for org %s, order %s',
                sub.organization.name, result['order_id'],
            )
        else:
            failed += 1
            logger.warning(
                'Recurring charge failed for org %s', sub.organization.name,
            )
            # Mark past_due after first failure
            if sub.status == 'active':
                sub.status = 'past_due'
                sub.save(update_fields=['status', 'updated_at'])

    # Cancel subscriptions past_due for more than 7 days
    cutoff = now - timedelta(days=7)
    stale_subs = Subscription.objects.filter(
        status='past_due',
        next_billing_date__lte=cutoff,
        cancel_at_period_end=False,
        is_complimentary=False,
    ).exclude(plan__tier='free').select_related('organization')

    canceled = 0
    free_plan = Plan.objects.filter(tier='free').first()
    for sub in stale_subs:
        sub.status = 'canceled'
        sub.canceled_at = now
        if free_plan:
            sub.plan = free_plan
        sub.save()
        invalidate_plan_cache(str(sub.organization_id))
        canceled += 1
        logger.info('Canceled stale subscription for org %s', sub.organization.name)

    logger.info(
        'Recurring billing complete: %d charged, %d failed, %d canceled',
        charged, failed, canceled,
    )


@shared_task
def refresh_exchange_rates():
    """Pre-cache exchange rates from frankfurter.dev every 6 hours."""
    from .currency import get_exchange_rates, CACHE_KEY
    from django.core.cache import cache

    # Clear cache to force fresh fetch
    cache.delete(CACHE_KEY)
    rates = get_exchange_rates()
    if rates and len(rates) > 1:
        logger.info('Exchange rates refreshed: %d currencies', len(rates))
    else:
        logger.warning('Exchange rate refresh returned minimal data')


@shared_task
def record_daily_usage():
    """
    Record daily usage metrics per organization.
    Intended to run once daily via Celery Beat.
    """
    from users.models import Organization
    from meetings.models import Meeting, MeetingRecording
    from .models import UsageRecord

    today = timezone.now().date()
    yesterday = today - timedelta(days=1)
    created_count = 0

    # Only process organizations that had activity yesterday
    from django.db.models import Q
    active_org_ids = set(
        Meeting.objects.filter(created_at__date=yesterday).values_list('organization_id', flat=True)
    ) | set(
        MeetingRecording.objects.filter(created_at__date=yesterday).values_list('organization_id', flat=True)
    )

    for org_id in active_org_ids:
        org = Organization.objects.filter(id=org_id).first()
        if not org:
            continue

        meeting_count = Meeting.objects.filter(
            organization=org,
            created_at__date=yesterday,
        ).count()
        if meeting_count:
            UsageRecord.objects.update_or_create(
                organization=org,
                metric='meeting_minutes',
                recorded_at=yesterday,
                defaults={'value': meeting_count},
            )
            created_count += 1

        recording_count = MeetingRecording.objects.filter(
            organization=org,
            created_at__date=yesterday,
        ).count()
        if recording_count:
            UsageRecord.objects.update_or_create(
                organization=org,
                metric='recordings',
                recorded_at=yesterday,
                defaults={'value': recording_count},
            )
            created_count += 1

        total_storage = MeetingRecording.objects.filter(
            organization=org,
        ).aggregate(total=Sum('file_size'))['total'] or 0
        if total_storage:
            UsageRecord.objects.update_or_create(
                organization=org,
                metric='storage_bytes',
                recorded_at=today,
                defaults={'value': total_storage},
            )
            created_count += 1

    logger.info('Recorded %d daily usage entries for %d active orgs', created_count, len(active_org_ids))
