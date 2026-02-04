from django.db import migrations


def seed_plans(apps, schema_editor):
    Plan = apps.get_model('billing', 'Plan')

    Plan.objects.create(
        name='Free',
        tier='free',
        monthly_price_cents=0,
        annual_price_cents=0,
        is_per_user=False,
        max_rooms=1,
        max_participants=4,
        max_meeting_duration_minutes=30,
        recording_enabled=False,
        custom_branding=False,
        custom_subdomain=False,
        breakout_rooms=False,
        waiting_rooms=False,
        description='Get started with basic video conferencing.',
        display_order=0,
    )

    Plan.objects.create(
        name='Pro',
        tier='pro',
        monthly_price_cents=899,
        annual_price_cents=8599,
        is_per_user=False,
        max_rooms=3,
        max_participants=100,
        max_meeting_duration_minutes=-1,
        recording_enabled=True,
        custom_branding=True,
        custom_subdomain=False,
        breakout_rooms=False,
        waiting_rooms=False,
        description='For professionals who need more from their meetings.',
        display_order=1,
    )

    Plan.objects.create(
        name='Business',
        tier='business',
        monthly_price_cents=1199,
        annual_price_cents=11499,
        is_per_user=True,
        max_rooms=-1,
        max_participants=200,
        max_meeting_duration_minutes=-1,
        recording_enabled=True,
        custom_branding=True,
        custom_subdomain=True,
        breakout_rooms=True,
        waiting_rooms=True,
        description='Full-featured solution for teams and enterprises.',
        display_order=2,
    )


def remove_plans(apps, schema_editor):
    Plan = apps.get_model('billing', 'Plan')
    Plan.objects.filter(tier__in=['free', 'pro', 'business']).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_plans, remove_plans),
    ]
