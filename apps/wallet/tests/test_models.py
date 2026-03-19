"""
Unit tests for wallet models.
"""

import pytest
from decimal import Decimal

from apps.users.models import User
from apps.wallet.models import Transaction, Wallet


pytestmark = [pytest.mark.unit, pytest.mark.django_db]


class TestWalletModel:
    """Test cases for the Wallet model."""

    def test_create_wallet(self):
        """Test wallet creation with default values."""
        user = User.objects.create_user(
            email="wallet@example.com",
            password="secret123",
            first_name="Wallet",
            last_name="User",
            handle="walletuser",
        )
        wallet = Wallet.objects.get(user=user)

        assert wallet.user == user
        assert wallet.balance == Decimal("0.00")
        assert wallet.total_made == Decimal("0.00")
        assert wallet.total_withdrawn == Decimal("0.00")
        assert wallet.created_at is not None
        assert wallet.updated_at is not None

    def test_wallet_str(self):
        """Test wallet string representation."""
        user = User.objects.create_user(
            email="str@example.com",
            password="secret123",
            first_name="Str",
            last_name="User",
            handle="struser",
        )
        wallet = user.wallet
        wallet.balance = Decimal("100.50")
        wallet.save()

        assert str(wallet) == f"Wallet for str@example.com (balance: ₾{wallet.balance})"

    def test_wallet_pending_property_no_pending_transactions(self):
        """Test pending property returns 0 when no pending transactions."""
        user = User.objects.create_user(
            email="nopending@example.com",
            password="secret123",
            first_name="No",
            last_name="Pending",
            handle="nopending",
        )
        wallet = user.wallet

        assert wallet.pending == 0

    def test_wallet_pending_property_with_pending_transactions(self):
        """Test pending property aggregates pending transaction amounts."""
        user = User.objects.create_user(
            email="pending@example.com",
            password="secret123",
            first_name="Pending",
            last_name="User",
            handle="pendinguser",
        )
        wallet = user.wallet

        # Create pending transactions
        Transaction.objects.create(
            wallet=wallet,
            type=Transaction.TYPE_WITHDRAW,
            amount=Decimal("50.00"),
            status=Transaction.STATUS_PENDING,
            label="Pending withdrawal 1",
        )
        Transaction.objects.create(
            wallet=wallet,
            type=Transaction.TYPE_WITHDRAW,
            amount=Decimal("25.50"),
            status=Transaction.STATUS_PENDING,
            label="Pending withdrawal 2",
        )
        # Create a completed transaction (should not count)
        Transaction.objects.create(
            wallet=wallet,
            type=Transaction.TYPE_DEPOSIT,
            amount=Decimal("100.00"),
            status=Transaction.STATUS_COMPLETED,
            label="Completed deposit",
        )

        assert wallet.pending == Decimal("75.50")

    def test_wallet_pending_property_only_pending_status(self):
        """Test pending property only includes PENDING status transactions."""
        user = User.objects.create_user(
            email="status@example.com",
            password="secret123",
            first_name="Status",
            last_name="User",
            handle="statususer",
        )
        wallet = user.wallet

        # Create transactions with different statuses
        Transaction.objects.create(
            wallet=wallet,
            type=Transaction.TYPE_SALE,
            amount=Decimal("10.00"),
            status=Transaction.STATUS_PENDING,
            label="Pending sale",
        )
        Transaction.objects.create(
            wallet=wallet,
            type=Transaction.TYPE_SALE,
            amount=Decimal("20.00"),
            status=Transaction.STATUS_COMPLETED,
            label="Completed sale",
        )
        Transaction.objects.create(
            wallet=wallet,
            type=Transaction.TYPE_SALE,
            amount=Decimal("30.00"),
            status=Transaction.STATUS_FAILED,
            label="Failed sale",
        )

        assert wallet.pending == Decimal("10.00")

    def test_wallet_one_to_one_relationship(self):
        """Test that user can only have one wallet."""
        user = User.objects.create_user(
            email="onetoone@example.com",
            password="secret123",
            first_name="One",
            last_name="ToOne",
            handle="onetoone",
        )
        wallet = user.wallet
        assert wallet is not None

        # Attempting to create another wallet for same user should fail
        with pytest.raises(Exception):  # IntegrityError
            Wallet.objects.create(user=user)

    def test_wallet_ordering(self):
        """Test wallets are ordered by created_at descending."""
        user1 = User.objects.create_user(
            email="user1@example.com",
            password="secret123",
            first_name="User",
            last_name="One",
            handle="userone",
        )
        user2 = User.objects.create_user(
            email="user2@example.com",
            password="secret123",
            first_name="User",
            last_name="Two",
            handle="usertwo",
        )

        wallet1 = user1.wallet
        wallet2 = user2.wallet

        wallets = list(Wallet.objects.all())
        assert wallets[0] == wallet2
        assert wallets[1] == wallet1


