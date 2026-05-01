"""Book models for the books app."""

import re
import unicodedata
import uuid
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

# Import theme mixin
from apps.books.models.book_theme import BookThemeMixin

BOOK_SLUG_ALLOWED_PATTERN = re.compile(r"[^a-z0-9\u10d0-\u10ff-]+")
BOOK_SLUG_SEPARATOR_PATTERN = re.compile(r"[\s\-_+/|]+")
BOOK_SLUG_DASH_PATTERN = re.compile(r"-{2,}")


def build_book_slug(author: str, title: str, max_length: int = 255) -> str:
    parts = [part.strip() for part in (author, title) if part and part.strip()]
    raw_value = " ".join(parts)

    if not raw_value:
        return "book"

    normalized_value = unicodedata.normalize("NFKC", raw_value).lower()
    slug = BOOK_SLUG_SEPARATOR_PATTERN.sub("-", normalized_value)
    slug = BOOK_SLUG_ALLOWED_PATTERN.sub("", slug)
    slug = BOOK_SLUG_DASH_PATTERN.sub("-", slug).strip("-")

    # Cap to max_length and strip trailing dashes
    if len(slug) > max_length:
        slug = slug[:max_length].rstrip("-")

    return slug or "book"


class Book(BookThemeMixin, models.Model):
    """Book model with ownership, status tracking, and metadata."""

    ACCESS_TYPE_EDUCATIONAL = "educational"
    ACCESS_TYPE_SCIENTIFIC = "scientific"
    ACCESS_TYPE_CHOICES = [
        (ACCESS_TYPE_EDUCATIONAL, "სასწავლო"),
        (ACCESS_TYPE_SCIENTIFIC, "სამეცნიერო"),
    ]

    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("published", "Published"),
    ]

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="books",
    )
    title = models.CharField(max_length=255)
    author = models.CharField(max_length=255)
    slug = models.CharField(max_length=255, blank=True, default="")
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="draft",
    )
    cover_image = models.ImageField(
        upload_to="books/covers/%Y/%m/",
        blank=True,
        null=True,
    )
    # Commerce fields
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        validators=[MinValueValidator(0)],
        help_text="Price in GBP",
    )
    access_type = models.CharField(
        max_length=20,
        choices=ACCESS_TYPE_CHOICES,
        default=ACCESS_TYPE_EDUCATIONAL,
        help_text="Book access and download policy",
    )
    # Analytics fields
    view_count = models.PositiveIntegerField(default=0)
    follower_count = models.PositiveIntegerField(default=0)
    revenue_total = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        validators=[MinValueValidator(0)],
        help_text="Total revenue in GBP",
    )
    total_pages = models.PositiveIntegerField(
        default=0, help_text="Total number of pages (set after file conversion)"
    )
    category = models.CharField(max_length=100, blank=True)
    is_featured = models.BooleanField(default=False)
    is_visible = models.BooleanField(
        default=True,
        help_text="Controls whether the book is visible in public endpoints.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # Theme data stored as JSON for per-book theming
    theme_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Theme configuration for book display (paper_background, font_family)",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["owner", "status"], name="books_owner_status_idx"),
            models.Index(
                fields=["status", "created_at"], name="books_status_created_idx"
            ),
        ]

    def __str__(self) -> str:
        return self.title

    @property
    def public_path_segment(self) -> str:
        slug = self.slug or build_book_slug(self.author, self.title)
        return f"{slug}--{self.pk}" if self.pk else slug

    def save(self, *args, **kwargs):
        """Override save to delete old cover image when a new one is uploaded."""
        self.slug = build_book_slug(self.author, self.title)

        if self.pk:
            # Check if this is an update and cover_image changed
            try:
                old_instance = Book.objects.get(pk=self.pk)
                if (
                    old_instance.cover_image
                    and old_instance.cover_image != self.cover_image
                ):
                    # Delete old cover image file
                    old_instance.cover_image.delete(save=False)
            except Book.DoesNotExist:
                pass
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Override delete to clean up associated files from storage."""
        # Delete cover image if it exists
        if self.cover_image:
            self.cover_image.delete(save=False)

        super().delete(*args, **kwargs)

    def can_user_access(self, user):
        """Check if user can access this book's content (owner or purchaser)."""
        from django.utils import timezone
        from apps.orders.models import Order

        if self.owner == user:
            return True
        order = Order.objects.filter(
            book=self, buyer=user, status=Order.STATUS_COMPLETED
        ).first()
        if order is None:
            return False
        if order.expires_at is not None and order.expires_at <= timezone.now():
            return False
        return True


class BookView(models.Model):
    """Track daily book views per user."""

    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="view_events")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="book_views"
    )
    view_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["book", "user", "view_date"], name="books_view_unique_per_day"
            )
        ]

    def __str__(self) -> str:
        return f"{self.book.title} view by {self.user_id} on {self.view_date}"


class BookFollow(models.Model):
    """Track follows for a book."""

    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="followers")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="followed_books",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["book", "user"], name="books_follow_unique")
        ]

    def __str__(self) -> str:
        return f"{self.book.title} followed by {self.user_id}"


class PageNote(models.Model):
    """User-owned notes for specific book pages."""

    book = models.ForeignKey(
        Book,
        on_delete=models.CASCADE,
        related_name="page_notes",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="page_notes",
    )
    page_number = models.PositiveIntegerField()
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["page_number", "created_at"]
        unique_together = ["book", "user", "page_number"]

    def __str__(self) -> str:
        return f"Note by {self.user.username} on {self.book.title} p{self.page_number}"


class Chapter(models.Model):
    """Chapter model for book structure.

    Supports hierarchical organization of book content with
    position-based ordering for chapter management.
    """

    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="chapters")
    title = models.CharField(max_length=255)
    position = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(
                fields=["book", "position"], name="unique_chapter_position_per_book"
            )
        ]

    def __str__(self) -> str:
        return f"{self.position}. {self.title}"


__all__ = [
    # Models
    "Book",
    "BookView",
    "BookFollow",
    "PageNote",
    "Chapter",
]
