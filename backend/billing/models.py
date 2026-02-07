import uuid
from datetime import date
from django.db import models
from users.models import Organization


# Country to tax label mapping
COUNTRY_TAX_LABELS = {
    'IN': ('GST Number', 'GST'),
    'US': ('Tax ID / EIN', 'EIN'),
    'GB': ('VAT Number', 'VAT'),
    'AU': ('ABN', 'ABN'),
    'CA': ('GST/HST Number', 'GST'),
    # EU countries use VAT
    'AT': ('VAT Number', 'VAT'),
    'BE': ('VAT Number', 'VAT'),
    'BG': ('VAT Number', 'VAT'),
    'HR': ('VAT Number', 'VAT'),
    'CY': ('VAT Number', 'VAT'),
    'CZ': ('VAT Number', 'VAT'),
    'DK': ('VAT Number', 'VAT'),
    'EE': ('VAT Number', 'VAT'),
    'FI': ('VAT Number', 'VAT'),
    'FR': ('VAT Number', 'VAT'),
    'DE': ('VAT Number', 'VAT'),
    'GR': ('VAT Number', 'VAT'),
    'HU': ('VAT Number', 'VAT'),
    'IE': ('VAT Number', 'VAT'),
    'IT': ('VAT Number', 'VAT'),
    'LV': ('VAT Number', 'VAT'),
    'LT': ('VAT Number', 'VAT'),
    'LU': ('VAT Number', 'VAT'),
    'MT': ('VAT Number', 'VAT'),
    'NL': ('VAT Number', 'VAT'),
    'PL': ('VAT Number', 'VAT'),
    'PT': ('VAT Number', 'VAT'),
    'RO': ('VAT Number', 'VAT'),
    'SK': ('VAT Number', 'VAT'),
    'SI': ('VAT Number', 'VAT'),
    'ES': ('VAT Number', 'VAT'),
    'SE': ('VAT Number', 'VAT'),
}

# Common countries list for dropdown
COUNTRIES = [
    ('US', 'United States'),
    ('IN', 'India'),
    ('GB', 'United Kingdom'),
    ('CA', 'Canada'),
    ('AU', 'Australia'),
    ('DE', 'Germany'),
    ('FR', 'France'),
    ('NL', 'Netherlands'),
    ('SG', 'Singapore'),
    ('AE', 'United Arab Emirates'),
    ('JP', 'Japan'),
    ('BR', 'Brazil'),
    ('MX', 'Mexico'),
    ('ES', 'Spain'),
    ('IT', 'Italy'),
    ('PL', 'Poland'),
    ('SE', 'Sweden'),
    ('CH', 'Switzerland'),
    ('BE', 'Belgium'),
    ('AT', 'Austria'),
    ('IE', 'Ireland'),
    ('NZ', 'New Zealand'),
    ('ZA', 'South Africa'),
    ('MY', 'Malaysia'),
    ('ID', 'Indonesia'),
    ('TH', 'Thailand'),
    ('PH', 'Philippines'),
    ('VN', 'Vietnam'),
    ('KR', 'South Korea'),
    ('HK', 'Hong Kong'),
]


def get_tax_label_for_country(country_code):
    """Get the appropriate tax label for a country code."""
    return COUNTRY_TAX_LABELS.get(country_code, ('Tax ID', 'TAX'))[0]


def get_tax_type_for_country(country_code):
    """Get the appropriate tax type for a country code."""
    return COUNTRY_TAX_LABELS.get(country_code, ('Tax ID', 'TAX'))[1]


