from django.contrib import admin
from .models import Plan, Subscription, Payment, UsageRecord
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
    search_fields = ['organization__name', 'stripe_customer_id', 'stripe_subscription_id']
    readonly_fields = ['id', 'created_at', 'updated_at', 'stripe_customer_id',
                       'stripe_subscription_id']
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
    search_fields = ['stripe_invoice_id', 'stripe_charge_id',
                     'subscription__organization__name']
    readonly_fields = ['id', 'created_at']


@admin.register(UsageRecord)
class UsageRecordAdmin(admin.ModelAdmin):
    list_display = ['organization', 'metric', 'value', 'recorded_at']
    list_filter = ['metric', 'recorded_at']
    search_fields = ['organization__name']
    readonly_fields = ['id']
