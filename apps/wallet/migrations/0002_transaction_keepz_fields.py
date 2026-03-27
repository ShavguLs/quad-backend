from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('wallet', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='transaction',
            name='credited_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='transaction',
            name='provider',
            field=models.CharField(blank=True, max_length=20, null=True),
        ),
        migrations.AddField(
            model_name='transaction',
            name='provider_order_id',
            field=models.CharField(blank=True, db_index=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='transaction',
            name='provider_payload',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='transaction',
            name='provider_status',
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
    ]
