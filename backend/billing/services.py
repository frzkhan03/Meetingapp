import hashlib
import logging

import requests
from django.conf import settings
from django.core.cache import cache

from .currency import convert_price

logger = logging.getLogger(__name__)

PAYU_TOKEN_CACHE_KEY = 'billing:payu_access_token'


def get_payu_access_token():
    """Obtain an OAuth 2.0 access token from PayU, cached for ~1 hour."""
    token = cache.get(PAYU_TOKEN_CACHE_KEY)
    if token:
        return token

    url = f'{settings.PAYU_BASE_URL}/pl/standard/user/oauth/authorize'
    resp = requests.post(url, data={
        'grant_type': 'client_credentials',
        'client_id': settings.PAYU_POS_ID,
        'client_secret': settings.PAYU_CLIENT_SECRET,
    }, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    token = data['access_token']
    expires_in = data.get('expires_in', 3600)
    cache.set(PAYU_TOKEN_CACHE_KEY, token, max(expires_in - 60, 60))
    return token


def create_payu_order(organization, plan, billing_cycle, currency, success_url, notify_url):
    """
    Create a PayU order (first recurring payment).
    Returns the redirect URL where the user completes payment.
    """
    token = get_payu_access_token()

    price_cents_usd = (
        plan.monthly_price_cents if billing_cycle == 'monthly'
        else plan.annual_price_cents
    )

    if plan.is_per_user:
        quantity = max(
            organization.memberships.filter(is_active=True).count(), 1
        )
    else:
        quantity = 1

    total_usd_cents = price_cents_usd * quantity
    total_local = convert_price(total_usd_cents, currency)

    # PayU expects amount as string in smallest currency unit
    description = f'{plan.name} plan ({billing_cycle}) for {organization.name}'

    # Get buyer email
    owner = organization.memberships.filter(
        role='owner', is_active=True
    ).select_related('user').first()
    buyer_email = owner.user.email if owner else ''
    buyer_name = owner.user.get_full_name() or owner.user.username if owner else ''

    order_payload = {
        'notifyUrl': notify_url,
        'continueUrl': success_url,
        'customerIp': '127.0.0.1',
        'merchantPosId': settings.PAYU_POS_ID,
        'description': description,
        'currencyCode': currency,
        'totalAmount': str(total_local),
        'buyer': {
            'email': buyer_email,
            'firstName': buyer_name.split()[0] if buyer_name else '',
            'lastName': ' '.join(buyer_name.split()[1:]) if buyer_name and len(buyer_name.split()) > 1 else '',
            'language': 'en',
        },
        'products': [{
            'name': f'{plan.name} ({billing_cycle})',
            'unitPrice': str(convert_price(price_cents_usd, currency)),
            'quantity': str(quantity),
        }],
        'extOrderId': f'{organization.id}-{plan.tier}-{billing_cycle}',
        'payMethods': {
            'payMethod': {
                'type': 'PBL',
            }
        },
        'recurring': 'FIRST',
    }

    url = f'{settings.PAYU_BASE_URL}/api/v2_1/orders'
    resp = requests.post(
        url,
        json=order_payload,
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        },
        allow_redirects=False,
        timeout=30,
    )

    # PayU returns 302 with redirectUri on success, or 200 with JSON
    if resp.status_code in (200, 201, 302):
        data = resp.json()
        redirect_uri = data.get('redirectUri', '')
        order_id = data.get('orderId', '')
        return {
            'redirect_url': redirect_uri,
            'order_id': order_id,
            'status': data.get('status', {}).get('statusCode', ''),
        }

    logger.error('PayU order creation failed: %s %s', resp.status_code, resp.text)
    resp.raise_for_status()


def create_payu_recurring_order(subscription):
    """
    Server-initiated recurring charge using stored card token.
    No user interaction needed.
    """
    token = get_payu_access_token()
    plan = subscription.plan
    billing_cycle = subscription.billing_cycle
    org = subscription.organization
    currency = 'USD'  # Recurring charges use original currency if stored, default USD

    # Check for stored payment currency from last payment
    last_payment = subscription.payments.filter(status='succeeded').order_by('-created_at').first()
    if last_payment:
        currency = last_payment.currency.upper()

    price_cents_usd = (
        plan.monthly_price_cents if billing_cycle == 'monthly'
        else plan.annual_price_cents
    )

    quantity = subscription.quantity or 1
    total_usd_cents = price_cents_usd * quantity
    total_local = convert_price(total_usd_cents, currency)

    description = f'{plan.name} plan ({billing_cycle}) renewal for {org.name}'

    order_payload = {
        'notifyUrl': f'{settings.SITE_URL}/billing/webhooks/payu/',
        'customerIp': '127.0.0.1',
        'merchantPosId': settings.PAYU_POS_ID,
        'description': description,
        'currencyCode': currency,
        'totalAmount': str(total_local),
        'extOrderId': f'{org.id}-{plan.tier}-{billing_cycle}-recurring',
        'products': [{
            'name': f'{plan.name} ({billing_cycle})',
            'unitPrice': str(convert_price(price_cents_usd, currency)),
            'quantity': str(quantity),
        }],
        'recurring': 'STANDARD',
        'payMethods': {
            'payMethod': {
                'value': subscription.payu_card_token,
                'type': 'CARD_TOKEN',
            }
        },
    }

    url = f'{settings.PAYU_BASE_URL}/api/v2_1/orders'
    resp = requests.post(
        url,
        json=order_payload,
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        },
        allow_redirects=False,
        timeout=30,
    )

    if resp.status_code in (200, 201, 302):
        data = resp.json()
        return {
            'order_id': data.get('orderId', ''),
            'status': data.get('status', {}).get('statusCode', ''),
        }

    logger.error('PayU recurring order failed for org %s: %s %s', org.id, resp.status_code, resp.text)
    return None


def verify_payu_signature(body_bytes, signature_header, second_key=None):
    """
    Verify PayU webhook signature.
    Header format: sender=checkout;signature=<md5>;algorithm=MD5;content=DOCUMENT
    """
    if not signature_header:
        return False

    second_key = second_key or settings.PAYU_SECOND_KEY

    parts = {}
    for part in signature_header.split(';'):
        if '=' in part:
            k, v = part.split('=', 1)
            parts[k] = v

    expected_sig = parts.get('signature', '')
    algorithm = parts.get('algorithm', 'MD5')

    if algorithm != 'MD5':
        logger.warning('Unsupported PayU signature algorithm: %s', algorithm)
        return False

    # MD5 of body + second_key
    concat = body_bytes + second_key.encode('utf-8')
    computed = hashlib.md5(concat).hexdigest()

    return computed == expected_sig


def cancel_subscription(organization):
    """Cancel subscription at period end (local-only, no PayU API needed)."""
    from .plan_limits import invalidate_plan_cache

    try:
        sub = organization.subscription
        sub.cancel_at_period_end = True
        sub.save(update_fields=['cancel_at_period_end', 'updated_at'])
        invalidate_plan_cache(str(organization.id))
    except Exception as e:
        logger.exception('Error canceling subscription for %s: %s', organization.name, e)
        raise


def resume_subscription(organization):
    """Resume a subscription that was set to cancel at period end (local-only)."""
    from .plan_limits import invalidate_plan_cache

    try:
        sub = organization.subscription
        sub.cancel_at_period_end = False
        sub.save(update_fields=['cancel_at_period_end', 'updated_at'])
        invalidate_plan_cache(str(organization.id))
    except Exception as e:
        logger.exception('Error resuming subscription for %s: %s', organization.name, e)
        raise