class BillingInfo(models.Model):
    """Billing/invoice information for an organization."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.OneToOneField(
        Organization, on_delete=models.CASCADE, related_name='billing_info'
    )

    # Company/billing name
    billing_name = models.CharField(max_length=255, blank=True, default='')

    # Address fields
    address_line1 = models.CharField(max_length=255, blank=True, default='')
    address_line2 = models.CharField(max_length=255, blank=True, default='')
    city = models.CharField(max_length=100, blank=True, default='')
    state = models.CharField(max_length=100, blank=True, default='')
    postal_code = models.CharField(max_length=20, blank=True, default='')
    country = models.CharField(max_length=2, blank=True, default='', help_text='ISO 3166-1 alpha-2 country code')

    # Tax information
    tax_id = models.CharField(max_length=50, blank=True, default='', help_text='GST/VAT/Tax ID number')
    tax_type = models.CharField(
        max_length=10, blank=True, default='',
        help_text='Tax type: GST, VAT, EIN, ABN, etc.'
    )

    # Billing contact
    billing_email = models.EmailField(blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Billing Info'
        verbose_name_plural = 'Billing Info'

    def __str__(self):
        return f"Billing Info for {self.organization.name}"

    def get_formatted_address(self):
        """Return a formatted multi-line address string."""
        parts = []
        if self.address_line1:
            parts.append(self.address_line1)
        if self.address_line2:
            parts.append(self.address_line2)
        city_state_zip = ', '.join(filter(None, [self.city, self.state, self.postal_code]))
        if city_state_zip:
            parts.append(city_state_zip)
        if self.country:
            country_name = dict(COUNTRIES).get(self.country, self.country)
            parts.append(country_name)
        return '\n'.join(parts)

    def get_tax_label(self):
        """Return the appropriate tax label based on country."""
        return get_tax_label_for_country(self.country)

    def save(self, *args, **kwargs):
        # Auto-set tax_type based on country if not explicitly set
        if self.country and not self.tax_type:
            self.tax_type = get_tax_type_for_country(self.country)
        super().save(*args, **kwargs)


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

    # (No external product IDs needed — PayU uses our tier for identification)

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
    """Tracks an organization's subscription. Updated via PayU webhooks."""

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

    # PayU references
    payu_customer_id = models.CharField(max_length=100, blank=True, default='')
    payu_card_token = models.CharField(
        max_length=200, blank=True, default='',
        help_text='PayU card token (TOKC_*) for recurring charges'
    )

    # Billing dates
    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    next_billing_date = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    canceled_at = models.DateTimeField(null=True, blank=True)

    # Per-user billing (Business plan)
    quantity = models.IntegerField(default=1)

    # Admin override
    is_complimentary = models.BooleanField(
        default=False, help_text='Granted by super admin, bypasses billing'
    )
    complimentary_note = models.TextField(blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['payu_customer_id']),
            models.Index(fields=['status']),
            models.Index(fields=['current_period_end']),
            models.Index(fields=['next_billing_date']),
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
    """Payment history record. Created from PayU order notifications."""

    class Status(models.TextChoices):
        SUCCEEDED = 'succeeded', 'Succeeded'
        FAILED = 'failed', 'Failed'
        PENDING = 'pending', 'Pending'
        REFUNDED = 'refunded', 'Refunded'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subscription = models.ForeignKey(
        Subscription, on_delete=models.CASCADE, related_name='payments'
    )

    # PayU references
    payu_order_id = models.CharField(max_length=100, blank=True, default='')
    payu_transaction_id = models.CharField(max_length=100, blank=True, default='')

    amount_cents = models.IntegerField()
    currency = models.CharField(max_length=3, default='usd')
    status = models.CharField(max_length=20, choices=Status.choices)
    description = models.CharField(max_length=500, blank=True, default='')

    invoice_pdf_url = models.URLField(blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['payu_order_id']),
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


class Invoice(models.Model):
    """Invoice record for completed payments."""

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        ISSUED = 'issued', 'Issued'
        PAID = 'paid', 'Paid'
        VOID = 'void', 'Void'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='invoices'
    )
    payment = models.OneToOneField(
        Payment, on_delete=models.CASCADE, related_name='invoice', null=True, blank=True
    )

    # Auto-generated invoice number (e.g., INV-2026-0001)
    invoice_number = models.CharField(max_length=20, unique=True, db_index=True)

    # Billing snapshot at time of invoice (immutable copy)
    billing_name = models.CharField(max_length=255, blank=True, default='')
    billing_address = models.TextField(blank=True, default='')
    billing_email = models.EmailField(blank=True, default='')
    tax_id = models.CharField(max_length=50, blank=True, default='')
    tax_type = models.CharField(max_length=10, blank=True, default='')

    # Line items stored as JSON
    line_items = models.JSONField(default=list, blank=True)
    # Example: [{"description": "Pro Plan (Monthly)", "quantity": 1, "unit_price": 999, "amount": 999}]

    # Amounts in cents
    subtotal_cents = models.IntegerField(default=0)
    tax_amount_cents = models.IntegerField(default=0)
    total_cents = models.IntegerField(default=0)
    currency = models.CharField(max_length=3, default='USD')

    # Status
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    issued_date = models.DateField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    paid_date = models.DateField(null=True, blank=True)

    # PDF storage
    pdf_url = models.URLField(blank=True, default='', help_text='S3 URL to generated PDF')

    # Metadata
    notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organization', '-created_at']),
            models.Index(fields=['invoice_number']),
            models.Index(fields=['status']),
            models.Index(fields=['issued_date']),
        ]

    def __str__(self):
        return f"{self.invoice_number} - {self.organization.name}"

    @property
    def subtotal(self):
        return self.subtotal_cents / 100

    @property
    def tax_amount(self):
        return self.tax_amount_cents / 100

    @property
    def total(self):
        return self.total_cents / 100

    @classmethod
    def generate_invoice_number(cls):
        """Generate a unique invoice number in format INV-YYYY-NNNN.

        Uses SELECT FOR UPDATE to prevent race conditions when multiple
        invoices are generated concurrently.
        """
        from django.db import transaction

        year = date.today().year
        prefix = f'INV-{year}-'

        with transaction.atomic():
            # Use select_for_update to lock the row and prevent race conditions
            last_invoice = cls.objects.filter(
                invoice_number__startswith=prefix
            ).select_for_update().order_by('-invoice_number').first()

            if last_invoice:
                try:
                    last_num = int(last_invoice.invoice_number.split('-')[-1])
                    next_num = last_num + 1
                except ValueError:
                    next_num = 1
            else:
                next_num = 1

            invoice_number = f'{prefix}{next_num:04d}'

            # Double-check uniqueness (for extra safety)
            while cls.objects.filter(invoice_number=invoice_number).exists():
                next_num += 1
                invoice_number = f'{prefix}{next_num:04d}'

            return invoice_number

    def get_formatted_total(self):
        """Return formatted total with currency symbol."""
        from .currency import format_currency
        return format_currency(self.total_cents, self.currency.upper())
