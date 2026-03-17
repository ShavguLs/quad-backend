"""
Unit tests for order models.
"""

import pytest
from decimal import Decimal

from apps.books.models import Book
from apps.orders.models import Order
from apps.users.models import User


pytestmark = [pytest.mark.unit, pytest.mark.django_db]


class TestOrderModel:
    """Test cases for the Order model."""

    def test_create_order(self):
        """Test order creation with all required fields."""
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

        assert order.buyer == buyer
        assert order.book == book
        assert order.amount == Decimal("19.99")
        assert order.status == Order.STATUS_COMPLETED
        assert order.created_at is not None
        assert order.id is not None

    def test_order_default_status(self):
        """Test that default order status is PENDING."""
        buyer = User.objects.create_user(
            email="defaultbuyer@example.com",
            password="secret123",
            first_name="Default",
            last_name="Buyer",
            handle="defaultbuyer",
        )
        author = User.objects.create_user(
            email="defaultauthor@example.com",
            password="secret123",
            first_name="Default",
            last_name="Author",
            handle="defaultauthor",
        )
        book = Book.objects.create(
            title="Default Status Book",
            owner=author,
            price=Decimal("9.99"),
            status="published",
        )

        order = Order.objects.create(
            buyer=buyer,
            book=book,
            amount=Decimal("9.99"),
        )

        assert order.status == Order.STATUS_PENDING

    def test_order_str(self):
        """Test order string representation."""
        buyer = User.objects.create_user(
            email="strbuyer@example.com",
            password="secret123",
            first_name="Str",
            last_name="Buyer",
            handle="strbuyer",
        )
        author = User.objects.create_user(
            email="strauthor@example.com",
            password="secret123",
            first_name="Str",
            last_name="Author",
            handle="strauthor",
        )
        book = Book.objects.create(
            title="Str Book",
            owner=author,
            price=Decimal("15.00"),
            status="published",
        )

        order = Order.objects.create(
            buyer=buyer,
            book=book,
            amount=Decimal("15.00"),
            status=Order.STATUS_COMPLETED,
        )

        expected = f"Order {order.id} - strbuyer@example.com bought Str Book"
        assert str(order) == expected

    def test_order_unique_constraint(self):
        """Test that buyer cannot purchase the same book twice."""
        buyer = User.objects.create_user(
            email="unique@example.com",
            password="secret123",
            first_name="Unique",
            last_name="Buyer",
            handle="uniquebuyer",
        )
        author = User.objects.create_user(
            email="uniqueauthor@example.com",
            password="secret123",
            first_name="Unique",
            last_name="Author",
            handle="uniqueauthor",
        )
        book = Book.objects.create(
            title="Unique Book",
            owner=author,
            price=Decimal("20.00"),
            status="published",
        )

        Order.objects.create(
            buyer=buyer,
            book=book,
            amount=Decimal("20.00"),
            status=Order.STATUS_COMPLETED,
        )

        # Attempting to create duplicate order should fail
        with pytest.raises(Exception):  # IntegrityError
            Order.objects.create(
                buyer=buyer,
                book=book,
                amount=Decimal("20.00"),
                status=Order.STATUS_COMPLETED,
            )

    def test_order_status_choices(self):
        """Test valid order status values."""
        buyer = User.objects.create_user(
            email="statusbuyer@example.com",
            password="secret123",
            first_name="Status",
            last_name="Buyer",
            handle="statusbuyer",
        )
        author = User.objects.create_user(
            email="statusauthor@example.com",
            password="secret123",
            first_name="Status",
            last_name="Author",
            handle="statusauthor",
        )

        for status_value, status_label in Order.STATUS_CHOICES:
            book = Book.objects.create(
                title=f"Status {status_value} Book",
                owner=author,
                price=Decimal("10.00"),
                status="published",
            )
            order = Order.objects.create(
                buyer=buyer,
                book=book,
                amount=Decimal("10.00"),
                status=status_value,
            )
            assert order.status == status_value

    def test_order_ordering(self):
        """Test orders are ordered by created_at descending."""
        buyer = User.objects.create_user(
            email="orderingbuyer@example.com",
            password="secret123",
            first_name="Ordering",
            last_name="Buyer",
            handle="orderingbuyer",
        )
        author = User.objects.create_user(
            email="orderingauthor@example.com",
            password="secret123",
            first_name="Ordering",
            last_name="Author",
            handle="orderingauthor",
        )

        book1 = Book.objects.create(
            title="First Book",
            owner=author,
            price=Decimal("10.00"),
            status="published",
        )
        book2 = Book.objects.create(
            title="Second Book",
            owner=author,
            price=Decimal("10.00"),
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
            amount=Decimal("10.00"),
            status=Order.STATUS_COMPLETED,
        )

        orders = list(Order.objects.filter(buyer=buyer))
        assert orders[0] == order2
        assert orders[1] == order1

    def test_order_related_names(self):
        """Test that related names work for buyer and book."""
        buyer = User.objects.create_user(
            email="relatedbuyer@example.com",
            password="secret123",
            first_name="Related",
            last_name="Buyer",
            handle="relatedbuyer",
        )
        author = User.objects.create_user(
            email="relatedauthor@example.com",
            password="secret123",
            first_name="Related",
            last_name="Author",
            handle="relatedauthor",
        )
        book = Book.objects.create(
            title="Related Book",
            owner=author,
            price=Decimal("25.00"),
            status="published",
        )

        order = Order.objects.create(
            buyer=buyer,
            book=book,
            amount=Decimal("25.00"),
            status=Order.STATUS_COMPLETED,
        )

        assert order in buyer.orders.all()
        assert order in book.orders.all()

    def test_order_amount_decimal_precision(self):
        """Test that order amount supports decimal precision."""
        buyer = User.objects.create_user(
            email="decimalbuyer@example.com",
            password="secret123",
            first_name="Decimal",
            last_name="Buyer",
            handle="decimalbuyer",
        )
        author = User.objects.create_user(
            email="decimalauthor@example.com",
            password="secret123",
            first_name="Decimal",
            last_name="Author",
            handle="decimalauthor",
        )
        book = Book.objects.create(
            title="Decimal Book",
            owner=author,
            price=Decimal("99.99"),
            status="published",
        )

        order = Order.objects.create(
            buyer=buyer,
            book=book,
            amount=Decimal("99.99"),
            status=Order.STATUS_COMPLETED,
        )

        assert order.amount == Decimal("99.99")

    def test_different_buyers_can_purchase_same_book(self):
        """Test that different buyers can purchase the same book."""
        buyer1 = User.objects.create_user(
            email="buyer1@example.com",
            password="secret123",
            first_name="Buyer",
            last_name="One",
            handle="buyerone",
        )
        buyer2 = User.objects.create_user(
            email="buyer2@example.com",
            password="secret123",
            first_name="Buyer",
            last_name="Two",
            handle="buyertwo",
        )
        author = User.objects.create_user(
            email="samebookauthor@example.com",
            password="secret123",
            first_name="Same",
            last_name="Author",
            handle="sameauthor",
        )
        book = Book.objects.create(
            title="Popular Book",
            owner=author,
            price=Decimal("15.00"),
            status="published",
        )

        order1 = Order.objects.create(
            buyer=buyer1,
            book=book,
            amount=Decimal("15.00"),
            status=Order.STATUS_COMPLETED,
        )
        order2 = Order.objects.create(
            buyer=buyer2,
            book=book,
            amount=Decimal("15.00"),
            status=Order.STATUS_COMPLETED,
        )

        assert book.orders.count() == 2
        assert order1 in book.orders.all()
        assert order2 in book.orders.all()
