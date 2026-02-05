import json
import logging
from datetime import timedelta

from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .services import verify_payu_signature

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def payu_webhook_view(request):
    """Handle PayU order notification webhooks."""
    if not settings.PAYU_ENABLED:
        return HttpResponse(status=200)

    body = request.body
    sig_header = request.META.get('HTTP_OPENPAYU_SIGNATURE', '')

    if not verify_payu_signature(body, sig_header):
        logger.warning('PayU webhook signature verification failed')
        return HttpResponse(status=400)

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        logger.warning('PayU webhook: invalid JSON body')
        return HttpResponse(status=400)

    order = data.get('order', {})
    order_id = order.get('orderId', '')
    status_code = order.get('status', '')
    ext_order_id = order.get('extOrderId', '')

    logger.info('PayU webhook: order=%s status=%s ext=%s', order_id, status_code, ext_order_id)

    try:
        if status_code == 'COMPLETED':
            handle_order_completed(order, data)
        elif status_code == 'WAITING_FOR_CONFIRMATION':
            from .services import capture_payu_order
            logger.info('PayU order %s waiting for confirmation, auto-capturing', order_id)
            capture_payu_order(order_id)
        elif status_code in ('CANCELED', 'REJECTED'):
            handle_order_failed(order)
        elif status_code == 'PENDING':
            logger.info('PayU order %s is pending', order_id)
        else:
            logger.debug('Unhandled PayU order status: %s', status_code)
    except Exception:
        logger.exception('Error handling PayU webhook for order %s', order_id)
        return HttpResponse(status=500)

    return HttpResponse(status=200)


def handle_order_completed(order, full_data):
    """Payment succeeded — update subscription and create Payment record."""
    from .models import Payment, Plan, Subscription
    from .plan_limits import invalidate_plan_cache

    ext_order_id = order.get('extOrderId', '')
    order_id = order.get('orderId', '')

    # Parse extOrderId: {org_id}-{tier}-{cycle}[-recurring]
    parts = ext_order_id.split('-')
    if len(parts) < 3:
        logger.warning('Cannot parse extOrderId: %s', ext_order_id)
        return

    # UUID is first 5 parts (8-4-4-4-12), then tier, then cycle
    # Format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx-pro-monthly[-recurring]
    # UUID has 5 parts separated by dashes, so org_id is parts[0:5]
    org_id = '-'.join(parts[:5])
    tier = parts[5] if len(parts) > 5 else ''
    billing_cycle = parts[6] if len(parts) > 6 else 'monthly'
    is_recurring = len(parts) > 7 and parts[7] == 'recurring'

    try:
        sub = Subscription.objects.select_related('plan', 'organization').get(
            organization_id=org_id
        )
    except Subscription.DoesNotExist:
        logger.warning('No subscription found for org %s', org_id)
        return

    plan = Plan.objects.filter(tier=tier, is_active=True).first()
    if not plan:
        logger.warning('Plan not found for tier: %s', tier)
        return

    # Extract card token from first recurring payment
    properties = full_data.get('properties', [])
    for prop in properties:
        if prop.get('name') == 'PAYMENT_ID':
            pass  # useful for logging
    # PayU returns payMethod with card token in the order
    pay_method = order.get('payMethod', {})
    card_token = pay_method.get('value', '')

    # Extract transaction ID from properties
    payu_transaction_id = ''
    if isinstance(properties, list):
        for prop in properties:
            if prop.get('name') == 'PAYMENT_ID':
                payu_transaction_id = str(prop.get('value', ''))

    # Update subscription
    now = timezone.now()
    if billing_cycle == 'annual':
        next_billing = now + timedelta(days=365)
    else:
        next_billing = now + timedelta(days=30)

    sub.plan = plan
    sub.status = 'active'
    sub.billing_cycle = billing_cycle.replace('-recurring', '')
    sub.current_period_start = now
    sub.current_period_end = next_billing
    sub.next_billing_date = next_billing
    sub.cancel_at_period_end = False
    sub.canceled_at = None

    if card_token and card_token.startswith('TOKC_'):
        sub.payu_card_token = card_token

    # Set customer ID from buyer
    buyer = order.get('buyer', {})
    if buyer.get('customerId'):
        sub.payu_customer_id = buyer['customerId']

    sub.save()
    invalidate_plan_cache(org_id)

    # Create Payment record
    amount = int(order.get('totalAmount', 0))
    currency = order.get('currencyCode', 'USD')

    Payment.objects.create(
        subscription=sub,
        payu_order_id=order_id,
        payu_transaction_id=payu_transaction_id,
        amount_cents=amount,
        currency=currency.lower(),
        status='succeeded',
        description=order.get('description', ''),
    )

    logger.info(
        'Payment completed: org=%s plan=%s cycle=%s amount=%s %s recurring=%s',
        org_id, tier, billing_cycle, amount, currency, is_recurring,
    )


def handle_order_failed(order):
    """Payment failed or canceled — record and update subscription if recurring."""
    from .models import Payment, Subscription

    ext_order_id = order.get('extOrderId', '')
    order_id = order.get('orderId', '')
    status = order.get('status', '')

    parts = ext_order_id.split('-')
    if len(parts) < 3:
        return

    org_id = '-'.join(parts[:5])
    is_recurring = 'recurring' in ext_order_id

    try:
        sub = Subscription.objects.get(organization_id=org_id)
    except Subscription.DoesNotExist:
        return

    # Record failed payment
    Payment.objects.create(
        subscription=sub,
        payu_order_id=order_id,
        amount_cents=int(order.get('totalAmount', 0)),
        currency=order.get('currencyCode', 'USD').lower(),
        status='failed',
        description=f'{status}: {order.get("description", "")}',
    )

    # If this was a recurring charge, mark subscription as past_due
    if is_recurring and sub.status == 'active':
        sub.status = 'past_due'
        sub.save(update_fields=['status', 'updated_at'])

    logger.warning('Payment failed: org=%s order=%s status=%s', org_id, order_id, status)
