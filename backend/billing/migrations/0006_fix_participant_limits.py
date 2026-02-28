from django.db import migrations


def fix_participant_limits(apps, schema_editor):
    """Set realistic participant limits for mesh WebRTC topology."""
    Plan = apps.get_model('billing', 'Plan')
    Plan.objects.filter(tier='pro').update(max_participants=15)
    Plan.objects.filter(tier='business').update(max_participants=25)


def revert_participant_limits(apps, schema_editor):
    Plan = apps.get_model('billing', 'Plan')
    Plan.objects.filter(tier='pro').update(max_participants=100)
    Plan.objects.filter(tier='business').update(max_participants=200)


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0005_add_billing_info_and_invoice'),
    ]

    operations = [
        migrations.RunPython(fix_participant_limits, revert_participant_limits),
    ]
