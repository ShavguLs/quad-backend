"""Views for orders app."""

import uuid
from decimal import Decimal

from django.conf import settings
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.orders.models import Order
from apps.orders.serializers import OrderCreateSerializer, OrderSerializer
from apps.orders.services import (
    CheckoutError,
    complete_cart_purchase,
    finalize_cart_checkout_transaction,
    get_validated_cart_books,
    normalize_book_ids,
)
from apps.wallet.keepz_client import KeepzClient, KeepzError
from apps.wallet.models import Transaction, Wallet
from apps.wallet.views import (
    _build_absolute_url,
    _build_api_absolute_url,
    _credit_wallet_if_needed,
    _extract_checkout_url,
    _extract_keepz_status,
    _handle_keepz_error,
    _merge_provider_payload,
)


class OrderViewSet(viewsets.ModelViewSet):
    """ViewSet for order creation and history."""

    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'create':
            return OrderCreateSerializer
        return OrderSerializer

    def get_queryset(self):
        return Order.objects.filter(
            buyer=self.request.user
        ).select_related('book', 'book__owner')

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        buyer = request.user
        book_id = serializer.validated_data['book']

        try:
            order = complete_cart_purchase(buyer, [book_id])[0]
        except CheckoutError as exc:
            return Response({'error': exc.message}, status=exc.status_code)

        output = OrderSerializer(order, context={'request': request})
        return Response(output.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'])
    def checkout(self, request):
        buyer = request.user

        try:
            book_ids = normalize_book_ids(request.data.get('books'))
            books = get_validated_cart_books(buyer, book_ids)
        except CheckoutError as exc:
            return Response({'error': exc.message}, status=exc.status_code)

        cart_total = sum((book.price for book in books), Decimal('0.00'))
        wallet = Wallet.objects.get(user=buyer)

        if wallet.balance >= cart_total:
            try:
                orders = complete_cart_purchase(buyer, book_ids)
            except CheckoutError as exc:
                return Response({'error': exc.message}, status=exc.status_code)
            serializer = OrderSerializer(orders, many=True, context={'request': request})
            return Response({'status': Order.STATUS_COMPLETED, 'orders': serializer.data})

        deficit = cart_total - wallet.balance
        integrator_order_id = str(uuid.uuid4())
        transaction_obj = Transaction.objects.create(
            wallet=wallet,
            type=Transaction.TYPE_DEPOSIT,
            amount=deficit,
            status=Transaction.STATUS_PENDING,
            label='Cart checkout deficit',
            provider=Transaction.PROVIDER_KEEPZ,
            provider_order_id=integrator_order_id,
            provider_status='INITIAL',
            provider_payload={
                'checkout': {
                    'type': 'cart_deficit',
                    'bookIds': book_ids,
                    'cartTotal': f'{cart_total:.2f}',
                    'walletBalanceAtCheckout': f'{wallet.balance:.2f}',
                    'deficit': f'{deficit:.2f}',
                }
            },
        )

        payload = {
            'amount': f'{deficit:.2f}',
            'currency': settings.KEEPZ_DEFAULT_CURRENCY,
            'receiverId': settings.KEEPZ_RECEIVER_ID,
            'receiverType': settings.KEEPZ_RECEIVER_TYPE,
            'integratorId': settings.KEEPZ_INTEGRATOR_ID,
            'integratorOrderId': integrator_order_id,
            'successRedirectUri': _build_absolute_url(f'/checkout/success?order={integrator_order_id}'),
            'failRedirectUri': _build_absolute_url(f'/checkout/success?checkout=failed&order={integrator_order_id}'),
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
            'status': 'PAYMENT_REQUIRED',
            'orderId': integrator_order_id,
            'checkoutUrl': checkout_url,
            'amountDue': f'₾{deficit:.2f}',
            'cartTotal': f'₾{cart_total:.2f}',
            'walletBalance': f'₾{wallet.balance:.2f}',
        })

    @action(detail=False, methods=['get'], url_path='checkout/status')
    def checkout_status(self, request):
        order_id = request.query_params.get('order_id')
        if not order_id:
            return Response({'error': 'order_id is required'}, status=status.HTTP_400_BAD_REQUEST)

        transaction_obj = Wallet.objects.get(user=request.user).transactions.filter(
            provider=Transaction.PROVIDER_KEEPZ,
            provider_order_id=order_id,
        ).first()
        if not transaction_obj:
            return Response({'error': 'Transaction not found'}, status=status.HTTP_404_NOT_FOUND)

        if transaction_obj.status == Transaction.STATUS_PENDING:
            try:
                keepz_response = KeepzClient().get_order_status(order_id)
            except KeepzError as exc:
                if exc.status_code == '6054':
                    return Response({
                        'orderId': order_id,
                        'status': Transaction.STATUS_PENDING,
                        'providerStatus': transaction_obj.provider_status,
                    })
                message, status_code = _handle_keepz_error(exc, order_id)
                return Response({'error': message}, status=status_code)

            provider_status = _extract_keepz_status(keepz_response)
            merged_payload = _merge_provider_payload(transaction_obj, 'order_status', keepz_response)
            transaction_obj = _credit_wallet_if_needed(transaction_obj.pk, provider_status, merged_payload)

        if transaction_obj.status == Transaction.STATUS_COMPLETED:
            result_status, orders, error = finalize_cart_checkout_transaction(transaction_obj)
            if result_status == 'COMPLETED':
                serializer = OrderSerializer(orders, many=True, context={'request': request})
                return Response({
                    'orderId': order_id,
                    'status': Order.STATUS_COMPLETED,
                    'providerStatus': transaction_obj.provider_status,
                    'orders': serializer.data,
                })
            if error:
                return Response({
                    'orderId': order_id,
                    'status': 'FAILED',
                    'providerStatus': transaction_obj.provider_status,
                    'error': error,
                })

        if transaction_obj.status == Transaction.STATUS_FAILED:
            return Response({
                'orderId': order_id,
                'status': 'FAILED',
                'providerStatus': transaction_obj.provider_status,
            })

        return Response({
            'orderId': order_id,
            'status': 'PENDING',
            'providerStatus': transaction_obj.provider_status,
        })
