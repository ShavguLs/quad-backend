"""Wallet views for stats, transactions, and Keepz deposits."""

import logging
import uuid
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.conf import settings
from django.db import transaction as db_transaction
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.wallet.keepz_client import KeepzClient, KeepzError
from apps.wallet.models import Transaction, Wallet
from apps.wallet.serializers import (
    TransactionSerializer,
    WalletStatsSerializer,
)


logger = logging.getLogger(__name__)

KEEPZ_PENDING_STATUSES = {'INITIAL', 'PROCESSING', 'PENDING', 'IN_PROGRESS', 'CREATED'}
KEEPZ_SUCCESS_STATUSES = {'SUCCESS', 'APPROVED', 'PAID', 'COMPLETE', 'COMPLETED', 'SETTLED', 'CAPTURED'}
KEEPZ_FULL_REVERSAL_STATUSES = {
    'REFUNDED_BY_OPERATOR',
    'REFUNDED_BY_INTEGRATOR',
    'REFUNDED_BY_KEEPZ',
}
KEEPZ_NON_FINAL_REFUND_STATUSES = {
    'REFUND_REQUESTED',
    'PARTIALLY_REFUNDED',
    'REFUNDED_FAILED',
}
KEEPZ_REFUND_STATUSES = KEEPZ_FULL_REVERSAL_STATUSES | KEEPZ_NON_FINAL_REFUND_STATUSES
KEEPZ_FAILED_STATUSES = {'FAILED', 'CANCELED', 'EXPIRED', 'DECLINED', 'REJECTED', 'REVERSED'}
KEEPZ_REFUND_PREFIX = 'REFUND'
MAX_DEPOSIT_AMOUNT = Decimal('5000.00')


def _parse_amount(raw_amount) -> Decimal:
    if raw_amount in (None, ''):
        raise ValidationError({'error': 'Amount is required'})

    try:
        amount = Decimal(str(raw_amount))
    except (ValueError, TypeError, InvalidOperation) as exc:
        raise ValidationError({'error': 'Invalid amount'}) from exc

    if amount <= 0 or amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) != amount:
        raise ValidationError({'error': 'Invalid amount'})

    if amount > MAX_DEPOSIT_AMOUNT:
        raise ValidationError({'error': 'Amount exceeds maximum limit'})

    return amount


def _build_absolute_url(path: str) -> str:
    return f"{settings.SITE_BASE_URL.rstrip('/')}/{path.lstrip('/')}"


def _build_api_absolute_url(path: str) -> str:
    return f"{settings.API_BASE_URL.rstrip('/')}/{path.lstrip('/')}"


def _merge_provider_payload(transaction_obj: Transaction, key: str, payload: dict) -> dict:
    provider_payload = transaction_obj.provider_payload or {}
    provider_payload[key] = payload
    return provider_payload


def _extract_keepz_status(payload: dict) -> str:
    for key in (
        'status',
        'orderStatus',
        'paymentStatus',
        'txStatus',
        'transactionStatus',
        'state',
        'resultCode',
        'responseCode',
        'keepzStatus',
    ):
        value = payload.get(key)
        if isinstance(value, str) and value:
            normalized = value.upper()
            logger.info(
                'Keepz status extracted from payload: key=%s status=%r payload_keys=%s',
                key,
                normalized,
                list(payload.keys()),
            )
            return normalized
    logger.warning('Keepz payload had no recognized status field: %s', list(payload.keys()))
    return 'INITIAL'


def _map_keepz_status(provider_status: str, current_status: str = Transaction.STATUS_PENDING) -> str:
    mapped_status = Transaction.STATUS_PENDING

    if provider_status in KEEPZ_PENDING_STATUSES:
        mapped_status = Transaction.STATUS_PENDING
    elif provider_status in KEEPZ_SUCCESS_STATUSES:
        mapped_status = Transaction.STATUS_COMPLETED
    elif provider_status in KEEPZ_FULL_REVERSAL_STATUSES:
        mapped_status = Transaction.STATUS_FAILED
    elif provider_status in KEEPZ_NON_FINAL_REFUND_STATUSES:
        if provider_status == 'REFUNDED_FAILED':
            mapped_status = current_status if current_status in {Transaction.STATUS_COMPLETED, Transaction.STATUS_FAILED} else Transaction.STATUS_PENDING
        else:
            mapped_status = Transaction.STATUS_PENDING
    elif provider_status in KEEPZ_FAILED_STATUSES:
        mapped_status = Transaction.STATUS_FAILED
    elif provider_status.startswith(KEEPZ_REFUND_PREFIX):
        mapped_status = current_status if current_status in {Transaction.STATUS_COMPLETED, Transaction.STATUS_FAILED} else Transaction.STATUS_PENDING
    else:
        mapped_status = current_status if current_status == Transaction.STATUS_COMPLETED else Transaction.STATUS_PENDING
        logger.warning('Unknown Keepz status %r, treating as PENDING (was %r)', provider_status, current_status)

    logger.info(
        'Keepz status mapped: provider_status=%r current_status=%r mapped_status=%r',
        provider_status,
        current_status,
        mapped_status,
    )
    return mapped_status


