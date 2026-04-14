# Generated migration for LiveKit integration

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('meetings', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='meetingrecording',
            name='livekit_egress_id',
            field=models.CharField(
                blank=True,
                max_length=255,
                null=True,
                help_text='LiveKit egress/recording ID for tracking recording status',
                verbose_name='LiveKit Egress ID'
            ),
        ),
        migrations.AddField(
            model_name='meetingrecording',
            name='recording_status',
            field=models.CharField(
                choices=[
                    ('pending', 'Pending'),
                    ('in_progress', 'In Progress'),
                    ('completed', 'Completed'),
                    ('failed', 'Failed'),
                ],
                default='pending',
                max_length=20,
                help_text='Current status of the recording',
                verbose_name='Recording Status'
            ),
        ),
        migrations.AlterField(
            model_name='meetingrecording',
            name='file_path',
            field=models.CharField(
                max_length=500,
                blank=True,
                null=True,
                help_text='S3 path or local file path to the recording',
                verbose_name='File Path'
            ),
        ),
    ]