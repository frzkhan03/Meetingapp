from django.contrib import admin
from .models import Plan, Subscription, Payment, UsageRecord, BillingInfo, Invoice
from .plan_limits import invalidate_plan_cache


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ['name', 'tier', 'monthly_price', 'annual_price', 'max_rooms',
                    'max_participants', 'recording_enabled', 'is_active', 'display_order']
    list_filter = ['tier', 'is_active']
    readonly_fields = ['id', 'created_at', 'updated_at']
    ordering = ['display_order']


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ['organization', 'plan', 'status', 'billing_cycle',
                    'current_period_end', 'is_complimentary', 'cancel_at_period_end', 'quantity']
    list_filter = ['status', 'plan', 'billing_cycle', 'is_complimentary']
    search_fields = ['organization__name', 'payu_customer_id']
    readonly_fields = ['id', 'created_at', 'updated_at', 'payu_customer_id',
                       'payu_card_token']
    actions = ['grant_complimentary', 'revoke_complimentary']

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
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['subscription', 'amount', 'currency', 'status', 'created_at']
    list_filter = ['status', 'currency', 'created_at']
    search_fields = ['payu_order_id', 'payu_transaction_id',
                     'subscription__organization__name']
    readonly_fields = ['id', 'created_at']


@admin.register(UsageRecord)
class UsageRecordAdmin(admin.ModelAdmin):
    list_display = ['organization', 'metric', 'value', 'recorded_at']
    list_filter = ['metric', 'recorded_at']
    search_fields = ['organization__name']
    readonly_fields = ['id']


@admin.register(BillingInfo)
class BillingInfoAdmin(admin.ModelAdmin):
    list_display = ['organization', 'billing_name', 'country', 'tax_type', 'tax_id', 'updated_at']
    list_filter = ['country', 'tax_type']
    search_fields = ['organization__name', 'billing_name', 'tax_id']
    readonly_fields = ['id', 'created_at', 'updated_at']


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ['invoice_number', 'organization', 'total', 'currency', 'status', 'issued_date', 'created_at']
    list_filter = ['status', 'currency', 'issued_date']
    search_fields = ['invoice_number', 'organization__name', 'billing_name', 'tax_id']
    readonly_fields = ['id', 'invoice_number', 'created_at', 'updated_at']
    date_hierarchy = 'issued_date'

    fieldsets = (
        ('Invoice Info', {
            'fields': ('id', 'invoice_number', 'organization', 'payment', 'status')
        }),
        ('Billing Details', {
            'fields': ('billing_name', 'billing_address', 'billing_email', 'tax_id', 'tax_type')
        }),
        ('Amounts', {
            'fields': ('line_items', 'subtotal_cents', 'tax_amount_cents', 'total_cents', 'currency')
        }),
        ('Dates', {
            'fields': ('issued_date', 'due_date', 'paid_date')
        }),
        ('PDF', {
            'fields': ('pdf_url',)
        }),
        ('Notes', {
            'fields': ('notes',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
