"""
Unit tests for wallet serializers.
"""

import pytest
from decimal import Decimal
from unittest.mock import Mock

from rest_framework.test import APIRequestFactory

from apps.users.models import User
from apps.wallet.models import Transaction, Wallet
from apps.wallet.serializers import (
    TransactionSerializer,
    WalletSerializer,
    WalletStatsSerializer,
)


pytestmark = [pytest.mark.unit, pytest.mark.django_db]


class TestWalletSerializer:
    """Test cases for the WalletSerializer."""

    def setup_method(self):
        self.factory = APIRequestFactory()

    def test_serialize_wallet(self):
        """Test basic wallet serialization with formatted fields."""
        user = User.objects.create_user(
            email="wallet@example.com",
            password="secret123",
            first_name="Wallet",
            last_name="User",
            handle="walletuser",
        )
        wallet = Wallet.objects.get(user=user)
        wallet.balance = Decimal("150.50")
        wallet.total_made = Decimal("500.00")
        wallet.total_withdrawn = Decimal("100.00")
        wallet.save()

        serializer = WalletSerializer(wallet)
        data = serializer.data

        assert data["balance"] == "₾150.50"
        assert data["total_made"] == "₾500.00"
        assert data["total_withdrawn"] == "₾100.00"

    def test_serialize_wallet_zero_values(self):
        """Test wallet serialization with zero values."""
        user = User.objects.create_user(
            email="zerowallet@example.com",
            password="secret123",
            first_name="Zero",
            last_name="Wallet",
            handle="zerowallet",
        )
        wallet = user.wallet

        serializer = WalletSerializer(wallet)
        data = serializer.data

        assert data["balance"] == "₾0.00"
        assert data["total_made"] == "₾0.00"
        assert data["total_withdrawn"] == "₾0.00"

    def test_serialize_wallet_decimal_rounding(self):
        """Test wallet serialization rounds decimals to 2 places."""
        user = User.objects.create_user(
            email="decimal@example.com",
            password="secret123",
            first_name="Decimal",
            last_name="Wallet",
            handle="decimalwallet",
        )
        wallet = Wallet.objects.get(user=user)
        wallet.balance = Decimal("99.999")
        wallet.total_made = Decimal("0.001")
        wallet.total_withdrawn = Decimal("123.456")
        wallet.save()

        serializer = WalletSerializer(wallet)
        data = serializer.data

        # The serializer formats with .2f, which rounds
        assert data["balance"] == "₾100.00"
        assert data["total_made"] == "₾0.00"
        assert data["total_withdrawn"] == "₾123.46"

    def test_wallet_serializer_fields(self):
        """Test that serializer includes expected fields."""
        user = User.objects.create_user(
            email="fields@example.com",
            password="secret123",
            first_name="Fields",
            last_name="Wallet",
            handle="fieldswallet",
        )
        wallet = user.wallet

        serializer = WalletSerializer(wallet)

        expected_fields = {"balance", "total_made", "total_withdrawn"}
        assert set(serializer.data.keys()) == expected_fields


class TestWalletStatsSerializer:
    """Test cases for the WalletStatsSerializer."""

    def setup_method(self):
        self.factory = APIRequestFactory()

    def test_serialize_wallet_stats(self):
        """Test wallet stats serialization with all fields."""
        user = User.objects.create_user(
            email="stats@example.com",
            password="secret123",
            first_name="Stats",
            last_name="User",
            handle="statsuser",
        )
        wallet = Wallet.objects.get(user=user)
        wallet.balance = Decimal("200.00")
        wallet.total_made = Decimal("1000.00")
        wallet.total_withdrawn = Decimal("300.00")
        wallet.save()

        # Add a pending transaction
        Transaction.objects.create(
            wallet=wallet,
            type=Transaction.TYPE_WITHDRAW,
            amount=Decimal("50.00"),
            status=Transaction.STATUS_PENDING,
            label="Pending withdrawal",
        )

        serializer = WalletStatsSerializer(wallet)
        data = serializer.data

        assert data["balance"] == "₾200.00"
        assert data["total_made"] == "₾1000.00"
        assert data["pending"] == "₾50.00"
        assert data["total_withdrawn"] == "₾300.00"

    def test_serialize_wallet_stats_no_pending(self):
        """Test wallet stats with no pending transactions."""
        user = User.objects.create_user(
            email="nopending@example.com",
            password="secret123",
            first_name="No",
            last_name="Pending",
            handle="nopending",
        )
        wallet = Wallet.objects.get(user=user)
        wallet.balance = Decimal("50.00")
        wallet.total_made = Decimal("200.00")
        wallet.total_withdrawn = Decimal("50.00")
        wallet.save()

        serializer = WalletStatsSerializer(wallet)
        data = serializer.data

        assert data["pending"] == "₾0.00"

    def test_wallet_stats_serializer_fields(self):
        """Test that stats serializer includes expected fields."""
        user = User.objects.create_user(
            email="statsfields@example.com",
            password="secret123",
            first_name="Stats",
            last_name="Fields",
            handle="statsfields",
        )
        wallet = user.wallet

        serializer = WalletStatsSerializer(wallet)

        expected_fields = {"balance", "total_made", "pending", "total_withdrawn"}
        assert set(serializer.data.keys()) == expected_fields


