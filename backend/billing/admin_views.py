import json

from django.template.response import TemplateResponse
from django.utils import timezone
from django.db.models import Sum, Count
from django.db.models.functions import TruncMonth
from datetime import timedelta


def billing_dashboard_view(request):
    """Super admin billing dashboard with revenue and usage metrics."""
    from .models import Subscription, Payment
    from meetings.models import Meeting, MeetingRecording
    from users.models import OrganizationMembership

    now = timezone.now()
    thirty_days_ago = now - timedelta(days=30)
    six_months_ago = now - timedelta(days=180)
    seven_days = now + timedelta(days=7)

    # Revenue Metrics
    active_subs = Subscription.objects.filter(
        status__in=['active', 'trialing', 'past_due']
    ).select_related('plan')

    mrr_cents = 0
    for sub in active_subs:
        if sub.billing_cycle == 'monthly':
            if sub.plan.is_per_user:
                mrr_cents += sub.plan.monthly_price_cents * sub.quantity
            else:
                mrr_cents += sub.plan.monthly_price_cents
        else:
            if sub.plan.is_per_user:
                mrr_cents += (sub.plan.annual_price_cents * sub.quantity) / 12
            else:
                mrr_cents += sub.plan.annual_price_cents / 12

    mrr = mrr_cents / 100
    arr = mrr * 12

    # Revenue by plan (last 30 days)
    revenue_by_plan = list(
        Payment.objects.filter(status='succeeded', created_at__gte=thirty_days_ago)
        .values('subscription__plan__name')
        .annotate(total=Sum('amount_cents'))
        .order_by('-total')
    )

    # Subscription analytics
    total_orgs = Subscription.objects.count()
    orgs_by_plan = list(
        Subscription.objects.values('plan__name', 'plan__tier')
        .annotate(count=Count('id'))
        .order_by('plan__display_order')
    )

    new_subs_30d = Subscription.objects.filter(
        created_at__gte=thirty_days_ago
    ).exclude(plan__tier='free').count()

    churned_30d = Subscription.objects.filter(
        status='canceled', canceled_at__gte=thirty_days_ago
    ).count()

    complimentary_count = Subscription.objects.filter(is_complimentary=True).count()

    # Payment health
    recent_payments = Payment.objects.filter(created_at__gte=thirty_days_ago)
    successful_payments = recent_payments.filter(status='succeeded').count()
    failed_payments = recent_payments.filter(status='failed').count()

    total_revenue_30d = recent_payments.filter(status='succeeded').aggregate(
        total=Sum('amount_cents')
    )['total'] or 0

    upcoming_renewals = Subscription.objects.filter(
        status='active',
        current_period_end__gte=now,
        current_period_end__lte=seven_days,
    ).count()

    # Usage metrics
    meetings_last_30 = Meeting.objects.filter(created_at__gte=thirty_days_ago).count()
    active_users = OrganizationMembership.objects.filter(
        is_active=True
    ).values('user').distinct().count()
    total_storage = MeetingRecording.objects.aggregate(
        total=Sum('file_size')
    )['total'] or 0

    # Monthly revenue trend (last 6 months)
    monthly_revenue = list(
        Payment.objects.filter(status='succeeded', created_at__gte=six_months_ago)
        .annotate(month=TruncMonth('created_at'))
        .values('month')
        .annotate(total=Sum('amount_cents'))
        .order_by('month')
    )

    context = {
        'title': 'Billing Dashboard',
        'mrr': mrr,
        'arr': arr,
        'revenue_by_plan': revenue_by_plan,
        'total_revenue_30d': total_revenue_30d / 100,
        'total_orgs': total_orgs,
        'orgs_by_plan': orgs_by_plan,
        'new_subs_30d': new_subs_30d,
        'churned_30d': churned_30d,
        'complimentary_count': complimentary_count,
        'successful_payments': successful_payments,
        'failed_payments': failed_payments,
        'upcoming_renewals': upcoming_renewals,
        'meetings_last_30': meetings_last_30,
        'active_users': active_users,
        'total_storage_gb': round(total_storage / (1024 ** 3), 2),
        'monthly_revenue': json.dumps([
            {'month': r['month'].strftime('%b %Y'), 'total': r['total'] / 100}
            for r in monthly_revenue
        ]),
    }

    return TemplateResponse(request, 'admin/billing_dashboard.html', context)
