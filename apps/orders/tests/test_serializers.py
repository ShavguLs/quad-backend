"""
Unit tests for order serializers.
"""

import pytest
from decimal import Decimal
from unittest.mock import Mock

from rest_framework.test import APIRequestFactory

from apps.books.models import Book
from apps.orders.models import Order
from apps.orders.serializers import OrderCreateSerializer, OrderSerializer
from apps.users.models import User


pytestmark = [pytest.mark.unit, pytest.mark.django_db]


class TestOrderSerializer:
    """Test cases for the OrderSerializer."""

    def setup_method(self):
        self.factory = APIRequestFactory()

    def test_serialize_order(self):
        """Test basic order serialization with all computed fields."""
        buyer = User.objects.create_user(
            email="buyer@example.com",
            password="secret123",
            first_name="Buyer",
            last_name="User",
            handle="buyeruser",
        )
        author = User.objects.create_user(
            email="author@example.com",
            password="secret123",
            first_name="Author",
            last_name="User",
            handle="authoruser",
        )
        book = Book.objects.create(
            title="Test Book",
            owner=author,
            price=Decimal("19.99"),
            status="published",
        )
        order = Order.objects.create(
            buyer=buyer,
            book=book,
            amount=Decimal("19.99"),
            status=Order.STATUS_COMPLETED,
        )

        request = self.factory.get('/orders/')
        serializer = OrderSerializer(order, context={'request': request})
        data = serializer.data

        assert data['id'] == str(order.id)
        assert data['bookTitle'] == "Test Book"
        assert data['price'] == "₾19.99"
        assert data['status'] == Order.STATUS_COMPLETED
        assert data['timestamp'] == order.created_at.isoformat()
        assert 'img' in data

    def test_serialize_order_without_cover_image(self):
        """Test order serialization when book has no cover image."""
        buyer = User.objects.create_user(
            email="nocoverbuyer@example.com",
            password="secret123",
            first_name="NoCover",
            last_name="Buyer",
            handle="nocoverbuyer",
        )
        author = User.objects.create_user(
            email="nocoverauthor@example.com",
            password="secret123",
            first_name="NoCover",
            last_name="Author",
            handle="nocoverauthor",
        )
        book = Book.objects.create(
            title="No Cover Book",
            owner=author,
            price=Decimal("9.99"),
            status="published",
        )
        order = Order.objects.create(
            buyer=buyer,
            book=book,
            amount=Decimal("9.99"),
            status=Order.STATUS_COMPLETED,
        )

        request = self.factory.get('/orders/')
        serializer = OrderSerializer(order, context={'request': request})
        data = serializer.data

        assert data['img'] is None

    def test_serialize_order_without_request_context(self):
        """Test order serialization without request in context."""
        buyer = User.objects.create_user(
            email="nocontextbuyer@example.com",
            password="secret123",
            first_name="NoContext",
            last_name="Buyer",
            handle="nocontextbuyer",
        )
        author = User.objects.create_user(
            email="nocontextauthor@example.com",
            password="secret123",
            first_name="NoContext",
            last_name="Author",
            handle="nocontextauthor",
        )
        book = Book.objects.create(
            title="No Context Book",
            owner=author,
            price=Decimal("14.99"),
            status="published",
        )
        order = Order.objects.create(
            buyer=buyer,
            book=book,
            amount=Decimal("14.99"),
            status=Order.STATUS_COMPLETED,
        )

        serializer = OrderSerializer(order)  # No context
        data = serializer.data

        assert data['bookTitle'] == "No Context Book"
        assert data['price'] == "₾14.99"

    def test_serialize_order_with_mock_cover_image(self):
        """Test order serialization with cover image using mock."""
        buyer = User.objects.create_user(
            email="coverbuyer@example.com",
            password="secret123",
            first_name="Cover",
            last_name="Buyer",
            handle="coverbuyer",
        )
        author = User.objects.create_user(
            email="coverauthor@example.com",
            password="secret123",
            first_name="Cover",
            last_name="Author",
            handle="coverauthor",
        )
        book = Book.objects.create(
            title="Cover Book",
            owner=author,
            price=Decimal("24.99"),
            status="published",
        )

        order = Order.objects.create(
            buyer=buyer,
            book=book,
            amount=Decimal("24.99"),
            status=Order.STATUS_COMPLETED,
        )

        # Mock cover_image directly on the book instance without saving
        mock_cover = Mock()
        mock_cover.url = "/media/covers/test.jpg"
        book.cover_image = mock_cover

        request = self.factory.get('/orders/')
        serializer = OrderSerializer(order, context={'request': request})
        data = serializer.data

        assert data['img'] == "http://testserver/media/covers/test.jpg"

    def test_serialize_multiple_orders(self):
        """Test serialization of multiple orders."""
        buyer = User.objects.create_user(
            email="multiplebuyer@example.com",
            password="secret123",
            first_name="Multiple",
            last_name="Buyer",
            handle="multiplebuyer",
        )
        author = User.objects.create_user(
            email="multipleauthor@example.com",
            password="secret123",
            first_name="Multiple",
            last_name="Author",
            handle="multipleauthor",
        )

        book1 = Book.objects.create(
            title="Book One",
            owner=author,
            price=Decimal("10.00"),
            status="published",
        )
        book2 = Book.objects.create(
            title="Book Two",
            owner=author,
            price=Decimal("20.00"),
            status="published",
        )

        order1 = Order.objects.create(
            buyer=buyer,
            book=book1,
            amount=Decimal("10.00"),
            status=Order.STATUS_COMPLETED,
        )
        order2 = Order.objects.create(
            buyer=buyer,
            book=book2,
            amount=Decimal("20.00"),
            status=Order.STATUS_PENDING,
        )

        request = self.factory.get('/orders/')
        orders = Order.objects.filter(buyer=buyer)
        serializer = OrderSerializer(orders, many=True, context={'request': request})
        data = serializer.data

        assert len(data) == 2
        assert data[0]['bookTitle'] == "Book Two"  # Most recent first
        assert data[0]['price'] == "₾20.00"
        assert data[0]['status'] == Order.STATUS_PENDING
        assert data[1]['bookTitle'] == "Book One"
        assert data[1]['price'] == "₾10.00"
        assert data[1]['status'] == Order.STATUS_COMPLETED

    def test_order_serializer_fields_are_read_only(self):
        """Test that all OrderSerializer fields are read-only."""
        assert OrderSerializer.Meta.read_only_fields == [
            'id', 'bookTitle', 'price', 'img', 'status', 'timestamp'
        ]

    def test_get_bookTitle_method(self):
        """Test get_bookTitle method returns book title."""
        buyer = User.objects.create_user(
            email="titlebuyer@example.com",
            password="secret123",
            first_name="Title",
            last_name="Buyer",
            handle="titlebuyer",
        )
        author = User.objects.create_user(
            email="titleauthor@example.com",
            password="secret123",
            first_name="Title",
            last_name="Author",
            handle="titleauthor",
        )
        book = Book.objects.create(
            title="Special Title Book",
            owner=author,
            price=Decimal("5.00"),
            status="published",
        )
        order = Order.objects.create(
            buyer=buyer,
            book=book,
            amount=Decimal("5.00"),
            status=Order.STATUS_COMPLETED,
        )

        serializer = OrderSerializer(order)
        assert serializer.get_bookTitle(order) == "Special Title Book"

    def test_get_price_method(self):
        """Test get_price method formats amount with ₾ symbol."""
        buyer = User.objects.create_user(
            email="pricebuyer@example.com",
            password="secret123",
            first_name="Price",
            last_name="Buyer",
            handle="pricebuyer",
        )
        author = User.objects.create_user(
            email="priceauthor@example.com",
            password="secret123",
            first_name="Price",
            last_name="Author",
            handle="priceauthor",
        )
        book = Book.objects.create(
            title="Price Book",
            owner=author,
            price=Decimal("123.45"),
            status="published",
        )
        order = Order.objects.create(
            buyer=buyer,
            book=book,
            amount=Decimal("123.45"),
            status=Order.STATUS_COMPLETED,
        )

        serializer = OrderSerializer(order)
        assert serializer.get_price(order) == "₾123.45"

    def test_get_timestamp_method(self):
        """Test get_timestamp method returns ISO format."""
        buyer = User.objects.create_user(
            email="timebuyer@example.com",
            password="secret123",
            first_name="Time",
            last_name="Buyer",
            handle="timebuyer",
        )
        author = User.objects.create_user(
            email="timeauthor@example.com",
            password="secret123",
            first_name="Time",
            last_name="Author",
            handle="timeauthor",
        )
        book = Book.objects.create(
            title="Time Book",
            owner=author,
            price=Decimal("1.00"),
            status="published",
        )
        order = Order.objects.create(
            buyer=buyer,
            book=book,
            amount=Decimal("1.00"),
            status=Order.STATUS_COMPLETED,
        )

        serializer = OrderSerializer(order)
        assert serializer.get_timestamp(order) == order.created_at.isoformat()


