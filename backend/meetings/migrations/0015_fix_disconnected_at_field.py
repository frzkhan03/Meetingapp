from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('meetings', '0014_connectionlog'),
    ]

    operations = [
        migrations.AlterField(
            model_name='connectionlog',
            name='disconnected_at',
            field=models.DateTimeField(),
        ),
    ]
