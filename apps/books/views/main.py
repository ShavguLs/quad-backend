"""Views for the books app."""

from __future__ import annotations

import logging

from django.core.cache import cache
from django.db import IntegrityError
from django.db.models import F, Q
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser, IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.response import Response

from apps.books.models import Book, BookFollow, BookView, PageNote
from apps.books.serializers import BookSerializer, PageNoteSerializer


logger = logging.getLogger(__name__)


class BookViewSet(viewsets.ModelViewSet):
    """Public catalog API with staff-only catalog mutations."""

    queryset = Book.objects.all()
    serializer_class = BookSerializer

    def get_permissions(self):
        if self.action in {"create", "update", "partial_update", "destroy"}:
            return [IsAdminUser()]
        return [IsAuthenticatedOrReadOnly()]

    def get_queryset(self):
        queryset = Book.objects.select_related("owner")

        user = self.request.user
        if user.is_authenticated and user.is_staff:
            return queryset
        return queryset.filter(status="published", is_visible=True)

    def list(self, request, *args, **kwargs):
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
        serializer.save(owner=self.request.user)

    @staticmethod
    def _get_client_ip(request):
        forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR")

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

    @action(detail=False, methods=["get"], url_path="featured")
    def featured(self, request):
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
        methods=["get"],
        url_path="read",
        permission_classes=[IsAuthenticated],
    )
    def read(self, request, pk=None):
        book = self.get_object()
        
        if not book.can_user_access(request.user):
            return Response(
                {"detail": "You do not have access to this book."},
                status=status.HTTP_403_FORBIDDEN,
            )
            
        if not book.pdf_file:
            return Response(
                {"detail": "PDF file not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        pdf_file = self._open_pdf_file(book)
        if pdf_file is None:
            return Response(
                {"detail": "PDF file not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        response = FileResponse(pdf_file, content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{book.slug}.pdf"'
        return response

    @action(
        detail=True,
        methods=["get"],
        url_path="download",
        permission_classes=[IsAuthenticated],
    )
    def download(self, request, pk=None):
        book = self.get_object()
        
        if not book.can_user_access(request.user):
            return Response(
                {"detail": "You do not have access to this book."},
                status=status.HTTP_403_FORBIDDEN,
            )
            
        if book.access_type != Book.ACCESS_TYPE_SCIENTIFIC:
            return Response(
                {"detail": "This book is not available for download."},
                status=status.HTTP_403_FORBIDDEN,
            )
            
        if not book.pdf_file:
            return Response(
                {"detail": "PDF file not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        pdf_file = self._open_pdf_file(book)
        if pdf_file is None:
            return Response(
                {"detail": "PDF file not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        response = FileResponse(
            pdf_file,
            content_type="application/pdf",
            as_attachment=True,
            filename=f"{book.slug}.pdf",
        )
        return response

    def _open_pdf_file(self, book):
        try:
            return book.pdf_file.open("rb")
        except (FileNotFoundError, OSError) as exc:
            logger.warning(
                "Book PDF could not be opened",
                extra={"book_id": book.pk, "pdf_file": book.pdf_file.name},
                exc_info=True,
            )
            return None
        except Exception as exc:
            if not self._is_missing_pdf_storage_error(exc):
                raise
            logger.warning(
                "Book PDF could not be opened",
                extra={"book_id": book.pk, "pdf_file": book.pdf_file.name},
                exc_info=True,
            )
            return None

    def _is_missing_pdf_storage_error(self, exc):
        error_response = getattr(exc, "response", {})
        error = error_response.get("Error", {}) if isinstance(error_response, dict) else {}
        return error.get("Code") in {"404", "NoSuchKey", "NotFound"}


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
