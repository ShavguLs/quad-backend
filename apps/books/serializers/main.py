"""Serializers for the books app."""

from django.utils import timezone
from rest_framework import serializers

from apps.books.models import (
    Book,
    PageNote,
)
from apps.books.validators import validate_image
from apps.orders.models import Order


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
    access_expires_at = serializers.SerializerMethodField()
    access_is_expired = serializers.SerializerMethodField()

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
            "access_type",
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
            "coverUrl",
            "totalPages",
            "views",
            "followers",
            "revenue",
            "purchase_count",
            "access_expires_at",
            "access_is_expired",
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
            "access_expires_at",
            "access_is_expired",
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

    def _get_user_order(self, obj):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated or obj.owner_id == user.id:
            return None
        return Order.objects.filter(
            buyer=user,
            book=obj,
            status=Order.STATUS_COMPLETED,
        ).order_by("-created_at").first()

    def get_access_expires_at(self, obj):
        order = self._get_user_order(obj)
        if order and order.expires_at:
            return order.expires_at.isoformat()
        return None

    def get_access_is_expired(self, obj):
        order = self._get_user_order(obj)
        return bool(order and order.expires_at and order.expires_at <= timezone.now())

    def create(self, validated_data):
        if validated_data.get("is_visible") is None:
            validated_data["is_visible"] = True
        return super().create(validated_data)

    def update(self, instance, validated_data):
        cover_image = validated_data.get("cover_image")
        if cover_image:
            validate_image(cover_image)
        return super().update(instance, validated_data)


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

