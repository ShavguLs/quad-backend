# Generated manually for draft reliability - version tracking

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('books', '0014_add_page_html_content'),
    ]

    operations = [
        migrations.AddField(
            model_name='bookpage',
            name='version',
            field=models.PositiveIntegerField(default=1, help_text='Version number for optimistic locking'),
        ),
        migrations.AddField(
            model_name='bookpage',
            name='updated_at',
            field=models.DateTimeField(auto_now=True),
        ),
    ]
