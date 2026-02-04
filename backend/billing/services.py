import logging
from datetime import datetime, timezone as tz

import stripe
from django.conf import settings

logger = logging.getLogger(__name__)


def get_stripe():
    """Initialize and return stripe module with API key set."""
    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe


def get_or_create_stripe_customer(organization):
    """Get or create a Stripe Customer for the organization."""
    from .models import Subscription

    try:
        sub = organization.subscription
        if sub.stripe_customer_id:
            return sub.stripe_customer_id
    except Subscription.DoesNotExist:
        sub = None

    # Get owner email
    owner_membership = organization.memberships.filter(
        role='owner', is_active=True
    ).select_related('user').first()
    email = owner_membership.user.email if owner_membership else ''

    s = get_stripe()
    customer = s.Customer.create(
        email=email,
        name=organization.name,
        metadata={
            'organization_id': str(organization.id),
            'organization_slug': organization.slug,
        }
    )

    # Store customer ID
    if sub:
        sub.stripe_customer_id = customer.id
        sub.save(update_fields=['stripe_customer_id', 'updated_at'])
    else:
        from .models import Plan
        free_plan = Plan.objects.get(tier='free')
        sub = Subscription.objects.create(
            organization=organization,
            plan=free_plan,
            status='active',
            stripe_customer_id=customer.id,
        )

    return customer.id


def create_checkout_session(organization, plan, billing_cycle, success_url, cancel_url):
    """Create a Stripe Checkout Session for subscribing to a plan."""
    s = get_stripe()
    customer_id = get_or_create_stripe_customer(organization)

    price_id = (
        plan.stripe_monthly_price_id if billing_cycle == 'monthly'
        else plan.stripe_annual_price_id
    )

    if not price_id:
        raise ValueError(f'No Stripe price configured for {plan.name} ({billing_cycle})')

    quantity = 1
    if plan.is_per_user:
        quantity = max(
            organization.memberships.filter(is_active=True).count(),
            1
        )

    session = s.checkout.Session.create(
        customer=customer_id,
        mode='subscription',
        line_items=[{'price': price_id, 'quantity': quantity}],
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={
            'organization_id': str(organization.id),
            'plan_tier': plan.tier,
            'billing_cycle': billing_cycle,
        },
        subscription_data={
            'metadata': {
                'organization_id': str(organization.id),
                'plan_tier': plan.tier,
            },
        },
        allow_promotion_codes=True,
    )

    return session


def create_customer_portal_session(organization, return_url):
    """Create a Stripe Customer Portal session for self-service management."""
    s = get_stripe()
    customer_id = get_or_create_stripe_customer(organization)

    session = s.billing_portal.Session.create(
        customer=customer_id,
        return_url=return_url,
    )

    return session


def sync_subscription_from_stripe(stripe_subscription):
    """
    Create or update local Subscription from a Stripe subscription object.
    Idempotent - safe to call multiple times.
    """
    from .models import Plan, Subscription
    from .plan_limits import invalidate_plan_cache
    from users.models import Organization

    org_id = stripe_subscription.get('metadata', {}).get('organization_id')
    if not org_id:
        # Try to find org via customer
        customer_id = stripe_subscription.get('customer')
        try:
            sub = Subscription.objects.get(stripe_customer_id=customer_id)
            org_id = str(sub.organization_id)
        except Subscription.DoesNotExist:
            logger.warning(f"Cannot find org for Stripe subscription {stripe_subscription.get('id')}")
            return None

    try:
        org = Organization.objects.get(id=org_id)
    except Organization.DoesNotExist:
        logger.warning(f"Organization {org_id} not found for Stripe subscription")
        return None

    # Determine plan from price ID
    items = stripe_subscription.get('items', {}).get('data', [])
    price_id = items[0]['price']['id'] if items else ''
    interval = items[0]['price'].get('recurring', {}).get('interval', 'month') if items else 'month'

    plan = None
    if price_id:
        plan = Plan.objects.filter(stripe_monthly_price_id=price_id).first()
        if not plan:
            plan = Plan.objects.filter(stripe_annual_price_id=price_id).first()

    # Fallback: try metadata
    if not plan:
        plan_tier = stripe_subscription.get('metadata', {}).get('plan_tier')
        if plan_tier:
            plan = Plan.objects.filter(tier=plan_tier).first()

    if not plan:
        logger.warning(f"Cannot determine plan for price {price_id}")
        return None

    billing_cycle = 'annual' if interval == 'year' else 'monthly'
    quantity = items[0].get('quantity', 1) if items else 1

    # Convert timestamps
    period_start = None
    period_end = None
    canceled_at = None

    if stripe_subscription.get('current_period_start'):
        period_start = datetime.fromtimestamp(
            stripe_subscription['current_period_start'], tz=tz.utc
        )
    if stripe_subscription.get('current_period_end'):
        period_end = datetime.fromtimestamp(
            stripe_subscription['current_period_end'], tz=tz.utc
        )
    if stripe_subscription.get('canceled_at'):
        canceled_at = datetime.fromtimestamp(
            stripe_subscription['canceled_at'], tz=tz.utc
        )

    sub, created = Subscription.objects.update_or_create(
        organization=org,
        defaults={
            'plan': plan,
            'status': stripe_subscription.get('status', 'active'),
            'billing_cycle': billing_cycle,
            'stripe_customer_id': stripe_subscription.get('customer', ''),
            'stripe_subscription_id': stripe_subscription.get('id', ''),
            'current_period_start': period_start,
            'current_period_end': period_end,
            'cancel_at_period_end': stripe_subscription.get('cancel_at_period_end', False),
            'canceled_at': canceled_at,
            'quantity': quantity,
        }
    )

    invalidate_plan_cache(org_id)
    return sub


def cancel_subscription(organization):
    """Cancel subscription at period end via Stripe API."""
    s = get_stripe()
    try:
        sub = organization.subscription
        if sub.stripe_subscription_id:
            s.Subscription.modify(
                sub.stripe_subscription_id,
                cancel_at_period_end=True,
            )
            sub.cancel_at_period_end = True
            sub.save(update_fields=['cancel_at_period_end', 'updated_at'])
    except Exception as e:
        logger.exception(f"Error canceling subscription for {organization.name}: {e}")
        raise


def resume_subscription(organization):
    """Resume a subscription that was set to cancel at period end."""
    s = get_stripe()
    try:
        sub = organization.subscription
        if sub.stripe_subscription_id:
            s.Subscription.modify(
                sub.stripe_subscription_id,
                cancel_at_period_end=False,
            )
            sub.cancel_at_period_end = False
            sub.save(update_fields=['cancel_at_period_end', 'updated_at'])
    except Exception as e:
        logger.exception(f"Error resuming subscription for {organization.name}: {e}")
        raise
