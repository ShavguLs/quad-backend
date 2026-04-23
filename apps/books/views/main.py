"""
Views for the books app.
"""

import base64
import html
import logging
import mimetypes
import re

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.response import Response

from apps.books.models import (
    Book,
    BookContent,
    BookFile,
    BookFollow,
    BookView,
    PageNote,
    SavedPage,
    ReadingPosition,
)
from apps.books.permissions import IsOwnerOrReadOnly
from apps.books.audit import service as audit_service
from apps.books.storage import PrivateMediaStorage
from apps.books.serializers import (
    BookAuditLogSerializer,
    BookFileSerializer,
    BookSerializer,
    PageNoteSerializer,
    SavedPageSerializer,
    ReadingPositionSerializer,
)
from apps.orders.models import Order
from apps.books.publish import (
    DraftChangedError,
    PublishError,
)
from apps.books.validators import validate_file_type

logger = logging.getLogger(__name__)


class BookViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Book model.

    Provides CRUD operations with the following visibility rules:
    - Anonymous users see only published books
    - Authenticated users see published books plus their own drafts
    - Only book owners can update or delete their books
    """

    queryset = Book.objects.all()
    serializer_class = BookSerializer
    permission_classes = [IsAuthenticatedOrReadOnly, IsOwnerOrReadOnly]
    READER_CACHE_TIMEOUT = max(getattr(settings, "CACHE_DEFAULT_TIMEOUT", 300), 60)
    PRIVATE_STORAGE_PREFIXES = (
        "books/files/",
        "draft_elements/images/",
        "extracted_images/",
    )

    def get_queryset(self):
        """
        Filter queryset based on user authentication status.

        - Anonymous: only published books
        - Authenticated: published books + own drafts
        """
        queryset = Book.objects.select_related("owner")

        user = self.request.user
        if user.is_authenticated and user.is_staff:
            return queryset
        if user.is_authenticated:
            # Show user's own books regardless of visibility/status, plus public catalog.
            return queryset.filter(
                Q(owner=user) | Q(status="published", is_visible=True)
            )
        else:
            # Anonymous users only see published books
            return queryset.filter(status="published", is_visible=True)

    def perform_create(self, serializer):
        """Assign the current user as the book owner on creation."""
        serializer.save(owner=self.request.user)

    @staticmethod
    def _get_client_ip(request):
        forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR")

    @staticmethod
    def _is_owner(book: Book, user) -> bool:
        return bool(user and user.is_authenticated and book.owner_id == user.id)

    @staticmethod
    def _has_completed_purchase(book: Book, user) -> bool:
        if not user or not user.is_authenticated:
            return False
        order = Order.objects.filter(
            buyer=user, book=book, status=Order.STATUS_COMPLETED
        ).first()
        if order is None:
            return False
        if order.expires_at is not None and order.expires_at <= timezone.now():
            return False
        return True

    def _get_expired_order(self, book: Book, user) -> Order | None:
        """Get the expired order if user has a completed but expired purchase."""
        if not user or not user.is_authenticated:
            return None
        order = Order.objects.filter(
            buyer=user, book=book, status=Order.STATUS_COMPLETED
        ).first()
        if order and order.expires_at is not None and order.expires_at <= timezone.now():
            return order
        return None

    def _has_full_reader_access(self, book: Book, user) -> bool:
        return self._is_owner(book, user) or self._has_completed_purchase(book, user)

    @staticmethod
    def _reader_cache_version(book: Book) -> str:
        version_source = book.updated_at or timezone.now()
        extraction_source = book.extraction_updated_at or version_source
        return f"{version_source.isoformat()}:{extraction_source.isoformat()}"

    @staticmethod
    def _reader_access_bucket(is_owner: bool, full_access: bool) -> str:
        if is_owner:
            return "owner"
        return "full" if full_access else "denied"

    def _resolve_reader_html(self, blocks: list[dict]) -> tuple[str, str, str | None]:
        """Resolve a page render payload from stored blocks."""
        # Prefer explicit render payload written by extraction.
        for block in blocks:
            metadata = (block or {}).get("metadata") or {}
            render_html = metadata.get("render_html")
            if render_html:
                return (
                    metadata.get("render_mode", "html"),
                    self._redact_private_urls_in_html(render_html),
                    metadata.get("fallback_image_path"),
                )

        # Fallback: synthesize basic HTML from structured blocks.
        html_parts: list[str] = []
        for block in blocks:
            block_type = block.get("type")
            text_value = block.get("text") or block.get("content") or ""
            text_html = html.escape(str(text_value))
            formatting = block.get("formatting") or {}
            styles: list[str] = []

            alignment = formatting.get("alignment")
            if (
                alignment in {"left", "center", "right", "justify"}
                and alignment != "left"
            ):
                styles.append(f"text-align:{alignment}")
            font_size = formatting.get("font_size")
            if isinstance(font_size, (int, float)) and font_size > 0:
                styles.append(f"font-size:{float(font_size):.1f}px")
            font_family = formatting.get("font_family")
            if font_family:
                styles.append(f"font-family:{font_family}")
            color = formatting.get("color")
            if color:
                styles.append(f"color:{color}")
            line_height = formatting.get("line_height")
            if isinstance(line_height, (int, float)) and line_height > 0:
                styles.append(f"line-height:{float(line_height):.2f}")

            if formatting.get("bold"):
                text_html = f"<strong>{text_html}</strong>"
            if formatting.get("italic"):
                text_html = f"<em>{text_html}</em>"

            style_attr = f' style="{";".join(styles)}"' if styles else ""

            if block_type == "heading":
                level = 1
                raw_level = block.get("level") or (block.get("attrs") or {}).get(
                    "level"
                )
                if isinstance(raw_level, int) and 1 <= raw_level <= 6:
                    level = raw_level
                html_parts.append(f"<h{level}{style_attr}>{text_html}</h{level}>")
            elif block_type == "list_item":
                list_type = (block.get("attrs") or {}).get("list_type", "unordered")
                marker = "•"
                if list_type == "ordered":
                    marker = f"{(block.get('attrs') or {}).get('list_index', 1)}."
                html_parts.append(f"<p{style_attr}>{marker} {text_html}</p>")
            else:
                html_parts.append(f"<p{style_attr}>{text_html}</p>")

        if not html_parts:
            return ("html", "<p></p>", None)
        return ("html", self._redact_private_urls_in_html("\n".join(html_parts)), None)

    @classmethod
    def _contains_private_storage_prefix(cls, value: str) -> bool:
        lowered = value.lower()
        return any(prefix in lowered for prefix in cls.PRIVATE_STORAGE_PREFIXES)

    @classmethod
    def _looks_like_storage_reference(cls, value: str) -> bool:
        normalized = value.strip().lower()
        if not normalized:
            return False
        starts_like_ref = normalized.startswith(("http://", "https://", "/"))
        return starts_like_ref or any(
            normalized.startswith(prefix) for prefix in cls.PRIVATE_STORAGE_PREFIXES
        )

    @classmethod
    def _redact_private_urls_in_html(cls, html_value: str) -> str:
        if not isinstance(html_value, str) or not cls._contains_private_storage_prefix(
            html_value
        ):
            return html_value

        absolute_url_pattern = re.compile(
            r"https?://[^\s\"'<>]*(?:books/files/|draft_elements/images/|extracted_images/)[^\s\"'<>]*",
            flags=re.IGNORECASE,
        )
        relative_path_pattern = re.compile(
            r"(?:/)?(?:books/files|draft_elements/images|extracted_images)/[^\s\"'<>]*",
            flags=re.IGNORECASE,
        )
        redacted = absolute_url_pattern.sub("#", html_value)
        return relative_path_pattern.sub("#", redacted)

    @classmethod
    def _sanitize_private_storage_references(cls, value):
        if isinstance(value, dict):
            return {
                key: cls._sanitize_private_storage_references(nested_value)
                for key, nested_value in value.items()
            }

        if isinstance(value, list):
            return [cls._sanitize_private_storage_references(item) for item in value]

        if isinstance(value, str) and cls._contains_private_storage_prefix(value):
            if cls._looks_like_storage_reference(value):
                return None
            return cls._redact_private_urls_in_html(value)

        return value

    @staticmethod
    def _extract_page_dimensions(blocks: list[dict]) -> tuple[float, float] | None:
        """Extract per-page dimensions from stored reader metadata."""
        for block in blocks or []:
            metadata = (block or {}).get("metadata") or {}
            raw_width = metadata.get("page_width")
            raw_height = metadata.get("page_height")
            try:
                page_width = float(raw_width)
                page_height = float(raw_height)
            except (TypeError, ValueError):
                continue

            if page_width > 0 and page_height > 0:
                return (page_width, page_height)

        return None

    def _resolve_reader_page_frame(self, book: Book) -> tuple[float, float]:
        """
        Choose a single frame for all pages using the tallest extracted page.

        The frame width is the width associated with the tallest page found
        across all BookContent records for this book.  When multiple pages
        share the same maximum height, the widest of those pages is used.
        If no valid dimensions exist the method falls back to (595.0, 842.0)
        (ISO A4 in PDF points).

        Returns (page_frame_width, page_frame_height) in PDF point units.
        """
        default_width = 595.0
        default_height = 842.0
        max_height = 0.0
        width_for_max_height = 0.0

        pages = BookContent.objects.filter(book=book).only("blocks")
        for page in pages:
            dimensions = self._extract_page_dimensions(page.blocks or [])
            if not dimensions:
                continue

            page_width, page_height = dimensions
            if page_height > max_height:
                max_height = page_height
                width_for_max_height = page_width
            elif page_height == max_height and page_width > width_for_max_height:
                width_for_max_height = page_width

        if max_height <= 0 or width_for_max_height <= 0:
            return (default_width, default_height)

        return (width_for_max_height, max_height)

    @staticmethod
    def _fallback_image_data_uri(fallback_image_path: str | None) -> str | None:
        if not fallback_image_path:
            return None
        storage = PrivateMediaStorage()
        try:
            with storage.open(fallback_image_path, "rb") as fh:
                raw = fh.read()
            mime, _ = mimetypes.guess_type(fallback_image_path)
            mime = mime or "image/jpeg"
            return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
        except Exception:
            logger.exception(
                "Failed to load fallback image data URI for path: %s",
                fallback_image_path,
            )
            return None

    def _queue_backfill_if_needed(self, book_id: int) -> bool:
        """
        Queue async extraction if content is missing but a source file exists.
        Returns True if extraction is queued or already processing.
        """
        from apps.books.tasks import process_book_upload_task

        with transaction.atomic():
            locked = Book.objects.select_for_update().get(pk=book_id)
            if locked.content_pages.exists():
                return False

            latest_file = locked.files.order_by("-uploaded_at").first()
            if latest_file is None:
                return False

            if locked.extraction_status == "processing":
                return True

            now = timezone.now()
            locked.extraction_status = "processing"
            locked.extraction_error = None
            locked.extraction_started_at = now
            locked.extraction_updated_at = now
            locked.extraction_finished_at = None
            locked.is_visible = False
            locked.save(
                update_fields=[
                    "extraction_status",
                    "extraction_error",
                    "extraction_started_at",
                    "extraction_updated_at",
                    "extraction_finished_at",
                    "is_visible",
                    "updated_at",
                ]
            )

            process_book_upload_task.delay(locked.pk)
            return True

    def retrieve(self, request, *args, **kwargs):
        book = self.get_object()
        if book.status == "published":
            today = timezone.localdate()
            if request.user.is_authenticated:
                _, created = BookView.objects.get_or_create(
                    book=book, user=request.user, view_date=today
                )
                if created:
                    Book.objects.filter(pk=book.pk).update(
                        view_count=F("view_count") + 1
                    )
                    book.refresh_from_db(fields=["view_count"])
            else:
                client_ip = self._get_client_ip(request)
                if client_ip:
                    cache_key = f"book_view:{book.pk}:{client_ip}:{today.isoformat()}"
                    if not cache.get(cache_key):
                        cache.set(cache_key, True, timeout=60 * 60 * 24)
                        Book.objects.filter(pk=book.pk).update(
                            view_count=F("view_count") + 1
                        )
                        book.refresh_from_db(fields=["view_count"])

        serializer = self.get_serializer(book)
        return Response(serializer.data)

    def partial_update(self, request, *args, **kwargs):
        """Handle PATCH requests for partial updates."""
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        """
        Delete a book and all associated files.

        Only the book owner can delete. Associated cover image and
        book files are automatically cleaned up from storage.
        """
        instance = self.get_object()

        # Check ownership (explicit check even with permission classes)
        if instance.owner != request.user:
            return Response(
                {"detail": "Only the book owner can delete this book."},
                status=status.HTTP_403_FORBIDDEN,
            )

        self.perform_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], url_path="upload")
    def upload(self, request, pk=None):
        """
        Upload a source file and queue async extraction for reader content.

        Only the book owner can upload files.
        Validates file type and queues background processing.
        """
        from apps.books.tasks import process_book_upload_task

        book = self.get_object()

        # Check ownership
        if book.owner != request.user:
            return Response(
                {"detail": "Only the book owner can upload files."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if not request.user.can_upload_books:
            return Response(
                {"detail": "You do not have upload privilege."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if book.status != "draft":
            return Response(
                {"detail": "Only draft books can receive uploads."},
                status=status.HTTP_409_CONFLICT,
            )

        # Check file provided
        if "file" not in request.FILES:
            return Response(
                {"detail": "No file provided."}, status=status.HTTP_400_BAD_REQUEST
            )

        uploaded_file = request.FILES["file"]
        render_preference = request.data.get("render_preference")
        valid_render_preferences = {
            Book.RENDER_PREFERENCE_TEXT,
            Book.RENDER_PREFERENCE_EXACT_VISUAL,
        }

        if (
            render_preference is not None
            and render_preference not in valid_render_preferences
        ):
            return Response(
                {
                    "detail": "Invalid render_preference. Allowed values: text, exact_visual."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate file type and size
        try:
            canonical_mime_type = validate_file_type(uploaded_file)
        except ValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        # Store source file and mark processing state atomically; queue the
        # Celery task only after the transaction commits to avoid a race where
        # the worker picks up the task before the DB writes are visible.
        with transaction.atomic():
            book_file = BookFile.objects.create(
                book=book,
                file=uploaded_file,
                original_filename=uploaded_file.name,
                file_size=uploaded_file.size,
                mime_type=canonical_mime_type,
            )

            # Mark processing state and keep book hidden until extraction completes.
            now = timezone.now()
            next_render_preference = (
                render_preference
                if render_preference is not None
                else book.reader_render_preference
            )
            Book.objects.filter(pk=book.pk).update(
                extraction_status="processing",
                extraction_error=None,
                extraction_started_at=now,
                extraction_updated_at=now,
                extraction_finished_at=None,
                reader_render_preference=next_render_preference,
                is_visible=False,
                updated_at=now,
            )

            transaction.on_commit(lambda: process_book_upload_task.delay(book.pk))

        serializer = BookFileSerializer(book_file, context={"request": request})
        return Response(
            {
                "book_id": book.pk,
                "file": serializer.data,
                "extraction_status": "processing",
                "status": "processing",
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="retry-extraction",
        permission_classes=[IsAuthenticated],
    )
    def retry_extraction(self, request, pk=None):
        """Retry extraction for the latest uploaded source file."""
        from apps.books.tasks import process_book_upload_task

        book = self.get_object()
        if book.owner != request.user:
            return Response(
                {"detail": "Only the book owner can retry extraction."},
                status=status.HTTP_403_FORBIDDEN,
            )

        latest_file = book.files.order_by("-uploaded_at").first()
        if latest_file is None:
            return Response(
                {"detail": "No uploaded source file available for retry."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        now = timezone.now()
        Book.objects.filter(pk=book.pk).update(
            extraction_status="processing",
            extraction_error=None,
            extraction_started_at=now,
            extraction_updated_at=now,
            extraction_finished_at=None,
            is_visible=False,
            updated_at=now,
        )
        process_book_upload_task.delay(book.pk)

        return Response(
            {
                "book_id": book.pk,
                "extraction_status": "processing",
                "status": "processing",
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(
        detail=True,
        methods=["get"],
        url_path="read/manifest",
        permission_classes=[IsAuthenticatedOrReadOnly],
    )
    def read_manifest(self, request, pk=None):
        """
        Reader manifest endpoint — requires purchase or ownership.
        Allows unauthenticated preview access (first 10 pages) for published+visible books.
        """
        book = self.get_object()
        is_owner = self._is_owner(book, request.user)

        if not is_owner and (book.status != "published" or not book.is_visible):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        queued_backfill = self._queue_backfill_if_needed(book.pk)
        book.refresh_from_db()
        page_frame_width, page_frame_height = self._resolve_reader_page_frame(book)

        if queued_backfill or book.extraction_status == "processing":
            return Response(
                {
                    "book_id": book.pk,
                    "status": "processing",
                    "extraction_status": book.extraction_status,
                    "total_pages": book.total_pages or 0,
                    "access_mode": "processing",
                    "is_readable": False,
                    "page_frame_width": page_frame_width,
                    "page_frame_height": page_frame_height,
                },
                status=status.HTTP_202_ACCEPTED,
            )

        total_pages = book.content_pages.count() or book.total_pages or 0
        full_access = self._has_full_reader_access(book, request.user)
        expired_order = self._get_expired_order(book, request.user)
        if expired_order is not None:
            return Response(
                {
                    "code": "access_expired",
                    "detail": "Your access to this book has expired. Please renew to continue reading.",
                    "access_mode": "expired",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # Guest preview: allow first 10 pages for published+visible books
        is_preview = not request.user.is_authenticated
        if is_preview:
            preview_pages = min(total_pages, 10)
            access_bucket = f"preview:{preview_pages}"
            manifest_cache_key = f"reader:manifest:book:{book.pk}:access:{access_bucket}:v:{self._reader_cache_version(book)}"

            cached_manifest = cache.get(manifest_cache_key)
            if cached_manifest:
                return Response(cached_manifest)

            manifest_payload = {
                "book_id": book.pk,
                "title": book.title,
                "author": book.author,
                "price": f"₾{book.price}",
                "status": "ready",
                "extraction_status": book.extraction_status,
                "total_pages": total_pages,
                "available_pages": preview_pages,
                "access_mode": "preview",
                "is_readable": preview_pages > 0
                and book.extraction_status in {"completed", "partial"},
                "page_frame_width": page_frame_width,
                "page_frame_height": page_frame_height,
            }

            cache.set(
                manifest_cache_key, manifest_payload, timeout=self.READER_CACHE_TIMEOUT
            )

            return Response(manifest_payload)

        if not is_owner and not full_access:
            return Response(
                {
                    "code": "purchase_required",
                    "detail": "Purchase required to read this book.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        access_mode = "owner" if is_owner else "full"
        access_bucket = self._reader_access_bucket(is_owner, full_access)
        manifest_cache_key = f"reader:manifest:book:{book.pk}:access:{access_bucket}:v:{self._reader_cache_version(book)}"

        cached_manifest = cache.get(manifest_cache_key)
        if cached_manifest:
            return Response(cached_manifest)

        manifest_payload = {
            "book_id": book.pk,
            "title": book.title,
            "author": book.author,
            "price": f"₾{book.price}",
            "status": "ready",
            "extraction_status": book.extraction_status,
            "total_pages": total_pages,
            "available_pages": total_pages,
            "access_mode": access_mode,
            "is_readable": total_pages > 0
            and book.extraction_status in {"completed", "partial"},
            "page_frame_width": page_frame_width,
            "page_frame_height": page_frame_height,
        }

        cache.set(
            manifest_cache_key, manifest_payload, timeout=self.READER_CACHE_TIMEOUT
        )

        return Response(manifest_payload)

    @action(
        detail=True,
        methods=["get"],
        url_path=r"read/pages/(?P<page_number>\d+)",
        permission_classes=[IsAuthenticatedOrReadOnly],
    )
    def read_page(self, request, pk=None, page_number=None):
        """
        Reader page endpoint — requires purchase or ownership.
        Allows unauthenticated preview access (first 10 pages) for published+visible books.
        """
        book = self.get_object()
        is_owner = self._is_owner(book, request.user)

        if not is_owner and (book.status != "published" or not book.is_visible):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        queued_backfill = self._queue_backfill_if_needed(book.pk)
        book.refresh_from_db()
        if queued_backfill or book.extraction_status == "processing":
            return Response(
                {
                    "book_id": book.pk,
                    "status": "processing",
                    "extraction_status": book.extraction_status,
                },
                status=status.HTTP_202_ACCEPTED,
            )

        try:
            page_number = int(page_number)
        except (TypeError, ValueError):
            return Response(
                {"detail": "Invalid page number."}, status=status.HTTP_400_BAD_REQUEST
            )

        if page_number < 1:
            return Response(
                {"detail": "Page number must be >= 1."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Guest preview: allow only first 10 pages
        is_preview = not request.user.is_authenticated
        if is_preview and page_number > 10:
            return Response(
                {
                    "code": "preview_limit_exceeded",
                    "detail": "Preview limited to first 10 pages. Please purchase to continue reading.",
                    "access_mode": "preview",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        full_access = self._has_full_reader_access(book, request.user)
        expired_order = self._get_expired_order(book, request.user)
        if expired_order is not None:
            return Response(
                {
                    "code": "access_expired",
                    "detail": "Your access to this book has expired.",
                    "access_mode": "expired",
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        if not is_owner and not full_access and not is_preview:
            return Response(
                {
                    "code": "purchase_required",
                    "detail": "Purchase required to read this book.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        access_bucket = self._reader_access_bucket(is_owner, full_access)
        if is_preview:
            access_bucket = "preview"

        page = BookContent.objects.filter(book=book, page_number=page_number).first()
        if page is None:
            return Response(
                {"detail": "Page not found."}, status=status.HTTP_404_NOT_FOUND
            )

        page_cache_key = (
            f"reader:page:book:{book.pk}:access:{access_bucket}:page:{page_number}:"
            f"v:{book.updated_at.isoformat()}:{page.version}:{page.updated_at.isoformat()}"
        )
        cached_page = cache.get(page_cache_key)
        if cached_page:
            return Response(cached_page)

        render_mode, render_html, fallback_image_path = self._resolve_reader_html(
            page.blocks or []
        )
        fallback_image_data = self._fallback_image_data_uri(fallback_image_path)
        page_dimensions = self._extract_page_dimensions(page.blocks or [])
        page_width = page_dimensions[0] if page_dimensions else None
        page_height = page_dimensions[1] if page_dimensions else None

        page_payload = {
            "book_id": book.pk,
            "page_number": page.page_number,
            "render_mode": render_mode,
            "render_html": render_html,
            "fallback_image_data": fallback_image_data,
            "blocks": self._sanitize_private_storage_references(page.blocks),
            "version": page.version,
            "page_width": page_width,
            "page_height": page_height,
        }

        cache.set(page_cache_key, page_payload, timeout=self.READER_CACHE_TIMEOUT)

        return Response(page_payload)

    @action(detail=False, methods=["get"], url_path="featured")
    def featured(self, request):
        """
        Return featured published books.

        Filters for books with is_featured=True and status='published'.
        Includes owner data for complete book details.
        Supports pagination via page and page_size query parameters.
        """
        queryset = Book.objects.filter(
            is_featured=True, status="published", is_visible=True
        ).select_related("owner")

        order_param = request.query_params.get("order")
        order_map = {
            "views": "-view_count",
            "followers": "-follower_count",
            "revenue": "-revenue_total",
            "newest": "-created_at",
        }
        if order_param in order_map:
            queryset = queryset.order_by(order_map[order_param])

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(
        detail=True,
        methods=["post"],
        url_path="follow",
        permission_classes=[IsAuthenticated],
    )
    def follow(self, request, pk=None):
        book = self.get_object()
        if book.status != "published":
            return Response(
                {"detail": "Book must be published to follow."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        _, created = BookFollow.objects.get_or_create(book=book, user=request.user)
        if created:
            Book.objects.filter(pk=book.pk).update(
                follower_count=F("follower_count") + 1
            )
            book.refresh_from_db(fields=["follower_count"])

        serializer = self.get_serializer(book)
        return Response(serializer.data)

    @action(
        detail=True,
        methods=["post"],
        url_path="unfollow",
        permission_classes=[IsAuthenticated],
    )
    def unfollow(self, request, pk=None):
        book = self.get_object()
        if book.status != "published":
            return Response(
                {"detail": "Book must be published to unfollow."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        deleted, _ = BookFollow.objects.filter(book=book, user=request.user).delete()
        if deleted:
            Book.objects.filter(pk=book.pk).update(
                follower_count=F("follower_count") - 1
            )
            book.refresh_from_db(fields=["follower_count"])

        serializer = self.get_serializer(book)
        return Response(serializer.data)

    @action(
        detail=True,
        methods=["post"],
        url_path="publish",
        permission_classes=[IsAuthenticated, IsOwnerOrReadOnly],
    )
    def publish(self, request, pk=None):
        """
        Publish a draft book with artifact regeneration (ASYNC).

        Uses Celery task to avoid Heroku's 30-second web request timeout.
        - Returns 202 Accepted immediately
        - Image generation happens in background worker
        - Client should poll for publish status
        """
        from apps.books.tasks import publish_book_task

        try:
            book = self.get_object()

            # Validate book can be published
            if book.status != "draft":
                return Response(
                    {"detail": "Only draft books can be published"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if book.owner != request.user:
                return Response(
                    {"detail": "Only the owner can publish this book"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            # Check if already publishing
            if getattr(book, "publish_status", None) == "publishing":
                return Response(
                    {"detail": "Publish already in progress"},
                    status=status.HTTP_409_CONFLICT,
                )

            # Trigger async publish task
            logger.info(f"Triggering async publish for book {pk}")
            publish_book_task.delay(pk, request.user.pk)

            # Return 202 Accepted - client should poll for status
            return Response(
                {"detail": "Publish started", "status": "publishing", "book_id": pk},
                status=status.HTTP_202_ACCEPTED,
            )

        except PublishError as e:
            # Invalid state for publish (not draft, not owner, etc.)
            logger.warning(f"Publish failed for book {pk}: {e}")
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except DraftChangedError as e:
            # Draft modified during publish
            logger.warning(f"Publish conflict for book {pk}: {e}")
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        except Exception as e:
            # Unexpected error
            logger.exception(f"Unexpected error publishing book {pk}")
            return Response(
                {"detail": f"Publish failed: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(
        detail=True,
        methods=["get"],
        url_path="audit",
        permission_classes=[IsAuthenticated, IsOwnerOrReadOnly],
    )
    def audit_log(self, request, pk=None):
        """
        Get audit log for a book.

        Query parameters:
        - action: Filter by action type (upload, edit, publish)
        - user_id: Filter by user ID
        - start_date: Filter by start date (YYYY-MM-DD)
        - end_date: Filter by end date (YYYY-MM-DD)
        - limit: Maximum number of records (default: 100, max: 500)

        Only book owners and staff can view audit logs.
        """
        from datetime import datetime

        book = self.get_object()

        # Check permissions - owner or staff only
        is_owner = book.owner == request.user
        is_staff = request.user.is_staff

        if not is_owner and not is_staff:
            return Response(
                {"detail": "Only book owners or staff can view audit logs."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Parse query parameters
        action = request.query_params.get("action")
        user_id = request.query_params.get("user_id")
        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")
        limit = request.query_params.get("limit", "100")

        # Validate and parse limit
        try:
            limit = int(limit)
            limit = min(limit, 500)  # Cap at 500
            limit = max(limit, 1)  # Minimum 1
        except (ValueError, TypeError):
            limit = 100

        # Parse dates
        parsed_start_date = None
        parsed_end_date = None

        if start_date:
            try:
                parsed_start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
            except ValueError:
                return Response(
                    {"detail": "Invalid start_date format. Use YYYY-MM-DD."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        if end_date:
            try:
                parsed_end_date = datetime.strptime(end_date, "%Y-%m-%d").date()
            except ValueError:
                return Response(
                    {"detail": "Invalid end_date format. Use YYYY-MM-DD."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Parse user_id
        parsed_user_id = None
        if user_id:
            try:
                parsed_user_id = int(user_id)
            except (ValueError, TypeError):
                return Response(
                    {"detail": "Invalid user_id format. Must be an integer."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Get audit log
        audit_logs = audit_service.get_audit_log(
            book_id=pk,
            action=action,
            user_id=parsed_user_id,
            start_date=parsed_start_date,
            end_date=parsed_end_date,
            limit=limit,
        )

        serializer = BookAuditLogSerializer(audit_logs, many=True)
        return Response(
            {
                "count": len(serializer.data),
                "book_id": pk,
                "filters": {
                    "action": action,
                    "user_id": parsed_user_id,
                    "start_date": start_date,
                    "end_date": end_date,
                },
                "results": serializer.data,
            }
        )


class PageNoteViewSet(viewsets.ViewSet):
    """ViewSet for creating, listing, and deleting page notes."""

    queryset = PageNote.objects.all()
    serializer_class = PageNoteSerializer
    permission_classes = [IsAuthenticated]

    def list(self, request, book_id=None):
        resolved_book_id = (
            book_id
            or request.query_params.get("book_id")
            or request.query_params.get("bookId")
        )
        if not resolved_book_id:
            return Response(
                {"detail": "book_id is required."}, status=status.HTTP_400_BAD_REQUEST
            )

        book = get_object_or_404(Book, id=resolved_book_id)
        if not book.can_user_access(request.user):
            return Response(
                {"detail": "You do not have access to this book."},
                status=status.HTTP_403_FORBIDDEN,
            )

        notes = PageNote.objects.filter(book=book, user=request.user).order_by(
            "page_number", "created_at"
        )

        serializer = self.serializer_class(
            notes, many=True, context={"request": request}
        )
        return Response(serializer.data)

    def create(self, request, book_id=None):
        resolved_book_id = (
            book_id or request.data.get("book_id") or request.data.get("bookId")
        )
        if not resolved_book_id:
            return Response(
                {"detail": "book_id is required."}, status=status.HTTP_400_BAD_REQUEST
            )

        book = get_object_or_404(Book, id=resolved_book_id)
        if not book.can_user_access(request.user):
            return Response(
                {"detail": "You do not have access to this book."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = self.serializer_class(
            data=request.data, context={"request": request, "book": book}
        )
        serializer.is_valid(raise_exception=True)

        try:
            note = serializer.save(book=book, user=request.user)
        except IntegrityError:
            return Response(
                {"detail": "Note already exists for this page."},
                status=status.HTTP_409_CONFLICT,
            )

        output = self.serializer_class(note, context={"request": request})
        return Response(output.data, status=status.HTTP_201_CREATED)

    def destroy(self, request, pk=None):
        note = get_object_or_404(PageNote, pk=pk)
        if note.user != request.user:
            return Response(
                {"detail": "You do not have permission to delete this note."},
                status=status.HTTP_403_FORBIDDEN,
            )

        note.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SavedPageViewSet(viewsets.ViewSet):
    """List, save, and delete bookmarked reader pages (max 10 per book)."""

    permission_classes = [IsAuthenticated]
    MAX_SAVED = SavedPage.MAX_PER_BOOK

    def list(self, request, book_id=None):
        """GET /books/<book_id>/saved-pages/ — return saved pages for this user+book."""
        book = get_object_or_404(Book, pk=book_id)
        if not book.can_user_access(request.user):
            return Response(
                {"detail": "You do not have access to this book."},
                status=status.HTTP_403_FORBIDDEN,
            )
        pages = SavedPage.objects.filter(user=request.user, book=book)
        serializer = SavedPageSerializer(pages, many=True)
        return Response(
            {
                "count": len(serializer.data),
                "max": self.MAX_SAVED,
                "results": serializer.data,
            }
        )

    def create(self, request, book_id=None):
        """POST /books/<book_id>/saved-pages/ — save a page."""
        book = get_object_or_404(Book, pk=book_id)
        if not book.can_user_access(request.user):
            return Response(
                {"detail": "You do not have access to this book."},
                status=status.HTTP_403_FORBIDDEN,
            )

        page_number = request.data.get("page_number")
        try:
            page_number = int(page_number)
            if page_number < 1:
                raise ValueError
        except (TypeError, ValueError):
            return Response(
                {"detail": "page_number must be a positive integer."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            existing = (
                SavedPage.objects.select_for_update()
                .filter(
                    user=request.user,
                    book=book,
                    page_number=page_number,
                )
                .first()
            )
            if existing is not None:
                serializer = SavedPageSerializer(existing)
                return Response(serializer.data, status=status.HTTP_200_OK)

            # Enforce max 10 per user per book
            current_count = SavedPage.objects.filter(
                user=request.user, book=book
            ).count()
            if current_count >= self.MAX_SAVED:
                return Response(
                    {
                        "detail": f"You can save up to {self.MAX_SAVED} pages per book. Remove a saved page first.",
                        "code": "max_saved_pages_reached",
                    },
                    status=status.HTTP_409_CONFLICT,
                )

            try:
                saved, created = SavedPage.objects.get_or_create(
                    user=request.user,
                    book=book,
                    page_number=page_number,
                )
            except IntegrityError:
                saved = SavedPage.objects.get(
                    user=request.user, book=book, page_number=page_number
                )
                created = False

        serializer = SavedPageSerializer(saved)
        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    def destroy(self, request, book_id=None, page_number=None):
        """DELETE /books/<book_id>/saved-pages/<page_number>/ — unsave a page."""
        book = get_object_or_404(Book, pk=book_id)
        if not book.can_user_access(request.user):
            return Response(
                {"detail": "You do not have access to this book."},
                status=status.HTTP_403_FORBIDDEN,
            )
        entry = get_object_or_404(
            SavedPage, user=request.user, book=book, page_number=page_number
        )
        entry.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def destroy_all(self, request, book_id=None):
        """DELETE /books/<book_id>/saved-pages/ — clear all saved pages for this book."""
        book = get_object_or_404(Book, pk=book_id)
        if not book.can_user_access(request.user):
            return Response(
                {"detail": "You do not have access to this book."},
                status=status.HTTP_403_FORBIDDEN,
            )
        SavedPage.objects.filter(user=request.user, book=book).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ReadingPositionViewSet(viewsets.ViewSet):
    """Get, set, or clear a user's reading position for a book (cross-device)."""

    permission_classes = [IsAuthenticated]

    def retrieve(self, request, book_id=None):
        """GET /books/<book_id>/reading-position/ — return current position or null."""
        book = get_object_or_404(Book, pk=book_id)
        if not book.can_user_access(request.user):
            return Response(
                {"detail": "You do not have access to this book."},
                status=status.HTTP_403_FORBIDDEN,
            )
        try:
            pos = ReadingPosition.objects.get(user=request.user, book=book)
        except ReadingPosition.DoesNotExist:
            return Response({"page_number": None}, status=status.HTTP_200_OK)
        return Response(ReadingPositionSerializer(pos).data)

    def update(self, request, book_id=None):
        """PUT /books/<book_id>/reading-position/ — upsert reading position."""
        book = get_object_or_404(Book, pk=book_id)
        if not book.can_user_access(request.user):
            return Response(
                {"detail": "You do not have access to this book."},
                status=status.HTTP_403_FORBIDDEN,
            )

        page_number = request.data.get("page_number")
        try:
            page_number = int(page_number)
            if page_number < 1:
                raise ValueError
        except (TypeError, ValueError):
            return Response(
                {"detail": "page_number must be a positive integer."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        pos, created = ReadingPosition.objects.update_or_create(
            user=request.user,
            book=book,
            defaults={"page_number": page_number},
        )
        serializer = ReadingPositionSerializer(pos)
        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    def destroy(self, request, book_id=None):
        """DELETE /books/<book_id>/reading-position/ — clear position."""
        book = get_object_or_404(Book, pk=book_id)
        if not book.can_user_access(request.user):
            return Response(
                {"detail": "You do not have access to this book."},
                status=status.HTTP_403_FORBIDDEN,
            )
        ReadingPosition.objects.filter(user=request.user, book=book).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