def _handle_keepz_error(exc: KeepzError, integrator_order_id: str | None = None) -> tuple[str, int]:
    logger.warning(
        'Keepz request failed for order %s: %s (statusCode=%s, exceptionGroup=%s)',
        integrator_order_id,
        exc.message,
        exc.status_code,
        exc.exception_group,
    )
    if exc.status_code in {'6036', '6056'}:
        return 'გადახდის მისამართების გამოყენება ჯერ არ არის გააქტიურებული. სცადეთ მოგვიანებით ან დაუკავშირდით მხარდაჭერას.', status.HTTP_502_BAD_GATEWAY
    return 'გადახდის ინიციაცია ამ ეტაპზე ვერ მოხერხდა. სცადეთ მოგვიანებით.', status.HTTP_502_BAD_GATEWAY


def _extract_order_id(payload: dict) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ('integratorOrderId', 'orderId', 'order_id'):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _extract_checkout_url(payload: dict) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ('urlForQR', 'checkoutUrl', 'paymentUrl', 'redirectUrl', 'url'):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _normalize_callback_payload(raw_payload) -> dict:
    if hasattr(raw_payload, 'dict'):
        normalized = raw_payload.dict()
        if isinstance(normalized, dict):
            return normalized
    if isinstance(raw_payload, dict):
        return raw_payload
    return {}


def _credit_wallet_if_needed(transaction_id: int, provider_status: str, payload: dict | None = None) -> Transaction:
    with db_transaction.atomic():
        transaction_obj = Transaction.objects.select_for_update().select_related('wallet').get(pk=transaction_id)
        wallet = Wallet.objects.select_for_update().get(pk=transaction_obj.wallet_id)
        previous_balance = wallet.balance
        was_credited = transaction_obj.credited_at is not None
        transaction_obj.provider_status = provider_status
        transaction_obj.status = _map_keepz_status(provider_status, transaction_obj.status)
        if payload is not None:
            transaction_obj.provider_payload = payload

        is_reversed = (
            was_credited
            and (
                provider_status in KEEPZ_FAILED_STATUSES
                or provider_status in KEEPZ_FULL_REVERSAL_STATUSES
            )
        )

        is_non_final_refund = (
            was_credited
            and provider_status in KEEPZ_NON_FINAL_REFUND_STATUSES
        )

        if provider_status in KEEPZ_SUCCESS_STATUSES and transaction_obj.credited_at is None:
            wallet.balance = wallet.balance + transaction_obj.amount
            wallet.save(update_fields=['balance', 'updated_at'])
            transaction_obj.credited_at = timezone.now()
            transaction_obj.status = Transaction.STATUS_COMPLETED
        elif is_reversed:
            wallet.balance = wallet.balance - transaction_obj.amount
            wallet.save(update_fields=['balance', 'updated_at'])
            transaction_obj.credited_at = None
            transaction_obj.status = Transaction.STATUS_FAILED
        elif is_non_final_refund:
            logger.warning(
                'Keepz non-final refund status received for credited transaction_id=%s provider_status=%r — wallet not debited, manual review recommended',
                transaction_obj.pk,
                provider_status,
            )

        transaction_obj.save(update_fields=['provider_status', 'status', 'provider_payload', 'credited_at'])
        logger.info(
            'Keepz credit reconciliation: transaction_id=%s provider_status=%r was_credited=%s is_credited=%s previous_balance=%s current_balance=%s transaction_status=%s',
            transaction_obj.pk,
            provider_status,
            was_credited,
            transaction_obj.credited_at is not None,
            previous_balance,
            wallet.balance,
            transaction_obj.status,
        )
        return transaction_obj


