import uuid
from django.db import models
from users.models import Organization


class Plan(models.Model):
    """Pricing plan definition. Seeded via data migration."""

    class PlanTier(models.TextChoices):
        FREE = 'free', 'Free'
        PRO = 'pro', 'Pro'
        BUSINESS = 'business', 'Business'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=50)
    tier = models.CharField(max_length=20, choices=PlanTier.choices, unique=True)

    # Pricing
    monthly_price_cents = models.IntegerField(default=0)
    annual_price_cents = models.IntegerField(default=0)
    is_per_user = models.BooleanField(default=False)

    # Stripe references
    stripe_product_id = models.CharField(max_length=100, blank=True, default='')
    stripe_monthly_price_id = models.CharField(max_length=100, blank=True, default='')
    stripe_annual_price_id = models.CharField(max_length=100, blank=True, default='')

    # Feature limits (-1 means unlimited)
    max_rooms = models.IntegerField(default=1)
    max_participants = models.IntegerField(default=4)
    max_meeting_duration_minutes = models.IntegerField(default=30)
    recording_enabled = models.BooleanField(default=False)
    custom_branding = models.BooleanField(default=False)
    custom_subdomain = models.BooleanField(default=False)
    breakout_rooms = models.BooleanField(default=False)
    waiting_rooms = models.BooleanField(default=False)

    # Display
    description = models.TextField(blank=True, default='')
    is_active = models.BooleanField(default=True)
    display_order = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order']

    def __str__(self):
        return self.name

    @property
    def monthly_price(self):
        return self.monthly_price_cents / 100

    @property
    def annual_price(self):
        return self.annual_price_cents / 100

    @property
    def has_unlimited_rooms(self):
        return self.max_rooms == -1

    @property
    def has_unlimited_duration(self):
        return self.max_meeting_duration_minutes == -1


class Subscription(models.Model):
    """Tracks an organization's subscription. Synced from Stripe via webhooks."""

    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        PAST_DUE = 'past_due', 'Past Due'
        CANCELED = 'canceled', 'Canceled'
        INCOMPLETE = 'incomplete', 'Incomplete'
        INCOMPLETE_EXPIRED = 'incomplete_expired', 'Incomplete Expired'
        TRIALING = 'trialing', 'Trialing'
        UNPAID = 'unpaid', 'Unpaid'
        PAUSED = 'paused', 'Paused'

    class BillingCycle(models.TextChoices):
        MONTHLY = 'monthly', 'Monthly'
        ANNUAL = 'annual', 'Annual'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.OneToOneField(
        Organization, on_delete=models.CASCADE, related_name='subscription'
    )
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name='subscriptions')
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.ACTIVE)
    billing_cycle = models.CharField(
        max_length=10, choices=BillingCycle.choices, default=BillingCycle.MONTHLY
    )

    # Stripe references
    stripe_customer_id = models.CharField(max_length=100, blank=True, default='')
    stripe_subscription_id = models.CharField(max_length=100, blank=True, default='')

    # Billing dates
    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    canceled_at = models.DateTimeField(null=True, blank=True)

    # Per-user billing (Business plan)
    quantity = models.IntegerField(default=1)

    # Admin override
    is_complimentary = models.BooleanField(
        default=False, help_text='Granted by super admin, bypasses Stripe'
    )
    complimentary_note = models.TextField(blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['stripe_customer_id']),
            models.Index(fields=['stripe_subscription_id']),
            models.Index(fields=['status']),
            models.Index(fields=['current_period_end']),
        ]

    def __str__(self):
        return f"{self.organization.name} - {self.plan.name} ({self.status})"

    @property
    def is_active_subscription(self):
        """Returns True if the subscription grants access to paid features."""
        return self.status in (
            self.Status.ACTIVE,
            self.Status.TRIALING,
            self.Status.PAST_DUE,
        ) or self.is_complimentary


class Payment(models.Model):
    """Payment history record. Synced from Stripe invoices."""

    class Status(models.TextChoices):
        SUCCEEDED = 'succeeded', 'Succeeded'
        FAILED = 'failed', 'Failed'
        PENDING = 'pending', 'Pending'
        REFUNDED = 'refunded', 'Refunded'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subscription = models.ForeignKey(
        Subscription, on_delete=models.CASCADE, related_name='payments'
    )

    # Stripe references
    stripe_invoice_id = models.CharField(max_length=100, blank=True, default='')
    stripe_charge_id = models.CharField(max_length=100, blank=True, default='')
    stripe_payment_intent_id = models.CharField(max_length=100, blank=True, default='')

    amount_cents = models.IntegerField()
    currency = models.CharField(max_length=3, default='usd')
    status = models.CharField(max_length=20, choices=Status.choices)
    description = models.CharField(max_length=500, blank=True, default='')

    invoice_pdf_url = models.URLField(blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['stripe_invoice_id']),
            models.Index(fields=['subscription', '-created_at']),
        ]

    def __str__(self):
        return f"${self.amount_cents / 100:.2f} - {self.status} - {self.created_at}"

    @property
    def amount(self):
        return self.amount_cents / 100


class UsageRecord(models.Model):
    """Daily usage tracking per organization for analytics."""

    class MetricType(models.TextChoices):
        MEETING_MINUTES = 'meeting_minutes', 'Meeting Minutes'
        PARTICIPANTS = 'participants', 'Participants'
        RECORDINGS = 'recordings', 'Recordings'
        STORAGE_BYTES = 'storage_bytes', 'Storage (bytes)'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='usage_records'
    )
    metric = models.CharField(max_length=30, choices=MetricType.choices)
    value = models.BigIntegerField(default=0)
    recorded_at = models.DateField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['organization', 'metric', 'recorded_at']),
            models.Index(fields=['recorded_at']),
        ]
        unique_together = ['organization', 'metric', 'recorded_at']

    def __str__(self):
        return f"{self.organization.name} - {self.metric}: {self.value}"
