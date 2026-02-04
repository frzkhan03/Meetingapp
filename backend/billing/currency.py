import logging
import requests
from django.core.cache import cache

logger = logging.getLogger(__name__)

SUPPORTED_CURRENCIES = {
    'USD': ('$', 'US Dollar'),
    'INR': ('\u20b9', 'Indian Rupee'),
    'EUR': ('\u20ac', 'Euro'),
    'GBP': ('\u00a3', 'British Pound'),
    'SGD': ('S$', 'Singapore Dollar'),
    'MYR': ('RM', 'Malaysian Ringgit'),
    'AED': ('\u062f.\u0625', 'UAE Dirham'),
    'JPY': ('\u00a5', 'Japanese Yen'),
}

CACHE_KEY = 'billing:fx_rates'
CACHE_TTL = 6 * 60 * 60  # 6 hours
FRANKFURTER_URL = 'https://api.frankfurter.dev/v1/latest'


def get_exchange_rates():
    """Fetch USD-based exchange rates, cached in Redis/Django cache for 6 hours."""
    rates = cache.get(CACHE_KEY)
    if rates is not None:
        return rates

    target_codes = [c for c in SUPPORTED_CURRENCIES if c != 'USD']
    try:
        resp = requests.get(
            FRANKFURTER_URL,
            params={'base': 'USD', 'symbols': ','.join(target_codes)},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        rates = data.get('rates', {})
        rates['USD'] = 1.0
        cache.set(CACHE_KEY, rates, CACHE_TTL)
        return rates
    except Exception:
        logger.exception('Failed to fetch exchange rates from frankfurter.dev')
        # Return fallback rates so the site doesn't break
        return {'USD': 1.0}


def convert_price(amount_cents_usd, target_currency):
    """Convert a USD cent amount to the target currency. Returns cents (or smallest unit)."""
    if target_currency == 'USD':
        return amount_cents_usd

    rates = get_exchange_rates()
    rate = rates.get(target_currency)
    if rate is None:
        return amount_cents_usd  # Fallback to USD if rate unavailable

    converted = amount_cents_usd * rate
    # JPY has no fractional unit — round to whole number
    if target_currency == 'JPY':
        return round(converted)
    return round(converted)


def format_currency(amount_cents, currency_code):
    """Format a cent amount with the currency symbol. Returns string like '$8.99' or '\u00a5899'."""
    symbol, _ = SUPPORTED_CURRENCIES.get(currency_code, ('', currency_code))
    if currency_code == 'JPY':
        # JPY has no fractional unit
        return f'{symbol}{amount_cents:,}'
    amount = amount_cents / 100
    return f'{symbol}{amount:,.2f}'
