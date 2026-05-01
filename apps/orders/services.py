"""Order purchase helpers."""

from datetime import timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from apps.books.models import Book
from apps.orders.models import Order
from apps.wallet.models import Transaction, Wallet


class CheckoutError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def normalize_book_ids(raw_book_ids) -> list[int]:
    if not isinstance(raw_book_ids, list) or not raw_book_ids:
        raise CheckoutError('books is required')

    normalized_ids = []
    seen = set()
    for raw_id in raw_book_ids:
        try:
            book_id = int(raw_id)
        except (TypeError, ValueError) as exc:
            raise CheckoutError('Invalid book id') from exc
        if book_id not in seen:
            normalized_ids.append(book_id)
            seen.add(book_id)
    return normalized_ids


def get_validated_cart_books(buyer, book_ids: list[int], lock: bool = False):
    queryset = Book.objects.select_related('owner')
    if lock:
        queryset = queryset.select_for_update()

    books = list(queryset.filter(id__in=book_ids))
    books_by_id = {book.id: book for book in books}
    ordered_books = [books_by_id.get(book_id) for book_id in book_ids]

    if any(book is None for book in ordered_books):
        raise CheckoutError('Book not found or not published', 404)

    for book in ordered_books:
        if book.status != 'published':
            raise CheckoutError('Book not found or not published', 404)
        if book.owner_id == buyer.id:
            raise CheckoutError('Cannot purchase your own book')

    purchased_book_ids = set(Order.objects.filter(
        buyer=buyer,
        book_id__in=book_ids,
    ).values_list('book_id', flat=True))
    if purchased_book_ids:
        raise CheckoutError('Book already purchased', 409)

    return ordered_books


def complete_cart_purchase(buyer, book_ids: list[int]) -> list[Order]:
    with transaction.atomic():
        books = get_validated_cart_books(buyer, book_ids, lock=True)
        total = sum((book.price for book in books), Decimal('0.00'))

        buyer_wallet = Wallet.objects.select_for_update().get(user=buyer)
        author_ids = sorted({book.owner_id for book in books})
        author_wallets = {
            wallet.user_id: wallet
            for wallet in Wallet.objects.select_for_update().filter(user_id__in=author_ids)
        }

        if buyer_wallet.balance < total:
            raise CheckoutError('Insufficient funds')

        orders = []
        try:
            for book in books:
                expires_at = None
                if book.access_type == Book.ACCESS_TYPE_EDUCATIONAL:
                    expires_at = timezone.now() + timedelta(days=180)

                orders.append(Order.objects.create(
                    buyer=buyer,
                    book=book,
                    amount=book.price,
                    status=Order.STATUS_COMPLETED,
                    expires_at=expires_at,
                ))
        except IntegrityError as exc:
            raise CheckoutError('Book already purchased', 409) from exc

        for order in orders:
            Book.objects.filter(id=order.book_id).update(
                revenue_total=F('revenue_total') + order.amount
            )

        if total > 0:
            buyer_wallet.balance = F('balance') - total
            buyer_wallet.total_withdrawn = F('total_withdrawn') + total
            buyer_wallet.save(update_fields=['balance', 'total_withdrawn'])

        for order in orders:
            author_wallet = author_wallets[order.book.owner_id]
            if order.amount > 0:
                author_wallet.balance = F('balance') + order.amount
                author_wallet.total_made = F('total_made') + order.amount
                author_wallet.save(update_fields=['balance', 'total_made'])

        buyer_wallet.refresh_from_db()
        for author_wallet in author_wallets.values():
            author_wallet.refresh_from_db()

        for order in orders:
            Transaction.objects.create(
                wallet=buyer_wallet,
                type=Transaction.TYPE_WITHDRAW,
                amount=order.amount,
                status=Transaction.STATUS_COMPLETED,
                label=f'Purchase: {order.book.title}'
            )
            Transaction.objects.create(
                wallet=author_wallets[order.book.owner_id],
                type=Transaction.TYPE_SALE,
                amount=order.amount,
                status=Transaction.STATUS_COMPLETED,
                label=f'Sale: {order.book.title}'
            )

        return orders


def finalize_cart_checkout_transaction(transaction_obj: Transaction) -> tuple[str, list[Order], str | None]:
    payload = transaction_obj.provider_payload or {}
    checkout = payload.get('checkout') if isinstance(payload, dict) else None
    if not isinstance(checkout, dict) or checkout.get('type') != 'cart_deficit':
        return 'IGNORED', [], None

    book_ids = checkout.get('bookIds')
    if not isinstance(book_ids, list):
        return _store_checkout_result(transaction_obj, 'FAILED', [], 'CHECKOUT_FINALIZATION_FAILED')

    existing_orders = list(Order.objects.filter(
        buyer=transaction_obj.wallet.user,
        book_id__in=book_ids,
        status=Order.STATUS_COMPLETED,
    ).select_related('book', 'book__owner'))
    if len(existing_orders) == len(set(book_ids)):
        return _store_checkout_result(transaction_obj, 'COMPLETED', existing_orders, None)

    try:
        orders = complete_cart_purchase(transaction_obj.wallet.user, normalize_book_ids(book_ids))
    except CheckoutError:
        return _store_checkout_result(transaction_obj, 'FAILED', [], 'CHECKOUT_FINALIZATION_FAILED')

    return _store_checkout_result(transaction_obj, 'COMPLETED', orders, None)


def _store_checkout_result(transaction_obj: Transaction, status: str, orders: list[Order], error: str | None):
    transaction_obj.refresh_from_db()
    payload = transaction_obj.provider_payload or {}
    payload['checkout_result'] = {
        'status': status,
        'orderIds': [str(order.id) for order in orders],
    }
    if error:
        payload['checkout_result']['error'] = error
    transaction_obj.provider_payload = payload
    transaction_obj.save(update_fields=['provider_payload'])
    return status, orders, error