class TestTransactionSerializer:
    """Test cases for the TransactionSerializer."""

    def setup_method(self):
        self.factory = APIRequestFactory()

    def test_serialize_deposit_transaction(self):
        """Test serialization of deposit transaction with + prefix."""
        user = User.objects.create_user(
            email="deposit@example.com",
            password="secret123",
            first_name="Deposit",
            last_name="User",
            handle="deposituser",
        )
        wallet = user.wallet
        transaction = Transaction.objects.create(
            wallet=wallet,
            type=Transaction.TYPE_DEPOSIT,
            amount=Decimal("100.00"),
            status=Transaction.STATUS_COMPLETED,
            label="Manual deposit",
        )

        serializer = TransactionSerializer(transaction)
        data = serializer.data

        assert data["amount"] == "+₾100.00"
        assert data["type"] == Transaction.TYPE_DEPOSIT
        assert data["status"] == Transaction.STATUS_COMPLETED
        assert data["label"] == "Manual deposit"
        assert data["date"] is not None
        assert "id" in data

    def test_serialize_sale_transaction(self):
        """Test serialization of sale transaction with + prefix."""
        user = User.objects.create_user(
            email="sale@example.com",
            password="secret123",
            first_name="Sale",
            last_name="User",
            handle="saleuser",
        )
        wallet = user.wallet
        transaction = Transaction.objects.create(
            wallet=wallet,
            type=Transaction.TYPE_SALE,
            amount=Decimal("25.50"),
            status=Transaction.STATUS_COMPLETED,
            label="Sale: Test Book",
        )

        serializer = TransactionSerializer(transaction)
        data = serializer.data

        assert data["amount"] == "+₾25.50"
        assert data["type"] == Transaction.TYPE_SALE

    def test_serialize_withdraw_transaction(self):
        """Test serialization of withdraw transaction with - prefix."""
        user = User.objects.create_user(
            email="withdraw@example.com",
            password="secret123",
            first_name="Withdraw",
            last_name="User",
            handle="withdrawuser",
        )
        wallet = user.wallet
        transaction = Transaction.objects.create(
            wallet=wallet,
            type=Transaction.TYPE_WITHDRAW,
            amount=Decimal("50.00"),
            status=Transaction.STATUS_COMPLETED,
            label="Purchase: Test Book",
        )

        serializer = TransactionSerializer(transaction)
        data = serializer.data

        assert data["amount"] == "-₾50.00"
        assert data["type"] == Transaction.TYPE_WITHDRAW

    def test_serialize_multiple_transactions(self):
        """Test serialization of multiple transactions."""
        user = User.objects.create_user(
            email="multiple@example.com",
            password="secret123",
            first_name="Multiple",
            last_name="User",
            handle="multipleuser",
        )
        wallet = user.wallet

        trans1 = Transaction.objects.create(
            wallet=wallet,
            type=Transaction.TYPE_DEPOSIT,
            amount=Decimal("100.00"),
            status=Transaction.STATUS_COMPLETED,
            label="Deposit",
        )
        trans2 = Transaction.objects.create(
            wallet=wallet,
            type=Transaction.TYPE_SALE,
            amount=Decimal("30.00"),
            status=Transaction.STATUS_COMPLETED,
            label="Sale",
        )
        trans3 = Transaction.objects.create(
            wallet=wallet,
            type=Transaction.TYPE_WITHDRAW,
            amount=Decimal("20.00"),
            status=Transaction.STATUS_COMPLETED,
            label="Withdraw",
        )

        transactions = wallet.transactions.all()
        serializer = TransactionSerializer(transactions, many=True)
        data = serializer.data

        assert len(data) == 3
        # Note: transactions are ordered by created_at descending
        assert data[0]["amount"] == "-₾20.00"
        assert data[1]["amount"] == "+₾30.00"
        assert data[2]["amount"] == "+₾100.00"

    def test_transaction_serializer_fields(self):
        """Test that transaction serializer includes expected fields."""
        user = User.objects.create_user(
            email="transfields@example.com",
            password="secret123",
            first_name="Trans",
            last_name="Fields",
            handle="transfields",
        )
        wallet = user.wallet
        transaction = Transaction.objects.create(
            wallet=wallet,
            type=Transaction.TYPE_DEPOSIT,
            amount=Decimal("50.00"),
            status=Transaction.STATUS_COMPLETED,
            label="Test",
        )

        serializer = TransactionSerializer(transaction)

        expected_fields = {"id", "type", "amount", "status", "label", "date"}
        assert set(serializer.data.keys()) == expected_fields

    def test_transaction_date_field(self):
        """Test that date field is the created_at datetime."""
        user = User.objects.create_user(
            email="date@example.com",
            password="secret123",
            first_name="Date",
            last_name="User",
            handle="dateuser",
        )
        wallet = user.wallet
        transaction = Transaction.objects.create(
            wallet=wallet,
            type=Transaction.TYPE_DEPOSIT,
            amount=Decimal("50.00"),
            status=Transaction.STATUS_COMPLETED,
            label="Date test",
        )

        serializer = TransactionSerializer(transaction)
        data = serializer.data

        # DateTimeField serializes to ISO format string
        assert data["date"] is not None
        assert isinstance(data["date"], str)
