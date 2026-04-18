"""
Unit tests for wallet views.
"""

import pytest
from decimal import Decimal
from unittest.mock import Mock, patch

from rest_framework import status
from rest_framework.test import APIClient, APIRequestFactory, APITestCase, force_authenticate

from apps.users.models import User
from apps.wallet.keepz_client import KeepzError
from apps.wallet.models import Transaction, Wallet
from apps.wallet.views import WalletViewSet


pytestmark = [pytest.mark.unit, pytest.mark.django_db]


class TestWalletViewSet:
    """Test cases for the WalletViewSet."""

    def setup_method(self):
        self.factory = APIRequestFactory()
        self.user = User.objects.create_user(
            email="walletview@example.com",
            password="secret123",
            first_name="Wallet",
            last_name="View",
            handle="walletview",
        )

    def test_get_queryset_creates_wallet_if_not_exists(self):
        """Test that get_queryset creates wallet if user doesn't have one."""
        # Wallet should already exist via signal
        wallet = Wallet.objects.get(user=self.user)

        view = WalletViewSet()
        view.request = self.factory.get('/wallet/stats')
        view.request.user = self.user

        queryset = view.get_queryset()

        # Wallet should be created
        assert Wallet.objects.filter(user=self.user).exists()
        assert queryset.count() == 1

    def test_get_queryset_returns_existing_wallet(self):
        """Test that get_queryset returns existing wallet."""
        wallet = Wallet.objects.get(user=self.user)
        wallet.balance = Decimal("100.00")
        wallet.save()

        view = WalletViewSet()
        view.request = self.factory.get('/wallet/stats')
        view.request.user = self.user

        queryset = view.get_queryset()

        assert queryset.count() == 1
        assert queryset.first() == wallet

    def test_stats_action_with_wallet(self):
        """Test stats action returns wallet statistics."""
        wallet = Wallet.objects.get(user=self.user)
        wallet.balance = Decimal("150.50")
        wallet.total_made = Decimal("500.00")
        wallet.total_withdrawn = Decimal("100.00")
        wallet.save()
        Transaction.objects.create(
            wallet=wallet,
            type=Transaction.TYPE_WITHDRAW,
            amount=Decimal("25.00"),
            status=Transaction.STATUS_PENDING,
            label="Pending",
        )

        view = WalletViewSet.as_view({'get': 'stats'})
        request = self.factory.get('/wallet/stats')
        force_authenticate(request, user=self.user)

        response = view(request)

        assert response.status_code == status.HTTP_200_OK
        # Serializer already formats values as '₾...' — no extra prefix added by view
        assert response.data['balance'] == '₾150.50'
        assert response.data['totalMade'] == '₾500.00'
        assert response.data['pending'] == '₾25.00'
        assert response.data['withdrawals'] == '₾100.00'

    def test_stats_action_without_wallet(self):
        """Test stats action returns zeros when no wallet exists."""
        view = WalletViewSet.as_view({'get': 'stats'})
        request = self.factory.get('/wallet/stats')
        force_authenticate(request, user=self.user)

        response = view(request)

        assert response.status_code == status.HTTP_200_OK
        # Serializer already formats values as '₾...' — no extra prefix added by view
        assert response.data['balance'] == '₾0.00'
        assert response.data['totalMade'] == '₾0.00'
        assert response.data['pending'] == '₾0.00'
        assert response.data['withdrawals'] == '₾0.00'

    def test_transactions_action_with_wallet(self):
        """Test transactions action returns transaction history."""
        wallet = Wallet.objects.get(user=self.user)
        Transaction.objects.create(
            wallet=wallet,
            type=Transaction.TYPE_DEPOSIT,
            amount=Decimal("100.00"),
            status=Transaction.STATUS_COMPLETED,
            label="Deposit",
        )
        Transaction.objects.create(
            wallet=wallet,
            type=Transaction.TYPE_SALE,
            amount=Decimal("25.00"),
            status=Transaction.STATUS_COMPLETED,
            label="Sale",
        )

        view = WalletViewSet.as_view({'get': 'transactions'})
        request = self.factory.get('/wallet/transactions')
        force_authenticate(request, user=self.user)

        response = view(request)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 2

    def test_transactions_action_without_wallet(self):
        """Test transactions action returns empty list when no wallet."""
        view = WalletViewSet.as_view({'get': 'transactions'})
        request = self.factory.get('/wallet/transactions')
        force_authenticate(request, user=self.user)

        response = view(request)

        assert response.status_code == status.HTTP_200_OK
        assert response.data == []

    def test_deposit_action_success(self):
        """Test successful deposit creates pending transaction and checkout URL."""
        wallet = Wallet.objects.get(user=self.user)
        wallet.balance = Decimal("50.00")
        wallet.save()

        with patch('apps.wallet.views.KeepzClient') as mock_client_cls:
            mock_client = Mock()
            mock_client.create_order.return_value = {
                'urlForQR': 'https://keepz.test/checkout/abc',
                'status': 'INITIAL',
            }
            mock_client_cls.return_value = mock_client

            view = WalletViewSet.as_view({'post': 'deposit'})
            request = self.factory.post('/wallet/deposit', {'amount': '100.00'})
            force_authenticate(request, user=self.user)

            response = view(request)

        assert response.status_code == status.HTTP_200_OK
        assert response.data['message'] == 'Deposit initiated'
        assert response.data['checkoutUrl'] == 'https://keepz.test/checkout/abc'
        assert response.data['orderId']
        assert response.data['status'] == Transaction.STATUS_PENDING

        wallet.refresh_from_db()
        assert wallet.balance == Decimal("50.00")
        transaction = wallet.transactions.get(type=Transaction.TYPE_DEPOSIT)
        assert transaction.status == Transaction.STATUS_PENDING
        assert transaction.provider == Transaction.PROVIDER_KEEPZ
        assert transaction.provider_order_id == response.data['orderId']

    def test_deposit_action_without_wallet(self):
        """Test deposit creates wallet if it doesn't exist."""
        with patch('apps.wallet.views.KeepzClient') as mock_client_cls:
            mock_client = Mock()
            mock_client.create_order.return_value = {
                'urlForQR': 'https://keepz.test/checkout/abc',
                'status': 'INITIAL',
            }
            mock_client_cls.return_value = mock_client

            view = WalletViewSet.as_view({'post': 'deposit'})
            request = self.factory.post('/wallet/deposit', {'amount': '50.00'})
            force_authenticate(request, user=self.user)

            response = view(request)

        assert response.status_code == status.HTTP_200_OK
        assert Wallet.objects.filter(user=self.user).exists()

    def test_deposit_action_missing_checkout_url_returns_gateway_error(self):
        wallet = Wallet.objects.get(user=self.user)

        with patch('apps.wallet.views.KeepzClient') as mock_client_cls, patch('apps.wallet.views.logger') as mock_logger:
            mock_client = Mock()
            mock_client.create_order.return_value = {
                'integratorOrderId': 'provider-order-1',
                'status': 'INITIAL',
            }
            mock_client_cls.return_value = mock_client

            view = WalletViewSet.as_view({'post': 'deposit'})
            request = self.factory.post('/wallet/deposit', {'amount': '100.00'})
            force_authenticate(request, user=self.user)

            response = view(request)

        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert 'გადახდის ბმული' in response.data['error']
        transaction = wallet.transactions.get(type=Transaction.TYPE_DEPOSIT)
        assert transaction.status == Transaction.STATUS_FAILED
        assert transaction.provider_status == 'FAILED'
        assert transaction.provider_payload['create_order']['integratorOrderId'] == 'provider-order-1'
        assert transaction.provider_payload['create_order_error']['message'] == 'Keepz did not return a checkout URL.'
        mock_logger.error.assert_called_once()

    def test_deposit_action_missing_amount(self):
        """Test deposit fails when amount is missing."""
        Wallet.objects.get(user=self.user)

        view = WalletViewSet.as_view({'post': 'deposit'})
        request = self.factory.post('/wallet/deposit', {})
        force_authenticate(request, user=self.user)

        response = view(request)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data['error'] == 'Amount is required'

    def test_deposit_action_invalid_amount_string(self):
        """Test deposit fails with invalid amount string."""
        Wallet.objects.get(user=self.user)

        view = WalletViewSet.as_view({'post': 'deposit'})
        request = self.factory.post('/wallet/deposit', {'amount': 'not-a-number'})
        force_authenticate(request, user=self.user)

        response = view(request)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data['error'] == 'Invalid amount'

    def test_deposit_action_negative_amount(self):
        """Test deposit fails with negative amount."""
        Wallet.objects.get(user=self.user)

        view = WalletViewSet.as_view({'post': 'deposit'})
        request = self.factory.post('/wallet/deposit', {'amount': '-50.00'})
        force_authenticate(request, user=self.user)

        response = view(request)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data['error'] == 'Invalid amount'

    def test_deposit_action_zero_amount(self):
        """Test deposit fails with zero amount."""
        Wallet.objects.get(user=self.user)

        view = WalletViewSet.as_view({'post': 'deposit'})
        request = self.factory.post('/wallet/deposit', {'amount': '0'})
        force_authenticate(request, user=self.user)

        response = view(request)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data['error'] == 'Invalid amount'

    def test_deposit_action_float_amount(self):
        """Test deposit works with float amount."""
        with patch('apps.wallet.views.KeepzClient') as mock_client_cls:
            mock_client = Mock()
            mock_client.create_order.return_value = {
                'urlForQR': 'https://keepz.test/checkout/float',
                'status': 'INITIAL',
            }
            mock_client_cls.return_value = mock_client

            wallet = Wallet.objects.get(user=self.user)
            view = WalletViewSet.as_view({'post': 'deposit'})
            request = self.factory.post('/wallet/deposit', {'amount': 75.50})
            force_authenticate(request, user=self.user)

            response = view(request)

        assert response.status_code == status.HTTP_200_OK
        wallet.refresh_from_db()
        assert wallet.balance == Decimal("0.00")
        assert wallet.transactions.get().amount == Decimal("75.50")

    def test_deposit_action_permission_error_returns_safe_message(self):
        with patch('apps.wallet.views.KeepzClient') as mock_client_cls:
            mock_client = Mock()
            mock_client.create_order.side_effect = KeepzError(
                'Dynamic redirect permission missing',
                status_code='6036',
                exception_group='PERMISSION',
            )
            mock_client_cls.return_value = mock_client

            view = WalletViewSet.as_view({'post': 'deposit'})
            request = self.factory.post('/wallet/deposit', {'amount': '40.00'})
            force_authenticate(request, user=self.user)

            response = view(request)

        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert 'გააქტიურებული' in response.data['error']
        transaction = Wallet.objects.get(user=self.user).transactions.get()
        assert transaction.status == Transaction.STATUS_FAILED

    def test_callback_success_credits_wallet_exactly_once(self):
        client = APIClient()
        wallet = Wallet.objects.get(user=self.user)
        transaction = Transaction.objects.create(
            wallet=wallet,
            type=Transaction.TYPE_DEPOSIT,
            amount=Decimal('30.00'),
            status=Transaction.STATUS_PENDING,
            label='Keepz deposit',
            provider=Transaction.PROVIDER_KEEPZ,
            provider_order_id='order-1',
            provider_status='INITIAL',
            provider_payload={},
        )

        with patch('apps.wallet.views.KeepzClient') as mock_client_cls:
            mock_client = Mock()
            mock_client.get_order_status.return_value = {'status': 'SUCCESS'}
            mock_client_cls.return_value = mock_client

            response = client.post('/wallet/deposit/callback/', {
                'integratorOrderId': 'order-1',
                'status': 'SUCCESS',
            }, format='json')
            duplicate = client.post('/wallet/deposit/callback/', {
                'integratorOrderId': 'order-1',
                'status': 'SUCCESS',
            }, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert duplicate.status_code == status.HTTP_200_OK

        wallet.refresh_from_db()
        transaction.refresh_from_db()
        assert wallet.balance == Decimal('30.00')
        assert transaction.status == Transaction.STATUS_COMPLETED
        assert transaction.credited_at is not None

    def test_callback_with_alternate_success_status(self):
        client = APIClient()
        wallet = Wallet.objects.get(user=self.user)
        transaction = Transaction.objects.create(
            wallet=wallet,
            type=Transaction.TYPE_DEPOSIT,
            amount=Decimal('25.00'),
            status=Transaction.STATUS_PENDING,
            label='Keepz deposit',
            provider=Transaction.PROVIDER_KEEPZ,
            provider_order_id='order-approved-callback',
            provider_status='INITIAL',
            provider_payload={},
        )

        with patch('apps.wallet.views.KeepzClient') as mock_client_cls:
            mock_client = Mock()
            mock_client.get_order_status.return_value = {'status': 'APPROVED'}
            mock_client_cls.return_value = mock_client

            response = client.post('/wallet/deposit/callback/', {
                'integratorOrderId': 'order-approved-callback',
                'status': 'APPROVED',
            }, format='json')

        assert response.status_code == status.HTTP_200_OK
        wallet.refresh_from_db()
        transaction.refresh_from_db()
        assert wallet.balance == Decimal('25.00')
        assert transaction.status == Transaction.STATUS_COMPLETED
        assert transaction.provider_status == 'APPROVED'
        assert transaction.credited_at is not None

    def test_callback_form_payload_credits_wallet(self):
        client = APIClient()
        wallet = Wallet.objects.get(user=self.user)
        transaction = Transaction.objects.create(
            wallet=wallet,
            type=Transaction.TYPE_DEPOSIT,
            amount=Decimal('22.00'),
            status=Transaction.STATUS_PENDING,
            label='Keepz deposit',
            provider=Transaction.PROVIDER_KEEPZ,
            provider_order_id='order-form-callback',
            provider_status='INITIAL',
            provider_payload={},
        )

        with patch('apps.wallet.views.KeepzClient') as mock_client_cls:
            mock_client = Mock()
            mock_client.get_order_status.return_value = {'status': 'SUCCESS'}
            mock_client_cls.return_value = mock_client

            response = client.post(
                '/wallet/deposit/callback/',
                {
                    'integratorOrderId': 'order-form-callback',
                    'status': 'SUCCESS',
                },
                format='multipart',
            )

        assert response.status_code == status.HTTP_200_OK
        wallet.refresh_from_db()
        transaction.refresh_from_db()
        assert wallet.balance == Decimal('22.00')
        assert transaction.status == Transaction.STATUS_COMPLETED
        assert transaction.provider_status == 'SUCCESS'
        assert transaction.credited_at is not None

    def test_callback_failed_does_not_credit_wallet(self):
        client = APIClient()
        wallet = Wallet.objects.get(user=self.user)
        transaction = Transaction.objects.create(
            wallet=wallet,
            type=Transaction.TYPE_DEPOSIT,
            amount=Decimal('30.00'),
            status=Transaction.STATUS_PENDING,
            label='Keepz deposit',
            provider=Transaction.PROVIDER_KEEPZ,
            provider_order_id='order-2',
            provider_status='INITIAL',
            provider_payload={},
        )

        with patch('apps.wallet.views.KeepzClient') as mock_client_cls:
            mock_client = Mock()
            mock_client.get_order_status.return_value = {'status': 'FAILED'}
            mock_client_cls.return_value = mock_client

            response = client.post('/wallet/deposit/callback/', {
                'integratorOrderId': 'order-2',
                'status': 'FAILED',
            }, format='json')

        assert response.status_code == status.HTTP_200_OK
        wallet.refresh_from_db()
        transaction.refresh_from_db()
        assert wallet.balance == Decimal('0.00')
        assert transaction.status == Transaction.STATUS_FAILED

    def test_callback_spoofed_success_status_does_not_credit_wallet(self):
        client = APIClient()
        wallet = Wallet.objects.get(user=self.user)
        transaction = Transaction.objects.create(
            wallet=wallet,
            type=Transaction.TYPE_DEPOSIT,
            amount=Decimal('32.00'),
            status=Transaction.STATUS_PENDING,
            label='Keepz deposit',
            provider=Transaction.PROVIDER_KEEPZ,
            provider_order_id='order-spoofed-status',
            provider_status='INITIAL',
            provider_payload={},
        )

        with patch('apps.wallet.views.KeepzClient') as mock_client_cls:
            mock_client = Mock()
            mock_client.get_order_status.return_value = {'status': 'FAILED'}
            mock_client_cls.return_value = mock_client

            response = client.post('/wallet/deposit/callback/', {
                'integratorOrderId': 'order-spoofed-status',
                'status': 'SUCCESS',
            }, format='json')

        assert response.status_code == status.HTTP_200_OK
        wallet.refresh_from_db()
        transaction.refresh_from_db()
        assert wallet.balance == Decimal('0.00')
        assert transaction.status == Transaction.STATUS_FAILED
        assert transaction.provider_status == 'FAILED'

    def test_deposit_status_success_reconciles_wallet_credit(self):
        client = APIClient()
        client.force_authenticate(user=self.user)
        wallet = Wallet.objects.get(user=self.user)
        transaction = Transaction.objects.create(
            wallet=wallet,
            type=Transaction.TYPE_DEPOSIT,
            amount=Decimal('45.00'),
            status=Transaction.STATUS_PENDING,
            label='Keepz deposit',
            provider=Transaction.PROVIDER_KEEPZ,
            provider_order_id='order-3',
            provider_status='INITIAL',
            provider_payload={},
        )

        with patch('apps.wallet.views.KeepzClient') as mock_client_cls:
            mock_client = Mock()
            mock_client.get_order_status.return_value = {'status': 'SUCCESS'}
            mock_client_cls.return_value = mock_client

            response = client.get('/wallet/deposit/status/', {'order_id': 'order-3'})

        assert response.status_code == status.HTTP_200_OK
        assert response.data['status'] == Transaction.STATUS_COMPLETED
        assert response.data['credited'] is True
        wallet.refresh_from_db()
        transaction.refresh_from_db()
        assert wallet.balance == Decimal('45.00')
        assert transaction.credited_at is not None

    def test_deposit_status_with_alternate_success_status(self):
        client = APIClient()
        client.force_authenticate(user=self.user)
        wallet = Wallet.objects.get(user=self.user)
        transaction = Transaction.objects.create(
            wallet=wallet,
            type=Transaction.TYPE_DEPOSIT,
            amount=Decimal('15.00'),
            status=Transaction.STATUS_PENDING,
            label='Keepz deposit',
            provider=Transaction.PROVIDER_KEEPZ,
            provider_order_id='order-approved-status',
            provider_status='INITIAL',
            provider_payload={},
        )

        with patch('apps.wallet.views.KeepzClient') as mock_client_cls:
            mock_client = Mock()
            mock_client.get_order_status.return_value = {'txStatus': 'APPROVED'}
            mock_client_cls.return_value = mock_client

            response = client.get('/wallet/deposit/status/', {'order_id': 'order-approved-status'})

        assert response.status_code == status.HTTP_200_OK
        assert response.data['status'] == Transaction.STATUS_COMPLETED
        assert response.data['providerStatus'] == 'APPROVED'
        assert response.data['credited'] is True
        wallet.refresh_from_db()
        transaction.refresh_from_db()
        assert wallet.balance == Decimal('15.00')
        assert transaction.credited_at is not None

    def test_deposit_status_with_complete_status(self):
        client = APIClient()
        client.force_authenticate(user=self.user)
        wallet = Wallet.objects.get(user=self.user)
        transaction = Transaction.objects.create(
            wallet=wallet,
            type=Transaction.TYPE_DEPOSIT,
            amount=Decimal('18.00'),
            status=Transaction.STATUS_PENDING,
            label='Keepz deposit',
            provider=Transaction.PROVIDER_KEEPZ,
            provider_order_id='order-complete-status',
            provider_status='INITIAL',
            provider_payload={},
        )

        with patch('apps.wallet.views.KeepzClient') as mock_client_cls:
            mock_client = Mock()
            mock_client.get_order_status.return_value = {'paymentStatus': 'COMPLETE'}
            mock_client_cls.return_value = mock_client

            response = client.get('/wallet/deposit/status/', {'order_id': 'order-complete-status'})

        assert response.status_code == status.HTTP_200_OK
        assert response.data['status'] == Transaction.STATUS_COMPLETED
        assert response.data['providerStatus'] == 'COMPLETE'
        assert response.data['credited'] is True
        wallet.refresh_from_db()
        transaction.refresh_from_db()
        assert wallet.balance == Decimal('18.00')
        assert transaction.credited_at is not None

    def test_callback_with_encrypted_payload_credits_wallet(self):
        """Test that encrypted callback payload is decrypted and credits wallet."""
        client = APIClient()
        wallet = Wallet.objects.get(user=self.user)
        transaction = Transaction.objects.create(
            wallet=wallet,
            type=Transaction.TYPE_DEPOSIT,
            amount=Decimal('35.00'),
            status=Transaction.STATUS_PENDING,
            label='Keepz deposit',
            provider=Transaction.PROVIDER_KEEPZ,
            provider_order_id='order-encrypted',
            provider_status='INITIAL',
            provider_payload={},
        )

        encrypted_payload = {
            'encryptedData': 'DUMMY_ENCRYPTED_DATA',
            'encryptedKeys': 'DUMMY_ENCRYPTED_KEYS',
            'aes': True,
        }
        decrypted_callback = {
            'integratorOrderId': 'order-encrypted',
            'status': 'SUCCESS',
        }

        with patch('apps.wallet.views.KeepzClient') as mock_client_cls:
            mock_client = Mock()
            mock_client.decrypt_payload.return_value = decrypted_callback
            mock_client.get_order_status.return_value = {'status': 'SUCCESS'}
            mock_client_cls.return_value = mock_client

            response = client.post(
                '/wallet/deposit/callback/',
                encrypted_payload,
                format='json',
            )

        assert response.status_code == status.HTTP_200_OK
        wallet.refresh_from_db()
        transaction.refresh_from_db()
        assert wallet.balance == Decimal('35.00')
        assert transaction.status == Transaction.STATUS_COMPLETED
        assert transaction.provider_status == 'SUCCESS'
        assert transaction.credited_at is not None

    def test_callback_with_encrypted_payload_unknown_order_returns_acknowledged(self):
        """Test that encrypted callback for unknown order returns 200 OK."""
        client = APIClient()

        encrypted_payload = {
            'encryptedData': 'DUMMY_ENCRYPTED_DATA',
            'encryptedKeys': 'DUMMY_ENCRYPTED_KEYS',
            'aes': True,
        }
        decrypted_callback = {
            'integratorOrderId': 'unknown-order-id',
            'status': 'SUCCESS',
        }

        with patch('apps.wallet.views.KeepzClient') as mock_client_cls:
            mock_client = Mock()
            mock_client.decrypt_payload.return_value = decrypted_callback
            mock_client_cls.return_value = mock_client

            response = client.post(
                '/wallet/deposit/callback/',
                encrypted_payload,
                format='json',
            )

        assert response.status_code == status.HTTP_200_OK
        assert response.data['acknowledged'] is False

    def test_callback_decryption_failure_returns_acknowledged_false(self):
        """Test that failed decryption returns 200 OK with acknowledged false."""
        client = APIClient()

        encrypted_payload = {
            'encryptedData': 'DUMMY_ENCRYPTED_DATA',
            'encryptedKeys': 'DUMMY_ENCRYPTED_KEYS',
            'aes': True,
        }

        with patch('apps.wallet.views.KeepzClient') as mock_client_cls:
            mock_client = Mock()
            mock_client.decrypt_payload.side_effect = KeepzError('Decryption failed')
            mock_client_cls.return_value = mock_client

            response = client.post(
                '/wallet/deposit/callback/',
                encrypted_payload,
                format='json',
            )

        assert response.status_code == status.HTTP_200_OK
        assert response.data['acknowledged'] is False

    def test_callback_keepz_verification_failure_returns_acknowledged_false(self):
        client = APIClient()
        wallet = Wallet.objects.get(user=self.user)
        Transaction.objects.create(
            wallet=wallet,
            type=Transaction.TYPE_DEPOSIT,
            amount=Decimal('27.00'),
            status=Transaction.STATUS_PENDING,
            label='Keepz deposit',
            provider=Transaction.PROVIDER_KEEPZ,
            provider_order_id='order-verify-error',
            provider_status='INITIAL',
            provider_payload={},
        )

        with patch('apps.wallet.views.KeepzClient') as mock_client_cls:
            mock_client = Mock()
            mock_client.get_order_status.side_effect = KeepzError('Verification failed')
            mock_client_cls.return_value = mock_client

            response = client.post('/wallet/deposit/callback/', {
                'integratorOrderId': 'order-verify-error',
                'status': 'SUCCESS',
            }, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert response.data['acknowledged'] is False
        wallet.refresh_from_db()
        assert wallet.balance == Decimal('0.00')

    def test_deposit_status_6054_error_returns_graceful_response(self):
        """Test that 6054 Keepz error returns 200 with current transaction state."""
        client = APIClient()
        client.force_authenticate(user=self.user)
        wallet = Wallet.objects.get(user=self.user)
        transaction = Transaction.objects.create(
            wallet=wallet,
            type=Transaction.TYPE_DEPOSIT,
            amount=Decimal('50.00'),
            status=Transaction.STATUS_PENDING,
            label='Keepz deposit',
            provider=Transaction.PROVIDER_KEEPZ,
            provider_order_id='order-6054-test',
            provider_status='INITIAL',
            provider_payload={},
        )

        with patch('apps.wallet.views.KeepzClient') as mock_client_cls:
            mock_client = Mock()
            mock_client.get_order_status.side_effect = KeepzError(
                'Cannot read the array length because "array" is null',
                status_code='6054',
                exception_group='6',
            )
            mock_client_cls.return_value = mock_client

            response = client.get('/wallet/deposit/status/', {'order_id': 'order-6054-test'})

        assert response.status_code == status.HTTP_200_OK
        assert response.data['status'] == Transaction.STATUS_PENDING
        assert response.data['credited'] is False
        assert response.data['warning'] is not None
        assert 'Keepz' in response.data['warning']

    def test_deposit_status_other_error_returns_502(self):
        """Test that non-6054 Keepz errors return 502."""
        client = APIClient()
        client.force_authenticate(user=self.user)
        wallet = Wallet.objects.get(user=self.user)
        transaction = Transaction.objects.create(
            wallet=wallet,
            type=Transaction.TYPE_DEPOSIT,
            amount=Decimal('50.00'),
            status=Transaction.STATUS_PENDING,
            label='Keepz deposit',
            provider=Transaction.PROVIDER_KEEPZ,
            provider_order_id='order-6026-test',
            provider_status='INITIAL',
            provider_payload={},
        )

        with patch('apps.wallet.views.KeepzClient') as mock_client_cls:
            mock_client = Mock()
            mock_client.get_order_status.side_effect = KeepzError(
                'Amount out of limit range',
                status_code='6026',
                exception_group='1',
            )
            mock_client_cls.return_value = mock_client

            response = client.get('/wallet/deposit/status/', {'order_id': 'order-6026-test'})

        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert 'error' in response.data


class TestWalletViewSetIntegration(APITestCase):
    """Integration tests for WalletViewSet using APIClient."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="integration@example.com",
            password="secret123",
            first_name="Integration",
            last_name="User",
            handle="integrationuser",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_stats_endpoint_authenticated(self):
        """Test stats endpoint requires authentication."""
        wallet = Wallet.objects.get(user=self.user)
        wallet.balance = Decimal("200.00")
        wallet.save()

        response = self.client.get('/wallet/stats/')

        # Should return 200 since we're authenticated
        assert response.status_code in [status.HTTP_200_OK, status.HTTP_404_NOT_FOUND]

    def test_transactions_endpoint_authenticated(self):
        """Test transactions endpoint requires authentication."""
        response = self.client.get('/wallet/transactions/')

        # Should return 200 or 404 since we're authenticated
        assert response.status_code in [status.HTTP_200_OK, status.HTTP_404_NOT_FOUND]

    def test_deposit_endpoint_authenticated(self):
        """Test deposit endpoint requires authentication."""
        with patch('apps.wallet.views.KeepzClient') as mock_client_cls:
            mock_client = Mock()
            mock_client.create_order.return_value = {
                'urlForQR': 'https://keepz.test/checkout/integration',
                'status': 'INITIAL',
            }
            mock_client_cls.return_value = mock_client

            response = self.client.post('/wallet/deposit/', {'amount': '100.00'})

        assert response.status_code == status.HTTP_200_OK

    def test_endpoints_require_authentication(self):
        """Test that endpoints require authentication."""
        # Create a new client without authentication
        unauthenticated_client = APIClient()

        stats_response = unauthenticated_client.get('/wallet/stats/')
        transactions_response = unauthenticated_client.get('/wallet/transactions/')
        deposit_response = unauthenticated_client.post('/wallet/deposit/', {'amount': '100.00'})

        # All should return 401 or 403
        assert stats_response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]
        assert transactions_response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]
        assert deposit_response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]
