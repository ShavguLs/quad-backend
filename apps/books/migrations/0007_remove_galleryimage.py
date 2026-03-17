# Generated migration to remove GalleryImage model and migrate data to cover_image

from django.db import migrations, models


def migrate_gallery_to_cover(apps, schema_editor):
    """
    Migrate gallery images to cover images.
    
    For books that have gallery images but no cover image,
    use the first gallery image as the cover image.
    """
    Book = apps.get_model('books', 'Book')
    GalleryImage = apps.get_model('books', 'GalleryImage')
    
    # Find books with gallery images but no cover
    books_with_gallery_no_cover = Book.objects.filter(
        cover_image__isnull=True
    ).exclude(gallery__isnull=True)
    
    for book in books_with_gallery_no_cover:
        # Get the first gallery image (lowest order, then earliest created)
        first_gallery = book.gallery.order_by('order', 'created_at').first()
        if first_gallery:
            # Copy the image to cover_image
            book.cover_image = first_gallery.image
            book.save(update_fields=['cover_image'])


def reverse_migration(apps, schema_editor):
    """
    Reverse migration - no-op since we can't restore gallery from cover.
    Gallery images are lost in reverse direction.
    """
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('books', '0006_book_is_visible'),
    ]

    operations = [
        # First, run data migration to preserve gallery images as covers
        migrations.RunPython(
            migrate_gallery_to_cover,
            reverse_migration
        ),
        # Then delete the GalleryImage model
        migrations.DeleteModel(
            name='GalleryImage',
        ),
    ]
