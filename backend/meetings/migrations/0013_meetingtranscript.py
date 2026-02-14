from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('meetings', '0012_merge_20260214_2026'),
        ('users', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='MeetingTranscript',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('room_id', models.CharField(db_index=True, max_length=50)),
                ('entries', models.JSONField(default=list, help_text='List of {timestamp, speaker, text}')),
                ('status', models.CharField(choices=[('recording', 'Recording'), ('completed', 'Completed')], default='recording', max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='transcripts', to=settings.AUTH_USER_MODEL)),
                ('meeting', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='transcripts', to='meetings.meeting')),
                ('organization', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='transcripts', to='users.organization')),
            ],
            options={
                'ordering': ['-created_at'],
                'indexes': [
                    models.Index(fields=['room_id', '-created_at'], name='meetings_me_room_id_transcript_idx'),
                ],
            },
        ),
    ]
