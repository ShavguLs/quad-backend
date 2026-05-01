from __future__ import annotations

"""
Views for the books app.
"""

import html
import io
import logging
import mimetypes

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.db.models import F, Max, Q
from django.http import FileResponse, HttpResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.http import content_disposition_header
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.response import Response

from apps.books.models import (
    Book,
    BookFile,
    BookFollow,
    BookView,
    PageNote,
    SavedPage,
    ReadingPosition,
    BookContent,
)
from apps.books.permissions import IsOwnerOrReadOnly
from apps.books.audit import service as audit_service
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
from apps.books.storage import PrivateMediaStorage
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
    WATERMARK_CACHE_TIMEOUT = max(getattr(settings, "CACHE_DEFAULT_TIMEOUT", 300), 60 * 60 * 24)
    PREVIEW_PAGE_LIMIT = 10
    READER_PAGE_WINDOW_LIMIT = 24
    READER_DOCUMENT_TOKEN_MAX_AGE = 60 * 60
    PDF_CHUNK_SIZE = 1024 * 64

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

    def list(self, request, *args, **kwargs):
        """
        Public catalog listing — always returns only published, visible books.

        Owner drafts are accessible via /me/books/ or the detail endpoint.
        Supports query parameters:
        - search: filter by title or author (case-insensitive partial match)
        - category: filter by exact category
        - ordering: sort by newest, views, followers, or revenue
        - page / page_size: standard pagination
        """
        queryset = Book.objects.filter(
            status="published", is_visible=True
        ).select_related("owner")

        search = request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search) | Q(author__icontains=search)
            )

        category = request.query_params.get("category", "").strip()
        if category:
            queryset = queryset.filter(category__iexact=category)

        ordering_param = request.query_params.get("ordering", "").strip()
        ordering_map = {
            "newest": "-created_at",
            "views": "-view_count",
            "followers": "-follower_count",
            "revenue": "-revenue_total",
        }
        if ordering_param in ordering_map:
            queryset = queryset.order_by(ordering_map[ordering_param])

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

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
        order = BookViewSet._get_completed_order(book, user)
        if order is None:
            return False
        if order.expires_at is not None and order.expires_at <= timezone.now():
            return False
        return True

    @staticmethod
    def _get_completed_order(book: Book, user) -> Order | None:
        if not user or not user.is_authenticated:
            return None
        return Order.objects.filter(
            buyer=user, book=book, status=Order.STATUS_COMPLETED
        ).order_by("-created_at").first()

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
    def _access_label(book: Book) -> str:
        return dict(Book.ACCESS_TYPE_CHOICES).get(book.access_type, "სასწავლო")

    @staticmethod
    def _latest_source_file(book: Book) -> BookFile | None:
        return book.files.order_by("-uploaded_at").first()

    def _reader_document_token(self, request, book: Book, book_file: BookFile, preview: bool = False) -> str:
        signer = signing.TimestampSigner(salt="books.reader-document")
        user_id = request.user.pk if request.user.is_authenticated else ""
        return signer.sign(f"{book.pk}:{book_file.pk}:{int(preview)}:{user_id}")

    def _reader_document_token_user_id(self, request, book: Book, book_file: BookFile, preview: bool = False) -> str | None:
        token = request.query_params.get("token")
        if not token:
            return None

        signer = signing.TimestampSigner(salt="books.reader-document")
        try:
            value = signer.unsign(token, max_age=self.READER_DOCUMENT_TOKEN_MAX_AGE)
        except (signing.BadSignature, signing.SignatureExpired):
            return None

        parts = value.split(":")
        if len(parts) != 4:
            return None

        token_book_id, token_file_id, token_preview, token_user_id = parts
        if token_book_id != str(book.pk) or token_file_id != str(book_file.pk) or token_preview != str(int(preview)):
            return None

        if preview:
            return token_user_id

        if not token_user_id:
            return None

        User = get_user_model()
        try:
            token_user = User.objects.get(pk=token_user_id)
        except User.DoesNotExist:
            return None

        _state, can_read, _can_download, _order = self._reader_access_state(book, token_user)
        return token_user_id if can_read else None

    def _has_valid_reader_document_token(self, request, book: Book, book_file: BookFile, preview: bool = False) -> bool:
        return self._reader_document_token_user_id(request, book, book_file, preview) is not None

    def _build_reader_url(self, request, book: Book, endpoint: str, preview: bool = False, book_file: BookFile | None = None) -> str:
        base_path = request.path.split("/read/", 1)[0].rstrip("/")
        url = request.build_absolute_uri(f"{base_path}/read/{endpoint}/")
        params = []
        if preview:
            params.append("preview=1")
        if endpoint == "document" and book_file is not None:
            params.append(f"token={self._reader_document_token(request, book, book_file, preview)}")
        if params:
            return f"{url}?{'&'.join(params)}"
        return url

    def _reader_access_state(self, book: Book, user) -> tuple[str, bool, bool, Order | None]:
        if self._is_owner(book, user):
            return "ready", True, True, None

        order = self._get_completed_order(book, user)
        if order is None:
            return "purchase_required", False, False, None

        if order.expires_at is not None and order.expires_at <= timezone.now():
            return "expired", False, False, order

        can_download = book.access_type == Book.ACCESS_TYPE_SCIENTIFIC
        return "ready", True, can_download, order

    def _reader_access_payload(self, request, book: Book, mode: str, state: str, can_read: bool, can_download: bool, expires_at, document_url: str | None, download_url: str | None):
        total_pages = self._reader_total_pages(book)
        return {
            "book_id": book.pk,
            "title": book.title,
            "author": book.author,
            "access_type": book.access_type,
            "access_label": self._access_label(book),
            "mode": mode,
            "status": state,
            "can_read": can_read,
            "can_download": can_download,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "preview_pages": self.PREVIEW_PAGE_LIMIT,
            "total_pages": total_pages,
            "document_url": document_url,
            "download_url": download_url,
        }

    @staticmethod
    def _reader_total_pages(book: Book) -> int:
        content_total = book.content_pages.aggregate(max_page=Max("page_number"))["max_page"] or 0
        return max(book.total_pages or 0, content_total)

    @staticmethod
    def _render_block_html(block: dict) -> str:
        metadata = block.get("metadata") if isinstance(block.get("metadata"), dict) else {}
        render_html = metadata.get("render_html")
        if isinstance(render_html, str) and render_html.strip():
            return render_html

        text = html.escape(str(block.get("text") or block.get("content") or ""))
        block_type = block.get("type")
        if block_type == "heading":
            attrs = block.get("attrs") if isinstance(block.get("attrs"), dict) else {}
            level = attrs.get("level", 2)
            try:
                level = min(max(int(level), 1), 6)
            except (TypeError, ValueError):
                level = 2
            return f"<h{level}>{text}</h{level}>"
        if block_type == "list_item":
            return f"<li>{text}</li>"
        if block_type == "page_break":
            return "<hr />"
        return f"<p>{text}</p>"

    def _reader_page_payload(self, request, page: BookContent, preview: bool) -> dict:
        blocks = page.blocks or []
        primary_metadata = {}
        if blocks and isinstance(blocks[0].get("metadata"), dict):
            primary_metadata = blocks[0]["metadata"]

        render_mode = primary_metadata.get("render_mode") or "html"
        fallback_image_path = primary_metadata.get("fallback_image_path")
        query = "?preview=1" if preview else ""
        image_url = (
            request.build_absolute_uri(f"{request.path.split('/read/', 1)[0].rstrip('/')}/read/page-image/{page.page_number}/{query}")
            if render_mode == "image" and fallback_image_path
            else None
        )

        return {
            "page_number": page.page_number,
            "render_mode": "image" if image_url else "html",
            "html": "" if image_url else "\n".join(self._render_block_html(block) for block in blocks),
            "image_url": image_url,
            "page_width": primary_metadata.get("page_width"),
            "page_height": primary_metadata.get("page_height"),
        }

    def _ensure_preview_file(self, book_file: BookFile) -> bool:
        if book_file.preview_file:
            return True

        try:
            import fitz

            with book_file.file.open("rb") as source:
                source_bytes = source.read()

            source_doc = fitz.open(stream=source_bytes, filetype="pdf")
            if source_doc.page_count <= 0:
                source_doc.close()
                return False
            preview_doc = fitz.open()
            preview_doc.insert_pdf(source_doc, from_page=0, to_page=min(source_doc.page_count, self.PREVIEW_PAGE_LIMIT) - 1)
            output = preview_doc.tobytes(garbage=4, deflate=True)
            preview_doc.close()
            source_doc.close()

            filename = f"book-{book_file.book_id}-preview.pdf"
            book_file.preview_file.save(filename, ContentFile(output), save=True)
            return True
        except Exception:
            logger.exception("Failed to generate preview PDF for book file %s", book_file.pk)
            return False

    @staticmethod
    def _parse_byte_range(range_header: str, file_size: int) -> tuple[int, int] | str | None:
        if not range_header.startswith("bytes="):
            return None

        range_value = range_header.removeprefix("bytes=").strip()
        if "," in range_value or "-" not in range_value:
            return "invalid"

        start_value, end_value = range_value.split("-", 1)
        try:
            if start_value == "":
                suffix_length = int(end_value)
                if suffix_length <= 0:
                    return "invalid"
                start = max(file_size - suffix_length, 0)
                end = file_size - 1
            else:
                start = int(start_value)
                end = int(end_value) if end_value else file_size - 1
        except ValueError:
            return "invalid"

        if start < 0 or end < start:
            return "invalid"
        if start >= file_size:
            return "unsatisfiable"

        return start, min(end, file_size - 1)

    def _stream_file_range(self, file_handle, start: int, length: int):
        try:
            file_handle.seek(start)
            remaining = length
            while remaining > 0:
                chunk = file_handle.read(min(self.PDF_CHUNK_SIZE, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk
        finally:
            file_handle.close()

    def _private_pdf_response(self, field_file, request, filename: str, as_attachment: bool = False):
        file_size = field_file.size
        range_header = request.META.get("HTTP_RANGE")
        disposition = content_disposition_header(as_attachment, filename)

        if range_header:
            byte_range = self._parse_byte_range(range_header, file_size)
            if byte_range == "unsatisfiable":
                response = HttpResponse(status=416)
                response["Content-Range"] = f"bytes */{file_size}"
                response["Accept-Ranges"] = "bytes"
                return response
            if byte_range != "invalid" and byte_range is not None:
                start, end = byte_range
                content_length = end - start + 1
                response = StreamingHttpResponse(
                    self._stream_file_range(field_file.open("rb"), start, content_length),
                    status=206,
                    content_type="application/pdf",
                )
                response["Content-Length"] = str(content_length)
                response["Content-Range"] = f"bytes {start}-{end}/{file_size}"
                response["Accept-Ranges"] = "bytes"
                if disposition:
                    response["Content-Disposition"] = disposition
                return response

        file_handle = field_file.open("rb")
        response = FileResponse(file_handle, content_type="application/pdf", as_attachment=as_attachment, filename=filename)
        response["Accept-Ranges"] = "bytes"
        return response

    def _source_pdf_response(self, request, book_file: BookFile, filename: str, as_attachment: bool = False):
        return self._private_pdf_response(book_file.file, request, filename, as_attachment=as_attachment)

    def _preview_pdf_response(self, request, book_file: BookFile):
        if not self._ensure_preview_file(book_file) or not book_file.preview_file:
            return Response(
                {"code": "preview_not_ready", "detail": "Preview is not ready."},
                status=status.HTTP_404_NOT_FOUND,
            )
        filename = f"{book_file.book.slug or book_file.book_id}-preview.pdf"
        return self._private_pdf_response(book_file.preview_file, request, filename)

    def _watermarked_pdf_response(self, book: Book, book_file: BookFile, order: Order, user):
        try:
            import fitz

            buyer_label = getattr(user, "email", None) or getattr(user, "handle", None) or str(user.pk)
            cache_key = (
                f"reader:watermark:book:{book.pk}:order:{order.pk}:buyer:{user.pk}:"
                f"source:{book_file.pk}:{book_file.uploaded_at.isoformat()}:{book_file.file_size}"
            )
            cached_output = cache.get(cache_key)

            if cached_output is None:
                with book_file.file.open("rb") as source:
                    source_bytes = source.read()

                doc = fitz.open(stream=source_bytes, filetype="pdf")
                watermark = f"Quaduni | {buyer_label} | Order {order.pk} | {book.title} | {order.created_at.date().isoformat()}"
                for page in doc:
                    rect = page.rect
                    positions = [
                        (36, max(48, rect.height * 0.18)),
                        (max(36, rect.width * 0.18), rect.height * 0.42),
                        (36, rect.height * 0.66),
                        (max(36, rect.width * 0.18), rect.height * 0.9),
                    ]
                    for position in positions:
                        page.insert_text(
                            position,
                            watermark,
                            fontsize=18,
                            color=(0.68, 0.68, 0.68),
                            overlay=True,
                        )

                cached_output = doc.tobytes(garbage=4, deflate=True)
                doc.close()
                cache.set(cache_key, cached_output, timeout=self.WATERMARK_CACHE_TIMEOUT)

            output = io.BytesIO(cached_output)
            output.seek(0)
            filename = f"{book.slug or book.pk}-watermarked.pdf"
            return FileResponse(output, content_type="application/pdf", as_attachment=True, filename=filename)
        except Exception:
            logger.exception("Failed to generate watermarked download for book %s order %s", book.pk, order.pk)
            return Response(
                {"code": "download_not_ready", "detail": "Download is not ready."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

    @staticmethod
    def _is_preview_request(request) -> bool:
        preview_value = str(request.query_params.get("preview", "")).strip().lower()
        return preview_value in {"1", "true", "yes", "on"}

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
        url_path="read/access",
        permission_classes=[IsAuthenticatedOrReadOnly],
    )
    def read_access(self, request, pk=None):
        """Return PDF reader access state for the external reader app."""
        book = self.get_object()
        is_preview_request = self._is_preview_request(request)
        is_owner = self._is_owner(book, request.user)

        if not is_owner and (book.status != "published" or not book.is_visible):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        latest_file = self._latest_source_file(book)
        if latest_file is None:
            return Response(
                self._reader_access_payload(
                    request,
                    book,
                    "preview" if is_preview_request else "full",
                    "processing",
                    False,
                    False,
                    None,
                    None,
                    None,
                ),
                status=status.HTTP_202_ACCEPTED,
            )

        if is_preview_request:
            return Response(
                self._reader_access_payload(
                    request,
                    book,
                    "preview",
                    "ready",
                    True,
                    False,
                    None,
                    self._build_reader_url(request, book, "document", preview=True, book_file=latest_file),
                    None,
                )
            )

        state, can_read, can_download, order = self._reader_access_state(book, request.user)
        expires_at = order.expires_at if order else None
        document_url = self._build_reader_url(request, book, "document", book_file=latest_file) if can_read else None
        download_url = self._build_reader_url(request, book, "download") if can_download else None
        return Response(
            self._reader_access_payload(
                request,
                book,
                "full",
                state,
                can_read,
                can_download,
                expires_at,
                document_url,
                download_url,
            )
        )

    @action(
        detail=True,
        methods=["get"],
        url_path="read/document",
        permission_classes=[IsAuthenticatedOrReadOnly],
    )
    def read_document(self, request, pk=None):
        """Serve the private PDF document after reader access checks."""
        book = get_object_or_404(Book.objects.select_related("owner"), pk=pk)
        is_preview_request = self._is_preview_request(request)
        is_owner = self._is_owner(book, request.user)

        latest_file = self._latest_source_file(book)
        if latest_file is None:
            return Response(
                {"code": "document_not_ready", "detail": "Document is not ready."},
                status=status.HTTP_404_NOT_FOUND,
            )

        token_user_id = self._reader_document_token_user_id(request, book, latest_file, is_preview_request)
        token_is_owner = token_user_id == str(book.owner_id)
        if not is_owner and (book.status != "published" or not book.is_visible) and not token_is_owner:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        if is_preview_request:
            return self._preview_pdf_response(request, latest_file)

        if token_user_id is not None:
            filename = latest_file.original_filename or f"{book.slug or book.pk}.pdf"
            return self._source_pdf_response(request, latest_file, filename)

        state, can_read, _can_download, _order = self._reader_access_state(book, request.user)
        if not can_read:
            code = "access_expired" if state == "expired" else "purchase_required"
            return Response({"code": code, "detail": "Reader access is not allowed."}, status=status.HTTP_403_FORBIDDEN)

        filename = latest_file.original_filename or f"{book.slug or book.pk}.pdf"
        return self._source_pdf_response(request, latest_file, filename)

    @action(
        detail=True,
        methods=["get"],
        url_path="read/download",
        permission_classes=[IsAuthenticated],
    )
    def read_download(self, request, pk=None):
        """Serve allowed downloads: owner original or scientific buyer watermark."""
        book = self.get_object()
        latest_file = self._latest_source_file(book)
        if latest_file is None:
            return Response(
                {"code": "document_not_ready", "detail": "Document is not ready."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if self._is_owner(book, request.user):
            filename = latest_file.original_filename or f"{book.slug or book.pk}.pdf"
            return self._source_pdf_response(request, latest_file, filename, as_attachment=True)

        state, can_read, can_download, order = self._reader_access_state(book, request.user)
        if not can_read:
            code = "access_expired" if state == "expired" else "purchase_required"
            return Response({"code": code, "detail": "Download is not allowed."}, status=status.HTTP_403_FORBIDDEN)
        if not can_download or order is None:
            return Response(
                {"code": "download_not_allowed", "detail": "Download is not allowed for this book."},
                status=status.HTTP_403_FORBIDDEN,
            )

        return self._watermarked_pdf_response(book, latest_file, order, request.user)

    @action(
        detail=True,
        methods=["get"],
        url_path="read/pages",
        permission_classes=[IsAuthenticatedOrReadOnly],
    )
    def read_pages(self, request, pk=None):
        """Return lightweight reader pages for fast, virtualized rendering."""
        book = get_object_or_404(Book.objects.select_related("owner"), pk=pk)
        is_preview_request = self._is_preview_request(request)
        is_owner = self._is_owner(book, request.user)

        if not is_owner and (book.status != "published" or not book.is_visible):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        if not is_preview_request:
            state, can_read, _can_download, _order = self._reader_access_state(book, request.user)
            if not can_read:
                code = "access_expired" if state == "expired" else "purchase_required"
                return Response({"code": code, "detail": "Reader access is not allowed."}, status=status.HTTP_403_FORBIDDEN)

        try:
            start = int(request.query_params.get("start", "1"))
            end = int(request.query_params.get("end", str(start + 4)))
        except (TypeError, ValueError):
            return Response(
                {"detail": "start and end must be positive integers."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if start < 1 or end < start:
            return Response(
                {"detail": "start and end must be positive integers."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        total_pages = self._reader_total_pages(book)
        max_end = min(total_pages or end, self.PREVIEW_PAGE_LIMIT) if is_preview_request else (total_pages or end)
        end = min(end, max_end, start + self.READER_PAGE_WINDOW_LIMIT - 1)
        pages = BookContent.objects.filter(
            book=book,
            page_number__gte=start,
            page_number__lte=end,
        ).order_by("page_number")

        return Response(
            {
                "book_id": book.pk,
                "total_pages": min(total_pages or pages.count(), self.PREVIEW_PAGE_LIMIT) if is_preview_request else (total_pages or pages.count()),
                "preview": is_preview_request,
                "pages": [self._reader_page_payload(request, page, is_preview_request) for page in pages],
            }
        )

    @action(
        detail=True,
        methods=["get"],
        url_path=r"read/page-image/(?P<page_number>\d+)",
        permission_classes=[IsAuthenticatedOrReadOnly],
    )
    def read_page_image(self, request, pk=None, page_number=None):
        """Serve a rasterized reader page image for exact-visual books."""
        book = get_object_or_404(Book.objects.select_related("owner"), pk=pk)
        is_preview_request = self._is_preview_request(request)
        is_owner = self._is_owner(book, request.user)

        if not is_owner and (book.status != "published" or not book.is_visible):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        if not is_preview_request:
            state, can_read, _can_download, _order = self._reader_access_state(book, request.user)
            if not can_read:
                code = "access_expired" if state == "expired" else "purchase_required"
                return Response({"code": code, "detail": "Reader access is not allowed."}, status=status.HTTP_403_FORBIDDEN)

        try:
            page_number_int = int(page_number)
        except (TypeError, ValueError):
            return Response({"detail": "Invalid page number."}, status=status.HTTP_400_BAD_REQUEST)

        if is_preview_request and page_number_int > self.PREVIEW_PAGE_LIMIT:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        page = get_object_or_404(BookContent, book=book, page_number=page_number_int)
        blocks = page.blocks or []
        metadata = blocks[0].get("metadata") if blocks and isinstance(blocks[0].get("metadata"), dict) else {}
        fallback_image_path = metadata.get("fallback_image_path")
        if not fallback_image_path:
            return Response({"detail": "Page image is not available."}, status=status.HTTP_404_NOT_FOUND)

        storage = PrivateMediaStorage()
        file_handle = storage.open(fallback_image_path, "rb")
        content_type = mimetypes.guess_type(fallback_image_path)[0] or "image/jpeg"
        response = FileResponse(file_handle, content_type=content_type)
        response["Cache-Control"] = "private, max-age=3600"
        return response

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