class TestTransactionModel:
    """Test cases for the Transaction model."""

    def test_create_transaction(self):
        """Test transaction creation with all fields."""
        user = User.objects.create_user(
            email="transaction@example.com",
            password="secret123",
            first_name="Transaction",
            last_name="User",
            handle="transactionuser",
        )
        wallet = user.wallet

        transaction = Transaction.objects.create(
            wallet=wallet,
            type=Transaction.TYPE_DEPOSIT,
            amount=Decimal("100.00"),
            status=Transaction.STATUS_COMPLETED,
            label="Test deposit",
        )

        assert transaction.wallet == wallet
        assert transaction.type == Transaction.TYPE_DEPOSIT
        assert transaction.amount == Decimal("100.00")
        assert transaction.status == Transaction.STATUS_COMPLETED
        assert transaction.label == "Test deposit"
        assert transaction.created_at is not None

    def test_transaction_str(self):
        """Test transaction string representation."""
        user = User.objects.create_user(
            email="transstr@example.com",
            password="secret123",
            first_name="Trans",
            last_name="Str",
            handle="transstr",
        )
        wallet = user.wallet

        transaction = Transaction.objects.create(
            wallet=wallet,
            type=Transaction.TYPE_SALE,
            amount=Decimal("50.00"),
            status=Transaction.STATUS_PENDING,
            label="Test sale",
        )

        assert str(transaction) == "SALE - ₾50.00 (PENDING)"

    def test_transaction_type_choices(self):
        """Test valid transaction types."""
        user = User.objects.create_user(
            email="types@example.com",
            password="secret123",
            first_name="Types",
            last_name="User",
            handle="typesuser",
        )
        wallet = user.wallet

        # Test all valid types
        for trans_type, expected_label in Transaction.TYPE_CHOICES:
            transaction = Transaction.objects.create(
                wallet=wallet,
                type=trans_type,
                amount=Decimal("10.00"),
                status=Transaction.STATUS_COMPLETED,
                label=f"Test {trans_type}",
            )
            assert transaction.type == trans_type

    def test_transaction_status_choices(self):
        """Test valid transaction statuses."""
        user = User.objects.create_user(
            email="statuses@example.com",
            password="secret123",
            first_name="Statuses",
            last_name="User",
            handle="statusesuser",
        )
        wallet = user.wallet

        # Test all valid statuses
        for status, expected_label in Transaction.STATUS_CHOICES:
            transaction = Transaction.objects.create(
                wallet=wallet,
                type=Transaction.TYPE_DEPOSIT,
                amount=Decimal("10.00"),
                status=status,
                label=f"Test {status}",
            )
            assert transaction.status == status

    def test_transaction_default_status(self):
        """Test that default status is COMPLETED."""
        user = User.objects.create_user(
            email="defaultstatus@example.com",
            password="secret123",
            first_name="Default",
            last_name="Status",
            handle="defaultstatus",
        )
        wallet = user.wallet

        transaction = Transaction.objects.create(
            wallet=wallet,
            type=Transaction.TYPE_DEPOSIT,
            amount=Decimal("10.00"),
            label="Test default status",
        )

        assert transaction.status == Transaction.STATUS_COMPLETED

    def test_transaction_ordering(self):
        """Test transactions are ordered by created_at descending."""
        user = User.objects.create_user(
            email="ordering@example.com",
            password="secret123",
            first_name="Ordering",
            last_name="User",
            handle="orderinguser",
        )
        wallet = user.wallet

        trans1 = Transaction.objects.create(
            wallet=wallet,
            type=Transaction.TYPE_DEPOSIT,
            amount=Decimal("10.00"),
            status=Transaction.STATUS_COMPLETED,
            label="First",
        )
        trans2 = Transaction.objects.create(
            wallet=wallet,
            type=Transaction.TYPE_DEPOSIT,
            amount=Decimal("20.00"),
            status=Transaction.STATUS_COMPLETED,
            label="Second",
        )

        transactions = list(wallet.transactions.all())
        assert transactions[0] == trans2
        assert transactions[1] == trans1

    def test_transaction_related_name(self):
        """Test that wallet.transactions returns related transactions."""
        user = User.objects.create_user(
            email="related@example.com",
            password="secret123",
            first_name="Related",
            last_name="User",
            handle="relateduser",
        )
        wallet = user.wallet

        trans1 = Transaction.objects.create(
            wallet=wallet,
            type=Transaction.TYPE_DEPOSIT,
            amount=Decimal("10.00"),
            status=Transaction.STATUS_COMPLETED,
            label="Transaction 1",
        )
        trans2 = Transaction.objects.create(
            wallet=wallet,
            type=Transaction.TYPE_SALE,
            amount=Decimal("20.00"),
            status=Transaction.STATUS_COMPLETED,
            label="Transaction 2",
        )

        assert wallet.transactions.count() == 2
        assert trans1 in wallet.transactions.all()
        assert trans2 in wallet.transactions.all()

    def test_transaction_decimal_precision(self):
        """Test that transaction amount supports decimal precision."""
        user = User.objects.create_user(
            email="decimal@example.com",
            password="secret123",
            first_name="Decimal",
            last_name="User",
            handle="decimaluser",
        )
        wallet = user.wallet

        transaction = Transaction.objects.create(
            wallet=wallet,
            type=Transaction.TYPE_DEPOSIT,
            amount=Decimal("99.99"),
            status=Transaction.STATUS_COMPLETED,
            label="Decimal test",
        )

        assert transaction.amount == Decimal("99.99")
