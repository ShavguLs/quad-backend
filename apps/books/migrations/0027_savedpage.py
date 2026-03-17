from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('books', '0026_delete_readingprogress'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='SavedPage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('page_number', models.PositiveIntegerField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('book', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='saved_pages',
                    to='books.book',
                )),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='saved_pages',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'ordering': ['page_number'],
                'verbose_name': 'Saved Page',
                'verbose_name_plural': 'Saved Pages',
            },
        ),
        migrations.AddConstraint(
            model_name='savedpage',
            constraint=models.UniqueConstraint(
                fields=['user', 'book', 'page_number'],
                name='unique_saved_page_per_user_book',
            ),
        ),
        migrations.AddConstraint(
            model_name='savedpage',
            constraint=models.CheckConstraint(
                condition=models.Q(page_number__gte=1),
                name='saved_page_number_gte_1',
            ),
        ),
        migrations.AddIndex(
            model_name='savedpage',
            index=models.Index(fields=['user', 'book'], name='savedpage_user_book_idx'),
        ),
    ]
