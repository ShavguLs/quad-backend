"""
Wallet models for Syndicate platform.

Provides Wallet and Transaction models for user balance tracking.
"""

from decimal import Decimal

from django.conf import settings
from django.db import models


class Wallet(models.Model):
    """User wallet with GBP balance tracking."""
    
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='wallet'
    )
    balance = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        help_text='Current GBP balance'
    )
    total_made = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        help_text='Total revenue earned from sales'
    )
    total_withdrawn = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        help_text='Total amount withdrawn'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Wallet'
        verbose_name_plural = 'Wallets'
        ordering = ['-created_at']
    
    def __str__(self) -> str:
        return f"Wallet for {self.user.email} (balance: ₾{self.balance})"
    
    @property
    def pending(self) -> Decimal:
        """Calculate pending transactions total."""
        pending_total = self.transactions.filter(
            status=Transaction.STATUS_PENDING
        ).aggregate(
            total=models.Sum('amount')
        )['total']
        return pending_total or Decimal('0.00')


class Transaction(models.Model):
    """Transaction record for wallet operations."""
    
    TYPE_SALE = 'SALE'
    TYPE_DEPOSIT = 'DEPOSIT'
    TYPE_WITHDRAW = 'WITHDRAW'
    
    TYPE_CHOICES = [
        (TYPE_SALE, 'Sale'),
        (TYPE_DEPOSIT, 'Deposit'),
        (TYPE_WITHDRAW, 'Withdraw'),
    ]
    
    STATUS_PENDING = 'PENDING'
    STATUS_COMPLETED = 'COMPLETED'
    STATUS_FAILED = 'FAILED'
    
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_FAILED, 'Failed'),
    ]
    
    wallet = models.ForeignKey(
        Wallet,
        on_delete=models.CASCADE,
        related_name='transactions'
    )
    type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_COMPLETED
    )
    label = models.CharField(
        max_length=255,
        help_text='Human-readable description'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = 'Transaction'
        verbose_name_plural = 'Transactions'
        ordering = ['-created_at']
    
    def __str__(self) -> str:
        return f"{self.type} - ₾{self.amount} ({self.status})"
