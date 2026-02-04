from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.conf import settings

from .models import Plan, Subscription, Payment


def pricing_view(request):
    """Public pricing page. No login required."""
    plans = Plan.objects.filter(is_active=True).order_by('display_order')

    current_tier = 'free'
    if request.user.is_authenticated and hasattr(request, 'plan_tier'):
        current_tier = request.plan_tier

    return render(request, 'billing/pricing.html', {
        'plans': plans,
        'current_tier': current_tier,
        'stripe_enabled': settings.STRIPE_ENABLED,
        'stripe_publishable_key': settings.STRIPE_PUBLISHABLE_KEY,
    })


@login_required
def create_checkout_view(request, plan_tier, billing_cycle):
    """Initiate Stripe Checkout for a plan. Owner-only."""
    if not settings.STRIPE_ENABLED:
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

    success_url = request.build_absolute_uri('/billing/checkout/success/') + '?session_id={CHECKOUT_SESSION_ID}'
    cancel_url = request.build_absolute_uri('/billing/checkout/cancel/')

    try:
        from .services import create_checkout_session
        session = create_checkout_session(
            organization=org,
            plan=plan,
            billing_cycle=billing_cycle,
            success_url=success_url,
            cancel_url=cancel_url,
        )
        return redirect(session.url)
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
        'stripe_enabled': settings.STRIPE_ENABLED,
    })


@login_required
def customer_portal_view(request):
    """Redirect to Stripe Customer Portal for payment method management."""
    if not settings.STRIPE_ENABLED:
        messages.info(request, 'Billing is not configured.')
        return redirect('billing_manage')

    org = getattr(request, 'organization', None)
    if not org:
        return redirect('billing_manage')

    membership = org.memberships.filter(user=request.user, is_active=True).first()
    if not membership or membership.role != 'owner':
        messages.error(request, 'Only the organization owner can manage billing.')
        return redirect('billing_manage')

    return_url = request.build_absolute_uri('/billing/manage/')

    try:
        from .services import create_customer_portal_session
        session = create_customer_portal_session(org, return_url)
        return redirect(session.url)
    except Exception as e:
        messages.error(request, f'Unable to open billing portal: {str(e)}')
        return redirect('billing_manage')


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
