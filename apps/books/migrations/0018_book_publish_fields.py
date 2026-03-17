# Generated manually for publish_status fields

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('books', '0017_add_intake_diagnostics'),
    ]

    operations = [
        migrations.AddField(
            model_name='book',
            name='publish_status',
            field=models.CharField(
                choices=[('idle', 'Idle'), ('publishing', 'Publishing'), ('published', 'Published'), ('failed', 'Failed')],
                default='idle',
                help_text='Async publishing status',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='book',
            name='publish_error',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='book',
            name='publish_finished_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='book',
            name='publish_started_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
