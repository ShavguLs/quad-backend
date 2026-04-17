"""Serializers for the books app."""

from rest_framework import serializers

from apps.books.models import (
    Book,
    BookAuditLog,
    BookFile,
    PageNote,
    SavedPage,
    ReadingPosition,
)
from apps.books.validators import validate_image


class BookFileSerializer(serializers.ModelSerializer):
    """Serializer for book file metadata."""

    download_url = serializers.SerializerMethodField()

    class Meta:
        model = BookFile
        fields = [
            "id",
            "original_filename",
            "file_size",
            "mime_type",
            "uploaded_at",
            "download_url",
        ]
        read_only_fields = ["id", "uploaded_at"]

    def get_download_url(self, obj):
        # Raw file URLs are intentionally not exposed through public APIs.
        return None


class BookSerializer(serializers.ModelSerializer):
    """Serializer for Book model."""

    owner = serializers.ReadOnlyField(source="owner.email")
    url_slug = serializers.CharField(source="slug", read_only=True)
    cover_image_url = serializers.SerializerMethodField()
    cover_image = serializers.ImageField(
        write_only=True, required=False, allow_null=True
    )

    coverUrl = serializers.SerializerMethodField()
    totalPages = serializers.SerializerMethodField()
    views = serializers.SerializerMethodField()
    followers = serializers.SerializerMethodField()
    revenue = serializers.SerializerMethodField()
    purchase_count = serializers.SerializerMethodField()

    publish_status = serializers.CharField(read_only=True)
    publish_error = serializers.CharField(read_only=True)
    extraction_status = serializers.CharField(read_only=True)
    extraction_error = serializers.SerializerMethodField()
    is_readable = serializers.SerializerMethodField()

    class Meta:
        model = Book
        fields = [
            "id",
            "owner",
            "title",
            "author",
            "url_slug",
            "description",
            "status",
            "price",
            "category",
            "is_featured",
            "view_count",
            "follower_count",
            "revenue_total",
            "total_pages",
            "created_at",
            "updated_at",
            "cover_image",
            "cover_image_url",
            "publish_status",
            "publish_error",
            "extraction_status",
            "extraction_error",
            "is_readable",
            "coverUrl",
            "totalPages",
            "views",
            "followers",
            "revenue",
            "purchase_count",
        ]
        read_only_fields = [
            "id",
            "owner",
            "created_at",
            "updated_at",
            "view_count",
            "follower_count",
            "revenue_total",
            "total_pages",
            "coverUrl",
            "totalPages",
            "views",
            "followers",
            "revenue",
            "purchase_count",
            "publish_status",
            "publish_error",
            "extraction_status",
            "extraction_error",
            "is_readable",
        ]

    def get_cover_image_url(self, obj):
        if obj.cover_image:
            request = self.context.get("request")
            if request:
                return request.build_absolute_uri(obj.cover_image.url)
            return obj.cover_image.url
        return None

    def get_coverUrl(self, obj):
        return self.get_cover_image_url(obj)

    def get_totalPages(self, obj):
        return obj.total_pages

    def get_views(self, obj):
        return obj.view_count

    def get_followers(self, obj):
        return obj.follower_count

    def get_revenue(self, obj):
        return obj.revenue_total

    def get_purchase_count(self, obj):
        return obj.orders.filter(status="COMPLETED").count()

    def get_extraction_error(self, obj):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user and user.is_authenticated and (user == obj.owner or user.is_staff):
            return obj.extraction_error
        return None

    def get_is_readable(self, obj):
        if obj.extraction_status not in {"completed", "partial"}:
            return False
        # Prefer total_pages as fast-path, then fallback to content existence.
        if (obj.total_pages or 0) > 0:
            return True
        return obj.content_pages.exists()

    def create(self, validated_data):
        if validated_data.get("is_visible") is None:
            validated_data["is_visible"] = True
        return super().create(validated_data)

    def update(self, instance, validated_data):
        cover_image = validated_data.get("cover_image")
        if cover_image:
            validate_image(cover_image)
        return super().update(instance, validated_data)


