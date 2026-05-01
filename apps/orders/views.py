"""Views for orders app."""

from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.books.models import Book
from apps.orders.models import Order
from apps.orders.serializers import OrderCreateSerializer, OrderSerializer
from apps.wallet.models import Transaction, Wallet


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

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        buyer = request.user
        book_id = serializer.validated_data['book']

        try:
            book = Book.objects.select_for_update().get(
                id=book_id,
                status='published'
            )
        except Book.DoesNotExist:
            return Response(
                {'error': 'Book not found or not published'},
                status=status.HTTP_404_NOT_FOUND
            )

        if book.owner == buyer:
            return Response(
                {'error': 'Cannot purchase your own book'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if Order.objects.filter(buyer=buyer, book=book).exists():
            return Response(
                {'error': 'Book already purchased'},
                status=status.HTTP_409_CONFLICT
            )

        buyer_wallet = Wallet.objects.select_for_update().get(user=buyer)
        author_wallet = Wallet.objects.select_for_update().get(user=book.owner)

        if buyer_wallet.balance < book.price:
            return Response(
                {'error': 'Insufficient funds'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            expires_at = None
            if book.access_type == Book.ACCESS_TYPE_EDUCATIONAL:
                expires_at = timezone.now() + timedelta(days=180)

            order = Order.objects.create(
                buyer=buyer,
                book=book,
                amount=book.price,
                status=Order.STATUS_COMPLETED,
                expires_at=expires_at
            )
        except IntegrityError:
            transaction.set_rollback(True)
            return Response(
                {'error': 'Book already purchased'},
                status=status.HTTP_409_CONFLICT
            )

        if book.status == 'published':
            Book.objects.filter(id=book.id).update(
                revenue_total=F('revenue_total') + order.amount
            )

        buyer_wallet.balance = F('balance') - book.price
        buyer_wallet.total_withdrawn = F('total_withdrawn') + book.price
        buyer_wallet.save(update_fields=['balance', 'total_withdrawn'])

        author_wallet.balance = F('balance') + book.price
        author_wallet.total_made = F('total_made') + book.price
        author_wallet.save(update_fields=['balance', 'total_made'])

        buyer_wallet.refresh_from_db()
        author_wallet.refresh_from_db()

        Transaction.objects.create(
            wallet=buyer_wallet,
            type=Transaction.TYPE_WITHDRAW,
            amount=book.price,
            status=Transaction.STATUS_COMPLETED,
            label=f'Purchase: {book.title}'
        )

        Transaction.objects.create(
            wallet=author_wallet,
            type=Transaction.TYPE_SALE,
            amount=book.price,
            status=Transaction.STATUS_COMPLETED,
            label=f'Sale: {book.title}'
        )

        output = OrderSerializer(order, context={'request': request})
        return Response(output.data, status=status.HTTP_201_CREATED)
