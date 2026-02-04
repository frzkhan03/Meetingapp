import logging

import stripe
from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def stripe_webhook_view(request):
    """Handle Stripe webhook events."""
    if not settings.STRIPE_ENABLED:
        return HttpResponse(status=200)

    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')

    try:
        stripe.api_key = settings.STRIPE_SECRET_KEY
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except (ValueError, stripe.error.SignatureVerificationError) as e:
        logger.warning(f"Stripe webhook signature verification failed: {e}")
        return HttpResponse(status=400)

    handlers = {
        'checkout.session.completed': handle_checkout_completed,
        'customer.subscription.created': handle_subscription_changed,
        'customer.subscription.updated': handle_subscription_changed,
        'customer.subscription.deleted': handle_subscription_deleted,
        'invoice.paid': handle_invoice_paid,
        'invoice.payment_failed': handle_invoice_payment_failed,
    }

    handler = handlers.get(event['type'])
    if handler:
        try:
            handler(event['data']['object'])
        except Exception as e:
            logger.exception(f"Error handling webhook {event['type']}: {e}")
            return HttpResponse(status=500)
    else:
        logger.debug(f"Unhandled Stripe event type: {event['type']}")

    return HttpResponse(status=200)


def handle_checkout_completed(session):
    """Checkout session completed - retrieve and sync the subscription."""
    from .services import get_stripe, sync_subscription_from_stripe

    subscription_id = session.get('subscription')
    if not subscription_id:
        return

    s = get_stripe()
    subscription = s.Subscription.retrieve(subscription_id)
    sync_subscription_from_stripe(subscription)

    logger.info(f"Checkout completed for subscription {subscription_id}")


def handle_subscription_changed(subscription):
    """Subscription created or updated."""
    from .services import sync_subscription_from_stripe
    sync_subscription_from_stripe(subscription)
    logger.info(f"Subscription {subscription.get('id')} synced (status: {subscription.get('status')})")


def handle_subscription_deleted(subscription):
    """Subscription canceled or expired - downgrade to free."""
    from .models import Plan, Subscription as SubModel
    from .plan_limits import invalidate_plan_cache

    org_id = subscription.get('metadata', {}).get('organization_id')
    customer_id = subscription.get('customer')

    sub = None
    if org_id:
        try:
            sub = SubModel.objects.get(organization_id=org_id)
        except SubModel.DoesNotExist:
            pass

    if not sub and customer_id:
        try:
            sub = SubModel.objects.get(stripe_customer_id=customer_id)
        except SubModel.DoesNotExist:
            pass

    if sub:
        free_plan = Plan.objects.filter(tier='free').first()
        if free_plan:
            sub.plan = free_plan
        sub.status = 'canceled'
        sub.canceled_at = None  # Will be set by Stripe timestamp if available
        sub.stripe_subscription_id = ''
        sub.save()
        invalidate_plan_cache(str(sub.organization_id))
        logger.info(f"Subscription deleted for org {sub.organization.name}, downgraded to free")


def handle_invoice_paid(invoice):
    """Successful payment - create Payment record."""
    from .models import Payment, Subscription as SubModel

    subscription_id = invoice.get('subscription')
    if not subscription_id:
        return

    try:
        sub = SubModel.objects.get(stripe_subscription_id=subscription_id)
    except SubModel.DoesNotExist:
        # Try customer lookup
        customer_id = invoice.get('customer')
        try:
            sub = SubModel.objects.get(stripe_customer_id=customer_id)
        except SubModel.DoesNotExist:
            logger.warning(f"No subscription found for invoice {invoice.get('id')}")
            return

    Payment.objects.update_or_create(
        stripe_invoice_id=invoice.get('id', ''),
        defaults={
            'subscription': sub,
            'amount_cents': invoice.get('amount_paid', 0),
            'currency': invoice.get('currency', 'usd'),
            'status': 'succeeded',
            'description': invoice.get('description', '') or f"Invoice {invoice.get('number', '')}",
            'stripe_charge_id': invoice.get('charge', '') or '',
            'stripe_payment_intent_id': invoice.get('payment_intent', '') or '',
            'invoice_pdf_url': invoice.get('invoice_pdf', '') or '',
        }
    )

    logger.info(f"Payment recorded for invoice {invoice.get('id')}")


def handle_invoice_payment_failed(invoice):
    """Failed payment - create Payment record."""
    from .models import Payment, Subscription as SubModel

    subscription_id = invoice.get('subscription')
    if not subscription_id:
        return

    try:
        sub = SubModel.objects.get(stripe_subscription_id=subscription_id)
    except SubModel.DoesNotExist:
        customer_id = invoice.get('customer')
        try:
            sub = SubModel.objects.get(stripe_customer_id=customer_id)
        except SubModel.DoesNotExist:
            return

    Payment.objects.update_or_create(
        stripe_invoice_id=invoice.get('id', ''),
        defaults={
            'subscription': sub,
            'amount_cents': invoice.get('amount_due', 0),
            'currency': invoice.get('currency', 'usd'),
            'status': 'failed',
            'description': f"Failed: {invoice.get('description', '') or invoice.get('number', '')}",
            'stripe_charge_id': invoice.get('charge', '') or '',
            'stripe_payment_intent_id': invoice.get('payment_intent', '') or '',
        }
    )

    logger.info(f"Failed payment recorded for invoice {invoice.get('id')}")
