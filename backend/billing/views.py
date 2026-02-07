import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.conf import settings
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST

from .models import Plan, Subscription, Payment, Invoice, BillingInfo, COUNTRIES, get_tax_label_for_country
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
        import logging
        logging.getLogger(__name__).exception('Checkout error for org %s', org.id)
        messages.error(request, 'Unable to start checkout. Please try again later.')
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

    # Get invoices
    invoices = Invoice.objects.filter(organization=org).order_by('-created_at')[:10]

    # Get billing info
    try:
        billing_info = org.billing_info
    except BillingInfo.DoesNotExist:
        billing_info = None

    return render(request, 'billing/manage.html', {
        'organization': org,
        'subscription': subscription,
        'payments': payments,
        'invoices': invoices,
        'billing_info': billing_info,
        'plans': plans,
        'is_owner': is_owner,
        'room_count': room_count,
        'plan_limits': plan_limits,
        'payu_enabled': settings.PAYU_ENABLED,
        'countries': COUNTRIES,
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
        import logging
        logging.getLogger(__name__).exception('Cancel subscription error for org %s', org.id)
        messages.error(request, 'Unable to cancel subscription. Please try again later.')

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
        import logging
        logging.getLogger(__name__).exception('Resume subscription error for org %s', org.id)
        messages.error(request, 'Unable to resume subscription. Please try again later.')

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


@login_required
def get_billing_info_view(request):
    """Get billing info for the current organization (AJAX)."""
    org = getattr(request, 'organization', None)
    if not org:
        return JsonResponse({'error': 'No organization selected'}, status=400)

    try:
        billing_info = org.billing_info
        data = {
            'billing_name': billing_info.billing_name,
            'address_line1': billing_info.address_line1,
            'address_line2': billing_info.address_line2,
            'city': billing_info.city,
            'state': billing_info.state,
            'postal_code': billing_info.postal_code,
            'country': billing_info.country,
            'tax_id': billing_info.tax_id,
            'tax_type': billing_info.tax_type,
            'billing_email': billing_info.billing_email,
        }
    except BillingInfo.DoesNotExist:
        data = {
            'billing_name': '',
            'address_line1': '',
            'address_line2': '',
            'city': '',
            'state': '',
            'postal_code': '',
            'country': '',
            'tax_id': '',
            'tax_type': '',
            'billing_email': '',
        }

    data['countries'] = COUNTRIES
    return JsonResponse(data)


@login_required
@require_POST
def save_billing_info_view(request):
    """Save billing info for the current organization (AJAX)."""
    org = getattr(request, 'organization', None)
    if not org:
        return JsonResponse({'error': 'No organization selected'}, status=400)

    # Check permissions
    membership = org.memberships.filter(user=request.user, is_active=True).first()
    if not membership or membership.role not in ['owner', 'admin']:
        return JsonResponse({'error': 'Permission denied'}, status=403)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    # Get or create billing info
    billing_info, created = BillingInfo.objects.get_or_create(
        organization=org,
        defaults={'billing_name': org.name}
    )

    # Update fields
    billing_info.billing_name = data.get('billing_name', '').strip()[:255]
    billing_info.address_line1 = data.get('address_line1', '').strip()[:255]
    billing_info.address_line2 = data.get('address_line2', '').strip()[:255]
    billing_info.city = data.get('city', '').strip()[:100]
    billing_info.state = data.get('state', '').strip()[:100]
    billing_info.postal_code = data.get('postal_code', '').strip()[:20]
    billing_info.country = data.get('country', '').strip()[:2].upper()
    billing_info.tax_id = data.get('tax_id', '').strip()[:50]
    billing_info.billing_email = data.get('billing_email', '').strip()[:254]

    # Auto-set tax type based on country
    if billing_info.country:
        from .models import get_tax_type_for_country
        billing_info.tax_type = get_tax_type_for_country(billing_info.country)

    billing_info.save()

    return JsonResponse({
        'success': True,
        'tax_label': get_tax_label_for_country(billing_info.country),
    })


@login_required
def get_tax_label_api(request):
    """Get the tax label for a country code (AJAX)."""
    country = request.GET.get('country', '').upper()
    return JsonResponse({
        'country': country,
        'tax_label': get_tax_label_for_country(country),
    })


@login_required
def invoice_list_view(request):
    """List invoices for the current organization."""
    org = getattr(request, 'organization', None)
    if not org:
        messages.info(request, 'Please select an organization first.')
        return redirect('organization_list')

    invoices = Invoice.objects.filter(organization=org).order_by('-created_at')[:50]

    return render(request, 'billing/invoices.html', {
        'organization': org,
        'invoices': invoices,
    })


@login_required
def invoice_detail_view(request, invoice_id):
    """View invoice details."""
    org = getattr(request, 'organization', None)
    if not org:
        messages.info(request, 'Please select an organization first.')
        return redirect('organization_list')

    invoice = get_object_or_404(Invoice, id=invoice_id, organization=org)

    return render(request, 'billing/invoice_detail.html', {
        'organization': org,
        'invoice': invoice,
    })


@login_required
def invoice_download_view(request, invoice_id):
    """Download invoice PDF."""
    org = getattr(request, 'organization', None)
    if not org:
        return JsonResponse({'error': 'No organization selected'}, status=400)

    invoice = get_object_or_404(Invoice, id=invoice_id, organization=org)

    # If PDF URL exists, redirect to it
    if invoice.pdf_url:
        return redirect(invoice.pdf_url)

    # Otherwise generate PDF on the fly
    try:
        from .invoice_generator import generate_invoice_pdf
        pdf_bytes = generate_invoice_pdf(invoice)

        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="{invoice.invoice_number}.pdf"'
        return response
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception('Failed to generate invoice PDF: %s', e)
        messages.error(request, 'Unable to generate invoice PDF.')
        return redirect('billing_manage')


@login_required
def invoices_api(request):
    """AJAX endpoint returning invoices for the current organization."""
    org = getattr(request, 'organization', None)
    if not org:
        return JsonResponse({'error': 'No organization selected'}, status=400)

    invoices = Invoice.objects.filter(organization=org).order_by('-created_at')[:50]

    invoice_list = []
    for inv in invoices:
        invoice_list.append({
            'id': str(inv.id),
            'invoice_number': inv.invoice_number,
            'issued_date': inv.issued_date.isoformat() if inv.issued_date else None,
            'total': inv.get_formatted_total(),
            'status': inv.status,
            'pdf_url': inv.pdf_url,
        })

    return JsonResponse({'invoices': invoice_list})
