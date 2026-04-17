"""Book models for the books app.

This module provides all book-related models including:
- Book: Main book entity with metadata and status
- BookContent: Structured JSONB-based content storage
- ContentVersion: Snapshot-based versioning for content history
- Block types: Type definitions for structured content blocks
"""

import re
import unicodedata
import uuid
from typing import Optional

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q, Value
from django.contrib.postgres.indexes import GinIndex

from apps.books.storage import PrivateMediaStorage

# Import theme mixin
from apps.books.models.book_theme import BookThemeMixin

# Import content block types for re-export
from apps.books.models.content_blocks import (
    BlockType,
    BlockPosition,
    BlockFormatting,
    BlockMetadata,
    ContentBlock,
    ParagraphBlock,
    HeadingBlock,
    ImageBlock,
    ListItemBlock,
    PageBreakBlock,
    block_from_extraction,
)


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

    RENDER_PREFERENCE_TEXT = "text"
    RENDER_PREFERENCE_EXACT_VISUAL = "exact_visual"
    READER_RENDER_PREFERENCE_CHOICES = [
        (RENDER_PREFERENCE_TEXT, "Text"),
        (RENDER_PREFERENCE_EXACT_VISUAL, "Exact Visual"),
    ]

    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("published", "Published"),
    ]

    INTAKE_STATUS_CHOICES = [
        ("queued", "Queued"),
        ("processing", "Processing"),
        ("ready", "Ready"),
        ("failed", "Failed"),
    ]

    PUBLISH_STATUS_CHOICES = [
        ("idle", "Idle"),
        ("publishing", "Publishing"),
        ("published", "Published"),
        ("failed", "Failed"),
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
    intake_status = models.CharField(
        max_length=20,
        choices=INTAKE_STATUS_CHOICES,
        default="queued",
        help_text="Canonical draft intake processing state.",
    )
    intake_attempt = models.PositiveIntegerField(default=0)
    intake_error = models.TextField(blank=True, null=True)
    intake_started_at = models.DateTimeField(blank=True, null=True)
    intake_finished_at = models.DateTimeField(blank=True, null=True)
    intake_updated_at = models.DateTimeField(blank=True, null=True)
    intake_diagnostics = models.JSONField(
        default=list,
        blank=True,
        help_text="Diagnostic information about unsupported style fragments detected during import",
    )
    # Text extraction fields (new for v1.9)
    extraction_status = models.CharField(
        max_length=20,
        choices=[
            ("pending", "Pending"),
            ("processing", "Processing"),
            ("completed", "Completed"),
            ("partial", "Partial"),
            ("failed", "Failed"),
        ],
        default="pending",
        help_text="Text extraction status for new reader experience",
    )
    extraction_error = models.TextField(blank=True, null=True)
    extraction_started_at = models.DateTimeField(blank=True, null=True)
    extraction_finished_at = models.DateTimeField(blank=True, null=True)
    extraction_updated_at = models.DateTimeField(blank=True, null=True)
    extraction_pages_processed = models.PositiveIntegerField(default=0)
    extraction_diagnostics = models.JSONField(
        default=list, blank=True, help_text="Text extraction warnings and diagnostics"
    )
    reader_render_preference = models.CharField(
        max_length=20,
        choices=READER_RENDER_PREFERENCE_CHOICES,
        default=RENDER_PREFERENCE_TEXT,
        help_text="Preferred reader rendering mode for uploaded PDFs",
    )
    publish_status = models.CharField(
        max_length=20,
        choices=PUBLISH_STATUS_CHOICES,
        default="idle",
        help_text="Async publishing status",
    )
    publish_error = models.TextField(blank=True, null=True)
    publish_started_at = models.DateTimeField(blank=True, null=True)
    publish_finished_at = models.DateTimeField(blank=True, null=True)
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
            models.Index(
                fields=["owner", "status", "intake_status"],
                name="books_owner_status_intake_idx",
            ),
            models.Index(
                fields=["status", "intake_status", "intake_updated_at"],
                name="books_status_intake_upd_idx",
            ),
            # New index for extraction status queries
            models.Index(
                fields=["extraction_status", "extraction_updated_at"],
                name="books_ext_status_upd_idx",
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

        # Remove draft elements first so protected image-asset relations
        # do not block book deletion.
        self.draft_elements.all().delete()

        # Delete draft image files from storage before model removal.
        for draft_asset in self.draft_image_assets.all():
            if draft_asset.image:
                draft_asset.image.delete(save=False)

        # Delete all associated files from storage before deleting the book
        for book_file in self.files.all():
            book_file.file.delete(save=False)
        super().delete(*args, **kwargs)

    def can_user_access(self, user):
        """Check if user can access this book's content (owner or purchaser)."""
        from apps.orders.models import Order

        if self.owner == user:
            return True
        if Order.objects.filter(
            book=self, buyer=user, status=Order.STATUS_COMPLETED
        ).exists():
            return True
        return False


class BookFile(models.Model):
    """File attachment model for books (PDF/EPUB)."""

    book = models.ForeignKey(
        Book,
        on_delete=models.CASCADE,
        related_name="files",
    )
    file = models.FileField(
        storage=PrivateMediaStorage(),
        upload_to="books/files/%Y/%m/",
    )
    original_filename = models.CharField(max_length=255)
    file_size = models.PositiveIntegerField()
    mime_type = models.CharField(max_length=100)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]
        verbose_name = "Book File"
        verbose_name_plural = "Book Files"

    def __str__(self) -> str:
        return f"{self.original_filename} ({self.book.title})"


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


class SavedPage(models.Model):
    """User-bookmarked pages — synced across devices, max 10 per book."""

    MAX_PER_BOOK = 10

    book = models.ForeignKey(
        Book,
        on_delete=models.CASCADE,
        related_name="saved_pages",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="saved_pages",
    )
    page_number = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["page_number"]
        verbose_name = "Saved Page"
        verbose_name_plural = "Saved Pages"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "book", "page_number"],
                name="unique_saved_page_per_user_book",
            ),
            models.CheckConstraint(
                condition=models.Q(page_number__gte=1),
                name="saved_page_number_gte_1",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "book"], name="savedpage_user_book_idx"),
        ]

    def __str__(self) -> str:
        return f"Saved p{self.page_number} of '{self.book.title}' by {self.user_id}"


