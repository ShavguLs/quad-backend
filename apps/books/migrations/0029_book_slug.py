from django.db import migrations, models


def _build_book_slug(author: str, title: str, max_length: int = 255) -> str:
    import re
    import unicodedata

    allowed_pattern = re.compile(r'[^a-z0-9\u10d0-\u10ff-]+')
    separator_pattern = re.compile(r'[\s\-_+/|]+')
    dash_pattern = re.compile(r'-{2,}')

    parts = [part.strip() for part in (author, title) if part and part.strip()]
    raw_value = ' '.join(parts)
    if not raw_value:
        return 'book'

    normalized_value = unicodedata.normalize('NFKC', raw_value).lower()
    slug = separator_pattern.sub('-', normalized_value)
    slug = allowed_pattern.sub('', slug)
    slug = dash_pattern.sub('-', slug).strip('-')
    
    # Cap to max_length and strip trailing dashes
    if len(slug) > max_length:
        slug = slug[:max_length].rstrip('-')
    
    return slug or 'book'


def backfill_book_slugs(apps, schema_editor):
    Book = apps.get_model('books', 'Book')

    for book in Book.objects.all().only('id', 'author', 'title').iterator():
        Book.objects.filter(pk=book.pk).update(
            slug=_build_book_slug(book.author, book.title),
        )


class Migration(migrations.Migration):

    dependencies = [
        ('books', '0028_readingposition'),
    ]

    operations = [
        migrations.AddField(
            model_name='book',
            name='slug',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.RunPython(backfill_book_slugs, migrations.RunPython.noop),
    ]