class WalletViewSet(viewsets.GenericViewSet):
    """
    ViewSet for wallet operations.
    
    Provides endpoints for:
    - Wallet statistics (balance, totalMade, pending, withdrawals)
    - Transaction history
    
    All endpoints require authentication and return data
    for the current user only.
    """
    
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """
        Return wallet for current user, creating if doesn't exist.
        
        Uses get_or_create to ensure wallet exists even if signal
        didn't fire (e.g., existing users before signal was added).
        """
        wallet, created = Wallet.objects.get_or_create(
            user=self.request.user,
            defaults={
                'balance': 0.00,
                'total_made': 0.00,
                'total_withdrawn': 0.00,
            }
        )
        return Wallet.objects.filter(user=self.request.user)
    
    @action(detail=False, methods=['get'])
    def stats(self, request):
        """
        GET /wallet/stats
        
        Returns wallet statistics for the current user:
        - balance: Current GBP balance
        - totalMade: Total revenue earned
        - pending: Sum of pending transactions
        - withdrawals: Total amount withdrawn
        """
        wallet = self.get_queryset().first()
        if not wallet:
            return Response({
                'balance': '₾0.00',
                'totalMade': '₾0.00',
                'pending': '₾0.00',
                'withdrawals': '₾0.00',
            })
        
        serializer = WalletStatsSerializer(wallet)
        data = serializer.data
        
        return Response({
            'balance': data['balance'],
            'totalMade': data['total_made'],
            'pending': data['pending'],
            'withdrawals': data['total_withdrawn'],
        })
    
    @action(detail=False, methods=['get'])
    def transactions(self, request):
        """
        GET /wallet/transactions
        
        Returns transaction history for the current user.
        Ordered by created_at descending (newest first).
        """
        wallet = self.get_queryset().first()
        if not wallet:
            return Response([])
        
        transactions = wallet.transactions.all()
        serializer = TransactionSerializer(transactions, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['post'])
    def deposit(self, request):
        try:
            amount = _parse_amount(request.data.get('amount'))
        except ValidationError as exc:
            return Response(
                exc.detail,
                status=status.HTTP_400_BAD_REQUEST,
            )

        wallet = self.get_queryset().first()
        integrator_order_id = str(uuid.uuid4())
        transaction_obj = Transaction.objects.create(
            wallet=wallet,
            type=Transaction.TYPE_DEPOSIT,
            amount=amount,
            status=Transaction.STATUS_PENDING,
            label='Keepz deposit',
            provider=Transaction.PROVIDER_KEEPZ,
            provider_order_id=integrator_order_id,
            provider_status='INITIAL',
            provider_payload={},
        )

        payload = {
            'amount': f'{amount:.2f}',
            'currency': settings.KEEPZ_DEFAULT_CURRENCY,
            'receiverId': settings.KEEPZ_RECEIVER_ID,
            'receiverType': settings.KEEPZ_RECEIVER_TYPE,
            'integratorId': settings.KEEPZ_INTEGRATOR_ID,
            'integratorOrderId': integrator_order_id,
            'successRedirectUri': _build_absolute_url(f'/wallet?deposit=success&order={integrator_order_id}'),
            'failRedirectUri': _build_absolute_url(f'/wallet?deposit=failed&order={integrator_order_id}'),
            'callbackUri': _build_api_absolute_url('/wallet/deposit/callback/'),
        }

        try:
            keepz_response = KeepzClient().create_order(payload)
        except KeepzError as exc:
            transaction_obj.provider_payload = _merge_provider_payload(transaction_obj, 'create_order_error', {
                'message': exc.message,
                'statusCode': exc.status_code,
                'exceptionGroup': exc.exception_group,
            })
            transaction_obj.provider_status = 'FAILED'
            transaction_obj.status = Transaction.STATUS_FAILED
            transaction_obj.save(update_fields=['provider_payload', 'provider_status', 'status'])
            message, status_code = _handle_keepz_error(exc, integrator_order_id)
            return Response({'error': message}, status=status_code)

        checkout_url = _extract_checkout_url(keepz_response)
        transaction_obj.provider_payload = _merge_provider_payload(transaction_obj, 'create_order', keepz_response)
        transaction_obj.provider_status = _extract_keepz_status(keepz_response)

        if not checkout_url:
            logger.error(
                'Keepz create_order returned no checkout URL for order %s. Response=%s',
                integrator_order_id,
                keepz_response,
            )
            transaction_obj.provider_status = 'FAILED'
            transaction_obj.status = Transaction.STATUS_FAILED
            transaction_obj.provider_payload = _merge_provider_payload(transaction_obj, 'create_order_error', {
                'message': 'Keepz did not return a checkout URL.',
            })
            transaction_obj.save(update_fields=['provider_payload', 'provider_status', 'status'])
            return Response(
                {'error': 'გადახდის ბმული ამ ეტაპზე ვერ შეიქმნა. სცადეთ მოგვიანებით.'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        transaction_obj.save(update_fields=['provider_payload', 'provider_status'])

        return Response({
            'message': 'Deposit initiated',
            'orderId': integrator_order_id,
            'checkoutUrl': checkout_url,
            'status': transaction_obj.status,
        })

    @action(detail=False, methods=['get'], url_path='deposit/status')
    def deposit_status(self, request):
        order_id = request.query_params.get('order_id')
        if not order_id:
            return Response({'error': 'order_id is required'}, status=status.HTTP_400_BAD_REQUEST)

        transaction_obj = self.get_queryset().first().transactions.filter(
            provider=Transaction.PROVIDER_KEEPZ,
            provider_order_id=order_id,
        ).first()
        if not transaction_obj:
            return Response({'error': 'Transaction not found'}, status=status.HTTP_404_NOT_FOUND)

        try:
            keepz_response = KeepzClient().get_order_status(order_id)
        except KeepzError as exc:
            logger.warning(
                'Keepz get_order_status failed for order %s: %s (statusCode=%s, exceptionGroup=%s)',
                order_id,
                exc.message,
                exc.status_code,
                exc.exception_group,
            )
            if exc.status_code == '6054':
                return Response({
                    'orderId': order_id,
                    'status': transaction_obj.status,
                    'providerStatus': transaction_obj.provider_status,
                    'credited': transaction_obj.credited_at is not None,
                    'amount': f'₾{transaction_obj.amount:.2f}',
                    'warning': 'Payment status check failed on Keepz side. Please try again later.',
                })
            message, status_code = _handle_keepz_error(exc, order_id)
            return Response({'error': message}, status=status_code)

        provider_status = _extract_keepz_status(keepz_response)
        logger.info(
            'Keepz deposit status response: order_id=%s keepz_response=%s extracted_status=%r',
            order_id,
            keepz_response,
            provider_status,
        )
        merged_payload = _merge_provider_payload(transaction_obj, 'order_status', keepz_response)
        transaction_obj = _credit_wallet_if_needed(transaction_obj.pk, provider_status, merged_payload)

        logger.info(
            'Keepz status resolution: extracted=%r, mapped=%r, transaction_id=%s',
            provider_status,
            transaction_obj.status,
            transaction_obj.pk,
        )

        return Response({
            'orderId': order_id,
            'status': transaction_obj.status,
            'providerStatus': transaction_obj.provider_status,
            'credited': transaction_obj.credited_at is not None,
            'amount': f'₾{transaction_obj.amount:.2f}',
        })


@method_decorator(csrf_exempt, name='dispatch')
class WalletDepositCallbackView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        raw_payload = _normalize_callback_payload(request.data)
        if not isinstance(raw_payload, dict):
            return Response({'acknowledged': False}, status=status.HTTP_200_OK)

        keepz_client = KeepzClient()

        if 'encryptedData' in raw_payload and 'encryptedKeys' in raw_payload:
            try:
                payload = keepz_client.decrypt_payload(raw_payload)
                logger.info('Keepz callback decrypted successfully')
            except KeepzError as exc:
                logger.warning('Keepz callback decryption failed: %s', exc.message)
                return Response({'acknowledged': False}, status=status.HTTP_200_OK)
        else:
            payload = raw_payload

        order_id = _extract_order_id(payload)
        if not order_id:
            logger.warning('Keepz callback received without integratorOrderId: %s', payload)
            return Response({'acknowledged': False}, status=status.HTTP_200_OK)

        transaction_obj = Transaction.objects.filter(
            provider=Transaction.PROVIDER_KEEPZ,
            provider_order_id=order_id,
        ).first()
        if not transaction_obj:
            logger.warning('Keepz callback received for unknown order %s', order_id)
            return Response({'acknowledged': False}, status=status.HTTP_200_OK)

        try:
            keepz_response = keepz_client.get_order_status(order_id)
        except KeepzError as exc:
            logger.warning('Keepz callback status verification failed for %s: %s', order_id, exc.message)
            return Response({'acknowledged': False}, status=status.HTTP_200_OK)

        provider_status = _extract_keepz_status(keepz_response)
        merged_payload = _merge_provider_payload(transaction_obj, 'callback', payload)
        merged_payload['verified_order_status'] = keepz_response
        _credit_wallet_if_needed(transaction_obj.pk, provider_status, merged_payload)
        return Response({'acknowledged': True}, status=status.HTTP_200_OK)