class MyBookSerializer(serializers.ModelSerializer):
    """Serializer for owner's books with analytics."""

    coverUrl = serializers.SerializerMethodField()
    price = serializers.SerializerMethodField()
    revenue = serializers.SerializerMethodField()
    views = serializers.SerializerMethodField()
    owners = serializers.SerializerMethodField()
    owners_count = serializers.IntegerField(read_only=True)
    extraction_status = serializers.CharField(read_only=True)
    extraction_error = serializers.CharField(read_only=True)
    is_readable = serializers.SerializerMethodField()
    total_pages = serializers.IntegerField(read_only=True)

    class Meta:
        model = Book
        fields = [
            "id",
            "title",
            "price",
            "coverUrl",
            "view_count",
            "views",
            "follower_count",
            "owners_count",
            "owners",
            "revenue",
            "extraction_status",
            "extraction_error",
            "is_readable",
            "total_pages",
        ]

    def get_coverUrl(self, obj):
        if obj.cover_image:
            request = self.context.get("request")
            if request:
                return request.build_absolute_uri(obj.cover_image.url)
            return obj.cover_image.url
        return None

    def get_price(self, obj):
        return f"₾{obj.price}"

    def get_revenue(self, obj):
        return f"₾{obj.revenue_total}"

    def get_views(self, obj):
        return obj.view_count

    def get_owners(self, obj):
        return getattr(obj, "owners_count", 0)

    def get_is_readable(self, obj):
        if obj.extraction_status not in {"completed", "partial"}:
            return False
        if (obj.total_pages or 0) > 0:
            return True
        return obj.content_pages.exists()


class PageNoteSerializer(serializers.ModelSerializer):
    """Serializer for user-owned notes on book pages."""

    book_id = serializers.IntegerField(source="book.id", read_only=True)
    content = serializers.CharField(min_length=1, max_length=2000)
    page_number = serializers.IntegerField(min_value=1)

    bookId = serializers.SerializerMethodField()
    pageNumber = serializers.SerializerMethodField()
    createdAt = serializers.SerializerMethodField()
    updatedAt = serializers.SerializerMethodField()

    class Meta:
        model = PageNote
        fields = [
            "id",
            "book_id",
            "page_number",
            "content",
            "created_at",
            "updated_at",
            "bookId",
            "pageNumber",
            "createdAt",
            "updatedAt",
        ]
        read_only_fields = [
            "id",
            "book_id",
            "created_at",
            "updated_at",
            "bookId",
            "pageNumber",
            "createdAt",
            "updatedAt",
        ]

    def get_bookId(self, obj):
        return obj.book_id

    def get_pageNumber(self, obj):
        return obj.page_number

    def get_createdAt(self, obj):
        return obj.created_at

    def get_updatedAt(self, obj):
        return obj.updated_at

    def validate(self, attrs):
        request = self.context.get("request")
        book = self.context.get("book")

        if not book:
            book_id = self.initial_data.get("book_id") or self.initial_data.get(
                "bookId"
            )
            if not book_id:
                raise serializers.ValidationError({"book_id": "Book is required."})
            try:
                book = Book.objects.get(id=book_id)
            except Book.DoesNotExist:
                raise serializers.ValidationError({"book_id": "Book not found."})

        if request and not book.can_user_access(request.user):
            raise serializers.ValidationError(
                {"book_id": "You do not have access to this book."}
            )

        page_number = attrs.get("page_number")
        total_pages = book.total_pages or 0
        if total_pages < 1:
            raise serializers.ValidationError(
                {"page_number": "Book has no pages available."}
            )
        if page_number and page_number > total_pages:
            raise serializers.ValidationError(
                {"page_number": "Page number exceeds total pages."}
            )

        return attrs


class BookAuditLogSerializer(serializers.ModelSerializer):
    """Serializer for audit log entries."""

    bookId = serializers.IntegerField(source="book_id", read_only=True)
    userId = serializers.IntegerField(source="user_id", read_only=True)
    userEmail = serializers.SerializerMethodField()
    action = serializers.CharField(read_only=True)
    timestamp = serializers.DateTimeField(read_only=True)
    details = serializers.JSONField(read_only=True)
    ipAddress = serializers.CharField(
        source="ip_address", read_only=True, allow_null=True
    )

    class Meta:
        model = BookAuditLog
        fields = [
            "id",
            "bookId",
            "userId",
            "userEmail",
            "action",
            "timestamp",
            "details",
            "ipAddress",
        ]

    def get_userEmail(self, obj):
        if obj.user:
            return obj.user.email
        return None


class SavedPageSerializer(serializers.ModelSerializer):
    """Serializer for user-bookmarked reader pages."""

    pageNumber = serializers.IntegerField(source="page_number", read_only=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = SavedPage
        fields = ["id", "page_number", "created_at", "pageNumber", "createdAt"]
        read_only_fields = ["id", "created_at", "pageNumber", "createdAt"]


class ReadingPositionSerializer(serializers.ModelSerializer):
    """Serializer for user's cross-device reading position."""

    pageNumber = serializers.IntegerField(source="page_number", read_only=True)
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)

    class Meta:
        model = ReadingPosition
        fields = ["id", "page_number", "updated_at", "pageNumber", "updatedAt"]
        read_only_fields = ["id", "updated_at", "pageNumber", "updatedAt"]
