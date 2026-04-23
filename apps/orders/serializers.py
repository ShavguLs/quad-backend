"""Serializers for orders app."""

from rest_framework import serializers

from apps.orders.models import Order


class OrderSerializer(serializers.ModelSerializer):
    """
    Serializer for order records with flat structure.

    Returns frontend-compatible fields matching the TypeScript Order interface:
    - bookTitle: from book.title
    - price: formatted with ₾ prefix
    - img: book cover image URL (or None)
    - timestamp: ISO 8601 formatted created_at
    - expiresAt: ISO 8601 formatted expires_at
    """

    bookTitle = serializers.SerializerMethodField()
    price = serializers.SerializerMethodField()
    img = serializers.SerializerMethodField()
    timestamp = serializers.SerializerMethodField()
    expiresAt = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = ['id', 'bookTitle', 'price', 'img', 'status', 'timestamp', 'expiresAt']
        read_only_fields = ['id', 'bookTitle', 'price', 'img', 'status', 'timestamp', 'expiresAt']

    def get_bookTitle(self, obj):
        """Return book title for frontend compatibility."""
        return obj.book.title

    def get_price(self, obj):
        """Format price with GEL currency symbol."""
        return f'₾{obj.amount}'

    def get_img(self, obj):
        """Generate absolute URL for book cover image."""
        if obj.book.cover_image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.book.cover_image.url)
            return obj.book.cover_image.url
        return None

    def get_timestamp(self, obj):
        """Return ISO 8601 formatted timestamp."""
        return obj.created_at.isoformat()

    def get_expiresAt(self, obj):
        """Return ISO 8601 formatted expiry timestamp."""
        if obj.expires_at:
            return obj.expires_at.isoformat()
        return None


class OrderCreateSerializer(serializers.Serializer):
    """Serializer for purchase requests."""

    book = serializers.IntegerField()
