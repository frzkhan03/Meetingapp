from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0003_create_free_subscriptions'),
    ]

    operations = [
        # ---- Plan: remove Stripe fields ----
        migrations.RemoveField(model_name='plan', name='stripe_product_id'),
        migrations.RemoveField(model_name='plan', name='stripe_monthly_price_id'),
        migrations.RemoveField(model_name='plan', name='stripe_annual_price_id'),

        # ---- Subscription: rename stripe_customer_id → payu_customer_id ----
        migrations.RenameField(
            model_name='subscription',
            old_name='stripe_customer_id',
            new_name='payu_customer_id',
        ),

        # ---- Subscription: remove stripe_subscription_id ----
        migrations.RemoveField(model_name='subscription', name='stripe_subscription_id'),

        # ---- Subscription: add payu_card_token ----
        migrations.AddField(
            model_name='subscription',
            name='payu_card_token',
            field=models.CharField(
                blank=True, default='', max_length=200,
                help_text='PayU card token (TOKC_*) for recurring charges',
            ),
        ),

        # ---- Subscription: add next_billing_date ----
        migrations.AddField(
            model_name='subscription',
            name='next_billing_date',
            field=models.DateTimeField(blank=True, null=True),
        ),

        # ---- Subscription: update help_text on is_complimentary ----
        migrations.AlterField(
            model_name='subscription',
            name='is_complimentary',
            field=models.BooleanField(
                default=False, help_text='Granted by super admin, bypasses billing',
            ),
        ),

        # ---- Payment: rename stripe fields → payu fields ----
        migrations.RenameField(
            model_name='payment',
            old_name='stripe_invoice_id',
            new_name='payu_order_id',
        ),
        migrations.RenameField(
            model_name='payment',
            old_name='stripe_charge_id',
            new_name='payu_transaction_id',
        ),

        # ---- Payment: remove stripe_payment_intent_id ----
        migrations.RemoveField(model_name='payment', name='stripe_payment_intent_id'),

        # ---- Subscription: update indexes ----
        # Remove old Stripe indexes
        migrations.RemoveIndex(model_name='subscription', name='billing_sub_stripe__97887e_idx'),
        migrations.RemoveIndex(model_name='subscription', name='billing_sub_stripe__abc269_idx'),
        # Add new PayU indexes
        migrations.AddIndex(
            model_name='subscription',
            index=models.Index(fields=['payu_customer_id'], name='billing_sub_payu_cu_41b0c1_idx'),
        ),
        migrations.AddIndex(
            model_name='subscription',
            index=models.Index(fields=['next_billing_date'], name='billing_sub_next_bi_0f9556_idx'),
        ),

        # ---- Payment: update indexes ----
        migrations.RemoveIndex(model_name='payment', name='billing_pay_stripe__5ad6f9_idx'),
        migrations.AddIndex(
            model_name='payment',
            index=models.Index(fields=['payu_order_id'], name='billing_pay_payu_or_258c47_idx'),
        ),
    ]
