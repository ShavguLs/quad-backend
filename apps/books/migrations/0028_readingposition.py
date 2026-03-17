from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('books', '0027_savedpage'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ReadingPosition',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('page_number', models.PositiveIntegerField()),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('book', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='reading_positions',
                    to='books.book',
                )),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='reading_positions',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'Reading Position',
                'verbose_name_plural': 'Reading Positions',
                'ordering': ['-updated_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='readingposition',
            constraint=models.UniqueConstraint(
                fields=['user', 'book'],
                name='unique_reading_position_per_user_book',
            ),
        ),
        migrations.AddIndex(
            model_name='readingposition',
            index=models.Index(fields=['user', 'book'], name='readingpos_user_book_idx'),
        ),
    ]
