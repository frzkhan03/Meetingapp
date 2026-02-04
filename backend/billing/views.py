from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.conf import settings
from django.http import JsonResponse

from .models import Plan, Subscription, Payment
from .currency import SUPPORTED_CURRENCIES, get_exchange_rates, convert_price, format_currency


def pricing_view(request):
    """Public pricing page. No login required."""
    plans = Plan.objects.filter(is_active=True).order_by('display_order')

    current_tier = 'free'
    if request.user.is_authenticated and hasattr(request, 'plan_tier'):
        current_tier = request.plan_tier

    currency = request.COOKIES.get('preferred_currency', 'USD')
    if currency not in SUPPORTED_CURRENCIES:
        currency = 'USD'

    return render(request, 'billing/pricing.html', {
        'plans': plans,
        'current_tier': current_tier,
        'payu_enabled': settings.PAYU_ENABLED,
        'supported_currencies': SUPPORTED_CURRENCIES,
        'selected_currency': currency,
    })


@login_required
def create_checkout_view(request, plan_tier, billing_cycle):
    """Initiate PayU checkout for a plan. Owner-only."""
    if not settings.PAYU_ENABLED:
        messages.info(request, 'Billing is not configured in this environment.')
        return redirect('pricing')

    org = getattr(request, 'organization', None)
    if not org:
        messages.error(request, 'Please select an organization first.')
        return redirect('pricing')

    membership = org.memberships.filter(user=request.user, is_active=True).first()
    if not membership or membership.role != 'owner':
        messages.error(request, 'Only the organization owner can manage billing.')
        return redirect('billing_manage')

    if billing_cycle not in ('monthly', 'annual'):
        messages.error(request, 'Invalid billing cycle.')
        return redirect('pricing')

    plan = get_object_or_404(Plan, tier=plan_tier, is_active=True)

    if plan.tier == 'free':
        messages.info(request, 'You are already on the Free plan.')
        return redirect('pricing')

    # Ensure subscription exists
    try:
        sub = org.subscription
    except Subscription.DoesNotExist:
        free_plan = Plan.objects.get(tier='free')
        sub = Subscription.objects.create(
            organization=org, plan=free_plan, status='active'
        )

    currency = request.COOKIES.get('preferred_currency', 'USD')
    if currency not in SUPPORTED_CURRENCIES:
        currency = 'USD'

    success_url = request.build_absolute_uri('/billing/checkout/success/')
    notify_url = request.build_absolute_uri('/billing/webhooks/payu/')

    try:
        from .services import create_payu_order
        result = create_payu_order(
            organization=org,
            plan=plan,
            billing_cycle=billing_cycle,
            currency=currency,
            success_url=success_url,
            notify_url=notify_url,
        )
        redirect_url = result.get('redirect_url', '')
        if redirect_url:
            return redirect(redirect_url)
        messages.error(request, 'Unable to start checkout. Please try again.')
        return redirect('pricing')
    except Exception as e:
        messages.error(request, f'Unable to start checkout: {str(e)}')
        return redirect('pricing')


@login_required
def checkout_success_view(request):
    """Post-checkout success page."""
    return render(request, 'billing/checkout_success.html', {
        'organization': getattr(request, 'organization', None),
    })


@login_required
def checkout_cancel_view(request):
    """Post-checkout cancellation page."""
    return render(request, 'billing/checkout_cancel.html', {
        'organization': getattr(request, 'organization', None),
    })


@login_required
def billing_manage_view(request):
    """Billing management dashboard for org owners."""
    org = getattr(request, 'organization', None)
    if not org:
        messages.info(request, 'Please select an organization first.')
        return redirect('organization_list')

    membership = org.memberships.filter(user=request.user, is_active=True).first()
    is_owner = membership and membership.role == 'owner'

    try:
        subscription = org.subscription
    except Subscription.DoesNotExist:
        subscription = None

    payments = []
    if subscription:
        payments = subscription.payments.order_by('-created_at')[:20]

    plans = Plan.objects.filter(is_active=True).order_by('display_order')

    from meetings.models import PersonalRoom
    room_count = PersonalRoom.objects.filter(organization=org, is_active=True).count()

    plan_limits = getattr(request, 'plan_limits', None)

    return render(request, 'billing/manage.html', {
        'organization': org,
        'subscription': subscription,
        'payments': payments,
        'plans': plans,
        'is_owner': is_owner,
        'room_count': room_count,
        'plan_limits': plan_limits,
        'payu_enabled': settings.PAYU_ENABLED,
    })


@login_required
def cancel_subscription_view(request):
    """Cancel subscription at period end. POST only."""
    if request.method != 'POST':
        return redirect('billing_manage')

    org = getattr(request, 'organization', None)
    if not org:
        return redirect('billing_manage')

    membership = org.memberships.filter(user=request.user, is_active=True).first()
    if not membership or membership.role != 'owner':
        messages.error(request, 'Only the organization owner can cancel the subscription.')
        return redirect('billing_manage')

    try:
        from .services import cancel_subscription
        cancel_subscription(org)
        messages.success(
            request,
            'Your subscription will be canceled at the end of the current billing period.'
        )
    except Exception as e:
        messages.error(request, f'Unable to cancel: {str(e)}')

    return redirect('billing_manage')


@login_required
def resume_subscription_view(request):
    """Resume a subscription set to cancel. POST only."""
    if request.method != 'POST':
        return redirect('billing_manage')

    org = getattr(request, 'organization', None)
    if not org:
        return redirect('billing_manage')

    membership = org.memberships.filter(user=request.user, is_active=True).first()
    if not membership or membership.role != 'owner':
        messages.error(request, 'Only the organization owner can resume the subscription.')
        return redirect('billing_manage')

    try:
        from .services import resume_subscription
        resume_subscription(org)
        messages.success(request, 'Your subscription has been resumed.')
    except Exception as e:
        messages.error(request, f'Unable to resume: {str(e)}')

    return redirect('billing_manage')


def currency_rates_api(request):
    """AJAX endpoint returning converted prices for all plans in the requested currency."""
    currency = request.GET.get('currency', 'USD')
    if currency not in SUPPORTED_CURRENCIES:
        return JsonResponse({'error': 'Unsupported currency'}, status=400)

    plans = Plan.objects.filter(is_active=True).order_by('display_order')
    symbol, name = SUPPORTED_CURRENCIES[currency]

    plan_prices = {}
    for plan in plans:
        monthly_converted = convert_price(plan.monthly_price_cents, currency)
        annual_converted = convert_price(plan.annual_price_cents, currency)
        plan_prices[plan.tier] = {
            'monthly': format_currency(monthly_converted, currency),
            'annual': format_currency(annual_converted, currency),
            'monthly_raw': monthly_converted,
            'annual_raw': annual_converted,
        }

    return JsonResponse({
        'currency': currency,
        'symbol': symbol,
        'name': name,
        'plans': plan_prices,
    })
