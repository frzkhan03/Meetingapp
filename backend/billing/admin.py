from django.contrib import admin
from django.db.models import Sum, Q
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline
from .models import Plan, Subscription, Payment, UsageRecord, BillingInfo, Invoice
from .plan_limits import invalidate_plan_cache


class PaymentInline(TabularInline):
    model = Payment
    extra = 0
    fields = ['formatted_amount', 'currency', 'status_badge', 'payu_order_id', 'created_at']
    readonly_fields = ['formatted_amount', 'currency', 'status_badge', 'payu_order_id', 'created_at']
    ordering = ['-created_at']
    max_num = 20

    @admin.display(description='Amount')
    def formatted_amount(self, obj):
        return f"${obj.amount_cents / 100:.2f}"

    @admin.display(description='Status')
    def status_badge(self, obj):
        colors = {
            'succeeded': '#22c55e',
            'failed': '#ef4444',
            'pending': '#f59e0b',
            'refunded': '#6b7280',
        }
        color = colors.get(obj.status, '#6b7280')
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:9999px;font-size:0.75rem;">{}</span>',
            color, obj.get_status_display()
        )


@admin.register(Plan)
class PlanAdmin(ModelAdmin):
    list_display = [
        'name', 'tier', 'formatted_monthly', 'formatted_annual',
        'is_per_user', 'max_rooms_display', 'max_participants',
        'max_duration_display', 'feature_list',
        'active_subscriptions', 'is_active', 'display_order',
    ]
    list_filter = ['tier', 'is_active']
    readonly_fields = ['id', 'created_at', 'updated_at']
    ordering = ['display_order']
    list_per_page = 10

    fieldsets = (
        ('Plan Info', {
            'fields': ('id', 'name', 'tier', 'description', 'is_active', 'display_order'),
        }),
        ('Pricing', {
            'fields': ('monthly_price_cents', 'annual_price_cents', 'is_per_user'),
        }),
        ('Limits', {
            'fields': ('max_rooms', 'max_participants', 'max_meeting_duration_minutes'),
            'description': 'Use -1 for unlimited.',
        }),
        ('Features', {
            'fields': ('recording_enabled', 'custom_branding', 'custom_subdomain',
                       'breakout_rooms', 'waiting_rooms'),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    def get_queryset(self, request):
        from django.db.models import Count
        return super().get_queryset(request).annotate(
            _active_subs=Count(
                'subscriptions',
                filter=Q(subscriptions__status__in=['active', 'trialing']),
                distinct=True,
            )
        )

    @admin.display(description='Monthly', ordering='monthly_price_cents')
    def formatted_monthly(self, obj):
        if obj.monthly_price_cents == 0:
            return format_html('<span style="color:#22c55e;font-weight:600;">{}</span>', 'Free')
        return f"${obj.monthly_price_cents / 100:.2f}"

    @admin.display(description='Annual', ordering='annual_price_cents')
    def formatted_annual(self, obj):
        if obj.annual_price_cents == 0:
            return format_html('<span style="color:#22c55e;font-weight:600;">{}</span>', 'Free')
        return f"${obj.annual_price_cents / 100:.2f}"

    @admin.display(description='Rooms')
    def max_rooms_display(self, obj):
        return 'Unlimited' if obj.max_rooms == -1 else str(obj.max_rooms)

    @admin.display(description='Duration')
    def max_duration_display(self, obj):
        if obj.max_meeting_duration_minutes == -1:
            return 'Unlimited'
        if obj.max_meeting_duration_minutes >= 60:
            hours = obj.max_meeting_duration_minutes / 60
            return f"{hours:.0f}h" if hours == int(hours) else f"{hours:.1f}h"
        return f"{obj.max_meeting_duration_minutes}m"

    @admin.display(description='Features')
    def feature_list(self, obj):
        features = []
        if obj.recording_enabled:
            features.append('Rec')
        if obj.custom_branding:
            features.append('Brand')
        if obj.breakout_rooms:
            features.append('Breakout')
        if obj.waiting_rooms:
            features.append('Waiting')
        if obj.custom_subdomain:
            features.append('Subdomain')
        return ', '.join(features) if features else '-'

    @admin.display(description='Active Subs', ordering='_active_subs')
    def active_subscriptions(self, obj):
        return obj._active_subs


@admin.register(Subscription)
class SubscriptionAdmin(ModelAdmin):
    list_display = [
        'organization', 'plan', 'status_badge', 'billing_cycle',
        'current_period_end', 'quantity',
        'is_complimentary', 'cancel_at_period_end', 'total_paid',
    ]
    list_filter = ['status', 'plan', 'billing_cycle', 'is_complimentary', 'cancel_at_period_end']
    search_fields = ['organization__name', 'payu_customer_id']
    readonly_fields = [
        'id', 'created_at', 'updated_at',
        'payu_customer_id', 'payu_card_token',
    ]
    autocomplete_fields = ['organization', 'plan']
    list_per_page = 25
    actions = ['grant_complimentary', 'revoke_complimentary']
    inlines = [PaymentInline]

    fieldsets = (
        ('Subscription Info', {
            'fields': ('id', 'organization', 'plan', 'status', 'billing_cycle', 'quantity'),
        }),
        ('Billing Period', {
            'fields': ('current_period_start', 'current_period_end', 'next_billing_date'),
        }),
        ('Cancellation', {
            'fields': ('cancel_at_period_end', 'canceled_at'),
        }),
        ('Complimentary', {
            'fields': ('is_complimentary', 'complimentary_note'),
            'description': 'Grant free access overriding billing.',
        }),
        ('PayU', {
            'fields': ('payu_customer_id', 'payu_card_token'),
            'classes': ('collapse',),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _total_paid=Sum(
                'payments__amount_cents',
                filter=Q(payments__status='succeeded'),
            )
        )

    @admin.display(description='Status')
    def status_badge(self, obj):
        colors = {
            'active': '#22c55e',
            'trialing': '#3b82f6',
            'past_due': '#f59e0b',
            'canceled': '#ef4444',
            'incomplete': '#6b7280',
            'incomplete_expired': '#6b7280',
            'unpaid': '#ef4444',
            'paused': '#a855f7',
        }
        color = colors.get(obj.status, '#6b7280')
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:9999px;font-size:0.75rem;">{}</span>',
            color, obj.get_status_display()
        )

    @admin.display(description='Total Paid', ordering='_total_paid')
    def total_paid(self, obj):
        total = obj._total_paid
        if total is None:
            return '$0.00'
        return f"${total / 100:.2f}"

    def grant_complimentary(self, request, queryset):
        queryset.update(is_complimentary=True, status='active')
        for sub in queryset:
            invalidate_plan_cache(str(sub.organization_id))
        self.message_user(request, f"Granted complimentary access to {queryset.count()} subscription(s).")
    grant_complimentary.short_description = "Grant complimentary access"

    def revoke_complimentary(self, request, queryset):
        queryset.update(is_complimentary=False)
        for sub in queryset:
            invalidate_plan_cache(str(sub.organization_id))
        self.message_user(request, f"Revoked complimentary access from {queryset.count()} subscription(s).")
    revoke_complimentary.short_description = "Revoke complimentary access"


@admin.register(Payment)
class PaymentAdmin(ModelAdmin):
    list_display = [
        'formatted_amount', 'currency', 'status_badge',
        'subscription_org', 'subscription_plan',
        'payu_order_id', 'created_at',
    ]
    list_filter = ['status', 'currency', 'created_at']
    search_fields = [
        'payu_order_id', 'payu_transaction_id',
        'subscription__organization__name',
    ]
    readonly_fields = ['id', 'created_at']
    date_hierarchy = 'created_at'
    list_per_page = 50

    fieldsets = (
        ('Payment Info', {
            'fields': ('id', 'subscription', 'status', 'description'),
        }),
        ('Amount', {
            'fields': ('amount_cents', 'currency'),
        }),
        ('PayU References', {
            'fields': ('payu_order_id', 'payu_transaction_id'),
        }),
        ('Invoice', {
            'fields': ('invoice_pdf_url',),
        }),
        ('Timestamps', {
            'fields': ('created_at',),
        }),
    )

    @admin.display(description='Amount', ordering='amount_cents')
    def formatted_amount(self, obj):
        return f"${obj.amount_cents / 100:.2f}"

    @admin.display(description='Status')
    def status_badge(self, obj):
        colors = {
            'succeeded': '#22c55e',
            'failed': '#ef4444',
            'pending': '#f59e0b',
            'refunded': '#6b7280',
        }
        color = colors.get(obj.status, '#6b7280')
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:9999px;font-size:0.75rem;">{}</span>',
            color, obj.get_status_display()
        )

    @admin.display(description='Organization')
    def subscription_org(self, obj):
        return obj.subscription.organization.name

    @admin.display(description='Plan')
    def subscription_plan(self, obj):
        return obj.subscription.plan.name


@admin.register(UsageRecord)
class UsageRecordAdmin(ModelAdmin):
    list_display = ['organization', 'metric', 'formatted_value', 'recorded_at']
    list_filter = ['metric', 'recorded_at', 'organization']
    search_fields = ['organization__name']
    readonly_fields = ['id']
    date_hierarchy = 'recorded_at'
    list_per_page = 50

    @admin.display(description='Value')
    def formatted_value(self, obj):
        if obj.metric == 'storage_bytes':
            if obj.value < 1024 * 1024:
                return f"{obj.value / 1024:.1f} KB"
            if obj.value < 1024 * 1024 * 1024:
                return f"{obj.value / (1024 * 1024):.1f} MB"
            return f"{obj.value / (1024 * 1024 * 1024):.2f} GB"
        if obj.metric == 'meeting_minutes':
            if obj.value >= 60:
                return f"{obj.value // 60}h {obj.value % 60}m"
            return f"{obj.value}m"
        return str(obj.value)


@admin.register(BillingInfo)
class BillingInfoAdmin(ModelAdmin):
    list_display = [
        'organization', 'billing_name', 'city', 'country',
        'tax_type', 'tax_id', 'billing_email', 'updated_at',
    ]
    list_filter = ['country', 'tax_type']
    search_fields = ['organization__name', 'billing_name', 'tax_id', 'billing_email']
    readonly_fields = ['id', 'created_at', 'updated_at', 'formatted_address_display']
    autocomplete_fields = ['organization']

    fieldsets = (
        ('Organization', {
            'fields': ('id', 'organization'),
        }),
        ('Billing Contact', {
            'fields': ('billing_name', 'billing_email'),
        }),
        ('Address', {
            'fields': (
                'address_line1', 'address_line2', 'city',
                'state', 'postal_code', 'country',
                'formatted_address_display',
            ),
        }),
        ('Tax Information', {
            'fields': ('tax_type', 'tax_id'),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    @admin.display(description='Full Address')
    def formatted_address_display(self, obj):
        addr = obj.get_formatted_address()
        if addr:
            return format_html('<pre style="margin:0;">{}</pre>', addr)
        return '-'


@admin.register(Invoice)
class InvoiceAdmin(ModelAdmin):
    list_display = [
        'invoice_number', 'organization', 'formatted_total',
        'currency', 'status_badge', 'issued_date', 'due_date', 'created_at',
    ]
    list_filter = ['status', 'currency', 'issued_date']
    search_fields = ['invoice_number', 'organization__name', 'billing_name', 'tax_id']
    readonly_fields = ['id', 'invoice_number', 'created_at', 'updated_at']
    date_hierarchy = 'issued_date'
    list_per_page = 25

    fieldsets = (
        ('Invoice Info', {
            'fields': ('id', 'invoice_number', 'organization', 'payment', 'status'),
        }),
        ('Billing Details', {
            'fields': ('billing_name', 'billing_address', 'billing_email', 'tax_id', 'tax_type'),
        }),
        ('Line Items', {
            'fields': ('line_items',),
        }),
        ('Amounts', {
            'fields': ('subtotal_cents', 'tax_amount_cents', 'total_cents', 'currency'),
        }),
        ('Dates', {
            'fields': ('issued_date', 'due_date', 'paid_date'),
        }),
        ('PDF', {
            'fields': ('pdf_url',),
        }),
        ('Notes', {
            'fields': ('notes',),
            'classes': ('collapse',),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    @admin.display(description='Total', ordering='total_cents')
    def formatted_total(self, obj):
        return f"${obj.total_cents / 100:.2f}"

    @admin.display(description='Status')
    def status_badge(self, obj):
        colors = {
            'draft': '#6b7280',
            'issued': '#3b82f6',
            'paid': '#22c55e',
            'void': '#ef4444',
        }
        color = colors.get(obj.status, '#6b7280')
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:9999px;font-size:0.75rem;">{}</span>',
            color, obj.get_status_display()
        )
