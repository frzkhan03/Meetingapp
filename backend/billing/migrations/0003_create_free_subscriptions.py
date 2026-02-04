from django.db import migrations


def create_free_subscriptions(apps, schema_editor):
    Organization = apps.get_model('users', 'Organization')
    Plan = apps.get_model('billing', 'Plan')
    Subscription = apps.get_model('billing', 'Subscription')

    try:
        free_plan = Plan.objects.get(tier='free')
    except Plan.DoesNotExist:
        return

    for org in Organization.objects.all():
        Subscription.objects.get_or_create(
            organization=org,
            defaults={
                'plan': free_plan,
                'status': 'active',
                'billing_cycle': 'monthly',
            }
        )


def remove_free_subscriptions(apps, schema_editor):
    Subscription = apps.get_model('billing', 'Subscription')
    Subscription.objects.filter(plan__tier='free', stripe_subscription_id='').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0002_seed_plans'),
        ('users', '0005_organization_recording_to_s3'),
    ]

    operations = [
        migrations.RunPython(create_free_subscriptions, remove_free_subscriptions),
    ]
