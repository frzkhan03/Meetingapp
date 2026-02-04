import logging
from celery import shared_task
from django.db.models import Sum
from django.utils import timezone
from datetime import timedelta

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def sync_subscription_from_stripe_task(self, stripe_subscription_data):
    """
    Async wrapper for sync_subscription_from_stripe.
    Called by webhook handlers that want to offload the sync.
    """
    try:
        from .services import sync_subscription_from_stripe
        result = sync_subscription_from_stripe(stripe_subscription_data)
        if result:
            logger.info(f"Synced subscription for org {result.organization.name}")
        return bool(result)
    except Exception as e:
        logger.exception(f"Error syncing subscription from Stripe: {e}")
        raise self.retry(exc=e)


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
    orgs = Organization.objects.all()
    created_count = 0

    for org in orgs.iterator():
        org_id = org.id

        # Meeting count for yesterday
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

        # Recording count for yesterday
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

        # Current total storage
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

    logger.info(f"Recorded {created_count} daily usage entries")


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def update_business_plan_quantities(self):
    """
    Sync active member count to Stripe seat quantity for Business plan subscriptions.
    Intended to run periodically (e.g., hourly) via Celery Beat.
    """
    from django.conf import settings
    from .models import Subscription

    if not getattr(settings, 'STRIPE_ENABLED', False):
        return

    try:
        import stripe
        stripe.api_key = settings.STRIPE_SECRET_KEY

        business_subs = Subscription.objects.filter(
            plan__tier='business',
            status__in=['active', 'trialing', 'past_due'],
            stripe_subscription_id__gt='',
        ).select_related('organization', 'plan')

        updated = 0
        for sub in business_subs:
            active_members = sub.organization.memberships.filter(
                is_active=True
            ).count()
            new_quantity = max(active_members, 1)

            if new_quantity != sub.quantity:
                # Update Stripe
                stripe_sub = stripe.Subscription.retrieve(
                    sub.stripe_subscription_id
                )
                if stripe_sub['items']['data']:
                    stripe.SubscriptionItem.modify(
                        stripe_sub['items']['data'][0]['id'],
                        quantity=new_quantity,
                    )

                sub.quantity = new_quantity
                sub.save(update_fields=['quantity', 'updated_at'])
                updated += 1
                logger.info(
                    f"Updated seat quantity for {sub.organization.name}: "
                    f"{sub.quantity} -> {new_quantity}"
                )

        logger.info(f"Business plan quantity sync complete: {updated} updated")

    except Exception as e:
        logger.exception(f"Error updating business plan quantities: {e}")
        raise self.retry(exc=e)
