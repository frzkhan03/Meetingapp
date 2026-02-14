from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0001_initial'),
        ('meetings', '0013_meetingtranscript'),
    ]

    operations = [
        migrations.CreateModel(
            name='ConnectionLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('room_id', models.CharField(db_index=True, max_length=50)),
                ('user_id', models.CharField(help_text='PeerJS user ID or display name', max_length=100)),
                ('connected_at', models.DateTimeField()),
                ('disconnected_at', models.DateTimeField(auto_now_add=True)),
                ('duration_seconds', models.PositiveIntegerField(default=0)),
                ('avg_bitrate_kbps', models.FloatField(default=0)),
                ('min_bitrate_kbps', models.FloatField(default=0)),
                ('max_bitrate_kbps', models.FloatField(default=0)),
                ('avg_rtt_ms', models.FloatField(default=0)),
                ('packet_loss_pct', models.FloatField(default=0)),
                ('quality_tier_changes', models.JSONField(blank=True, default=list)),
                ('reconnection_count', models.PositiveIntegerField(default=0)),
                ('browser', models.CharField(blank=True, default='', max_length=100)),
                ('device_type', models.CharField(blank=True, default='', max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('organization', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='connection_logs',
                    to='users.organization',
                )),
            ],
            options={
                'ordering': ['-created_at'],
                'indexes': [
                    models.Index(fields=['room_id', '-created_at'], name='meetings_co_room_id_idx'),
                    models.Index(fields=['organization', '-created_at'], name='meetings_co_org_idx'),
                ],
            },
        ),
    ]
