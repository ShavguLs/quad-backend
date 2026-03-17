import uuid

from django.conf import settings
from django.db import models

from apps.books.models import Book


class Order(models.Model):
    """Purchase record for a book."""

    STATUS_PENDING = 'PENDING'
    STATUS_COMPLETED = 'COMPLETED'
    STATUS_FAILED = 'FAILED'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_FAILED, 'Failed'),
    ]

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text='Primary identifier for the order'
    )
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='orders',
        help_text='User who purchased the book'
    )
    book = models.ForeignKey(
        Book,
        on_delete=models.CASCADE,
        related_name='orders',
        help_text='Book that was purchased'
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text='Purchase amount in GBP'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        help_text='Current order status'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text='Order creation timestamp'
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['buyer', 'book'],
                name='unique_purchase_per_buyer_book'
            )
        ]
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f"Order {self.id} - {self.buyer.email} bought {self.book.title}"
