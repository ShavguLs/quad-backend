from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('books', '0005_book_analytics_fields_and_models'),
    ]

    operations = [
        migrations.AddField(
            model_name='book',
            name='is_visible',
            field=models.BooleanField(
                default=True,
                help_text='Controls whether the book is visible in public endpoints.'
            ),
        ),
    ]