class TestOrderCreateSerializer:
    """Test cases for the OrderCreateSerializer."""

    def test_valid_book_id(self):
        """Test validation with valid book ID."""
        serializer = OrderCreateSerializer(data={'book': 1})
        assert serializer.is_valid()
        assert serializer.validated_data['book'] == 1

    def test_valid_book_id_as_string(self):
        """Test validation with book ID as string."""
        serializer = OrderCreateSerializer(data={'book': '123'})
        assert serializer.is_valid()
        assert serializer.validated_data['book'] == 123

    def test_missing_book_field(self):
        """Test validation fails when book field is missing."""
        serializer = OrderCreateSerializer(data={})
        assert not serializer.is_valid()
        assert 'book' in serializer.errors

    def test_invalid_book_type(self):
        """Test validation fails with invalid book type."""
        serializer = OrderCreateSerializer(data={'book': 'not-a-number'})
        assert not serializer.is_valid()
        assert 'book' in serializer.errors

    def test_book_field_is_required(self):
        """Test that book field is required."""
        serializer = OrderCreateSerializer(data={'book': None})
        assert not serializer.is_valid()
        assert 'book' in serializer.errors

    def test_negative_book_id(self):
        """Test validation with negative book ID (should be valid integer)."""
        serializer = OrderCreateSerializer(data={'book': -1})
        assert serializer.is_valid()  # IntegerField accepts negative values
        assert serializer.validated_data['book'] == -1

    def test_zero_book_id(self):
        """Test validation with zero book ID."""
        serializer = OrderCreateSerializer(data={'book': 0})
        assert serializer.is_valid()
        assert serializer.validated_data['book'] == 0

    def test_large_book_id(self):
        """Test validation with large book ID."""
        serializer = OrderCreateSerializer(data={'book': 999999})
        assert serializer.is_valid()
        assert serializer.validated_data['book'] == 999999