class ReadingPosition(models.Model):
    """User's current reading position in a book — one per user per book.

    Persisted to the backend so it syncs across devices. Upserted on every
    mark action; deleted when the user explicitly clears their position.
    """

    book = models.ForeignKey(
        Book,
        on_delete=models.CASCADE,
        related_name="reading_positions",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reading_positions",
    )
    page_number = models.PositiveIntegerField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        verbose_name = "Reading Position"
        verbose_name_plural = "Reading Positions"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "book"],
                name="unique_reading_position_per_user_book",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "book"], name="readingpos_user_book_idx"),
        ]

    def __str__(self) -> str:
        return f"Position p{self.page_number} in '{self.book.title}' by {self.user_id}"


class DraftImageAsset(models.Model):
    """Private image assets uploaded for draft editor elements."""

    book = models.ForeignKey(
        Book,
        on_delete=models.CASCADE,
        related_name="draft_image_assets",
    )
    image = models.ImageField(
        storage=PrivateMediaStorage(),
        upload_to="draft_elements/images/%Y/%m/%d/",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Draft image asset {self.pk} for book {self.book_id}"


class BookAuditLog(models.Model):
    """Audit trail for book lifecycle actions (upload, edit, publish)."""

    ACTION_UPLOAD = "upload"
    ACTION_EDIT = "edit"
    ACTION_PUBLISH = "publish"
    ACTION_CHOICES = [
        (ACTION_UPLOAD, "Upload"),
        (ACTION_EDIT, "Edit"),
        (ACTION_PUBLISH, "Publish"),
    ]

    book = models.ForeignKey(
        Book,
        on_delete=models.CASCADE,
        related_name="audit_logs",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="book_audit_logs",
    )
    action = models.CharField(
        max_length=20,
        choices=ACTION_CHOICES,
    )
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    details = models.JSONField(
        default=dict,
        blank=True,
        help_text="Action-specific details: page_number/version for edits, attempt for uploads, page_count for publish",
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["book", "timestamp"], name="audit_book_time_idx"),
            models.Index(fields=["user", "timestamp"], name="audit_user_time_idx"),
            models.Index(fields=["action", "timestamp"], name="audit_action_time_idx"),
        ]

    def __str__(self) -> str:
        user_str = self.user.email if self.user else "Unknown"
        return f"{self.action} on '{self.book.title}' by {user_str} at {self.timestamp}"


class DraftElement(models.Model):
    """Page-scoped draft overlay element persisted with normalized geometry."""

    TYPE_TEXT = "text"
    TYPE_IMAGE = "image"
    ELEMENT_TYPE_CHOICES = [
        (TYPE_TEXT, "Text"),
        (TYPE_IMAGE, "Image"),
    ]

    book = models.ForeignKey(
        Book,
        on_delete=models.CASCADE,
        related_name="draft_elements",
    )
    element_type = models.CharField(max_length=16, choices=ELEMENT_TYPE_CHOICES)
    page_number = models.PositiveIntegerField()
    x = models.DecimalField(max_digits=6, decimal_places=4)
    y = models.DecimalField(max_digits=6, decimal_places=4)
    width = models.DecimalField(max_digits=6, decimal_places=4)
    height = models.DecimalField(max_digits=6, decimal_places=4)
    z_index = models.IntegerField(default=0)
    text_content = models.TextField(blank=True, null=True)
    image_asset = models.ForeignKey(
        DraftImageAsset,
        on_delete=models.PROTECT,
        related_name="elements",
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["page_number", "z_index", "id"]
        indexes = [
            models.Index(
                fields=["book", "page_number", "z_index"],
                name="draft_el_book_page_z_idx",
            ),
            models.Index(
                fields=["book", "element_type"], name="draft_el_book_type_idx"
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(x__gte=0) & Q(x__lte=1),
                name="draft_el_x_0_1",
            ),
            models.CheckConstraint(
                condition=Q(y__gte=0) & Q(y__lte=1),
                name="draft_el_y_0_1",
            ),
            models.CheckConstraint(
                condition=Q(width__gt=0) & Q(width__lte=1),
                name="draft_el_w_gt0_1",
            ),
            models.CheckConstraint(
                condition=Q(height__gt=0) & Q(height__lte=1),
                name="draft_el_h_gt0_1",
            ),
            models.CheckConstraint(
                condition=Q(x__lte=Value(1) - F("width")),
                name="draft_el_x_plus_w_lte_1",
            ),
            models.CheckConstraint(
                condition=Q(y__lte=Value(1) - F("height")),
                name="draft_el_y_plus_h_lte_1",
            ),
            models.CheckConstraint(
                condition=(
                    (
                        Q(element_type="text")
                        & Q(text_content__isnull=False)
                        & Q(image_asset__isnull=True)
                    )
                    | (
                        Q(element_type="image")
                        & Q(text_content__isnull=True)
                        & Q(image_asset__isnull=False)
                    )
                ),
                name="draft_el_payload_by_type",
            ),
            models.CheckConstraint(
                condition=Q(page_number__gte=1),
                name="draft_el_page_gte_1",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"Draft element {self.pk} ({self.element_type}) on page {self.page_number}"
        )


class ExtractedImage(models.Model):
    """Images extracted from PDFs during intake processing."""

    book = models.ForeignKey(
        Book,
        on_delete=models.CASCADE,
        related_name="extracted_images",
    )
    page_number = models.PositiveIntegerField(
        help_text="Page number where image appears (1-based)"
    )
    xref = models.PositiveIntegerField(help_text="PDF xref identifier for the image")
    image = models.ImageField(
        storage=PrivateMediaStorage(),
        upload_to="extracted_images/%Y/%m/%d/",
        help_text="Extracted image file",
    )
    original_ext = models.CharField(
        max_length=10, help_text="Original image format (png, jpeg, etc.)"
    )
    width = models.PositiveIntegerField(help_text="Image width in pixels")
    height = models.PositiveIntegerField(help_text="Image height in pixels")
    bbox_x0 = models.FloatField(
        null=True, blank=True, help_text="Position on page: left coordinate"
    )
    bbox_y0 = models.FloatField(
        null=True, blank=True, help_text="Position on page: top coordinate"
    )
    bbox_x1 = models.FloatField(
        null=True, blank=True, help_text="Position on page: right coordinate"
    )
    bbox_y1 = models.FloatField(
        null=True, blank=True, help_text="Position on page: bottom coordinate"
    )
    has_transparency = models.BooleanField(
        default=False, help_text="Whether image had mask/transparency applied"
    )
    colorspace = models.PositiveIntegerField(
        default=0, help_text="PDF colorspace identifier"
    )
    file_size = models.PositiveIntegerField(help_text="Image file size in bytes")
    extracted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["page_number", "xref"]
        verbose_name = "Extracted Image"
        verbose_name_plural = "Extracted Images"
        constraints = [
            models.UniqueConstraint(
                fields=["book", "page_number", "xref"],
                name="unique_image_per_page_xref",
            )
        ]
        indexes = [
            models.Index(fields=["book", "page_number"], name="extimg_book_page_idx"),
        ]

    def __str__(self) -> str:
        return f"Image {self.xref} on page {self.page_number} of {self.book.title}"

    @property
    def bbox(self) -> Optional[tuple]:
        """Get bounding box as tuple or None."""
        if all(
            v is not None
            for v in [self.bbox_x0, self.bbox_y0, self.bbox_x1, self.bbox_y1]
        ):
            return (self.bbox_x0, self.bbox_y0, self.bbox_x1, self.bbox_y1)
        return None


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


class BookContent(models.Model):
    """Stores structured content as JSONB blocks per page.

    Replaces BookPage.content HTML field with structured JSONB-based
    content model that supports block-level metadata, formatting
    preservation, and efficient querying for 500+ page books.
    """

    BLOCK_TYPES = [
        ("paragraph", "Paragraph"),
        ("heading", "Heading"),
        ("list_item", "List Item"),
        ("image", "Image"),
        ("page_break", "Page Break"),
    ]

    book = models.ForeignKey(
        Book, on_delete=models.CASCADE, related_name="content_pages"
    )
    page_number = models.PositiveIntegerField()

    # JSONB storage for content blocks
    blocks = models.JSONField(
        default=list,
        help_text="List of content blocks with type, content, and metadata",
    )

    # Optimistic locking
    version = models.PositiveIntegerField(default=1)

    # Metadata (auto-calculated on save)
    block_count = models.PositiveIntegerField(default=0)
    word_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["page_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["book", "page_number"], name="unique_book_page_content"
            )
        ]
        indexes = [
            GinIndex(fields=["blocks"], name="book_content_blocks_gin"),
            models.Index(fields=["book", "page_number"]),
            models.Index(fields=["book", "updated_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.book.title} - Page {self.page_number}"

    @classmethod
    def exists_for_book(cls, book_id: int) -> bool:
        """Check if BookContent records exist for a book.

        Args:
            book_id: Book ID to check

        Returns:
            True if any content pages exist for the book
        """
        return cls.objects.filter(book_id=book_id).exists()

    @classmethod
    def get_stats_for_book(cls, book_id: int) -> dict:
        """Get content statistics for a book.

        Args:
            book_id: Book ID to get stats for

        Returns:
            Dict with page_count, block_count, word_count
        """
        from django.db.models import Sum

        stats = cls.objects.filter(book_id=book_id).aggregate(
            page_count=models.Count("id"),
            block_count=Sum("block_count"),
            word_count=Sum("word_count"),
        )

        return {
            "page_count": stats["page_count"] or 0,
            "block_count": stats["block_count"] or 0,
            "word_count": stats["word_count"] or 0,
        }

    def save(self, *args, **kwargs):
        """Auto-calculate metadata before saving."""
        self.block_count = len(self.blocks)
        self.word_count = self._calculate_word_count()
        super().save(*args, **kwargs)

    def _calculate_word_count(self) -> int:
        """Calculate word count from text blocks."""
        word_count = 0
        for block in self.blocks:
            if block.get("type") == "image":
                continue
            text = block.get("text", "")
            if text:
                word_count += len(text.split())
        return word_count


# Import ContentVersion after BookContent is defined (to avoid circular imports)
from apps.books.models.content_version import ContentVersion

__all__ = [
    # Models
    "Book",
    "BookFile",
    "BookView",
    "BookFollow",
    "PageNote",
    "SavedPage",
    "ReadingPosition",
    "DraftImageAsset",
    "BookAuditLog",
    "DraftElement",
    "ExtractedImage",
    "BookContent",
    "ContentVersion",
    "Chapter",
    # Block types
    "BlockType",
    "BlockPosition",
    "BlockFormatting",
    "BlockMetadata",
    "ContentBlock",
    "ParagraphBlock",
    "HeadingBlock",
    "ImageBlock",
    "ListItemBlock",
    "PageBreakBlock",
    "block_from_extraction",
]
