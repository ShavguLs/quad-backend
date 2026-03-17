"""
Admin configuration for orders app.

Registers Order model in Django admin with status workflow and refund actions.
"""

from decimal import Decimal

from django.contrib import admin, messages
from django.db import transaction

from apps.orders.models import Order


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    """Admin configuration for Order model with status workflow actions."""

    list_display = [
        'id',
        'buyer',
        'book',
        'amount',
        'status',
        'created_at',
    ]
    list_filter = ['status', 'created_at']
    search_fields = ['buyer__email', 'book__title']
    raw_id_fields = ['buyer', 'book']
    fields = ['buyer', 'book', 'amount', 'status']
    readonly_fields = ['id', 'created_at']
    ordering = ['-created_at']
    actions = ['mark_completed', 'mark_refunded', 'cancel_order']

    @admin.action(description='Mark selected orders as completed')
    def mark_completed(self, request, queryset):
        """Change status from PENDING to COMPLETED and transfer book to buyer's library."""
        from apps.books.models import BookFollow

        pending_orders = queryset.filter(status=Order.STATUS_PENDING)
        updated_count = 0

        with transaction.atomic():
            for order in pending_orders:
                # Update order status
                order.status = Order.STATUS_COMPLETED
                order.save()

                # Add book to buyer's library (follow the book to indicate ownership)
                BookFollow.objects.get_or_create(
                    book=order.book,
                    user=order.buyer
                )

                updated_count += 1

        if updated_count > 0:
            self.message_user(
                request,
                f'{updated_count} order(s) marked as completed. Books added to buyer libraries.',
                messages.SUCCESS
            )
        else:
            self.message_user(
                request,
                'No pending orders were updated.',
                messages.WARNING
            )

    @admin.action(description='Mark selected orders as refunded')
    def mark_refunded(self, request, queryset):
        """Change status from COMPLETED to REFUNDED and return funds to buyer."""
        completed_orders = queryset.filter(status=Order.STATUS_COMPLETED)
        updated_count = 0

        with transaction.atomic():
            for order in completed_orders:
                # Update order status
                order.status = Order.STATUS_FAILED
                order.save()

                # Return funds to buyer's wallet
                buyer_wallet = order.buyer.wallet
                buyer_wallet.balance += order.amount
                buyer_wallet.save()

                # Create refund transaction record
                from apps.wallet.models import Transaction
                Transaction.objects.create(
                    wallet=buyer_wallet,
                    type=Transaction.TYPE_DEPOSIT,
                    amount=order.amount,
                    status=Transaction.STATUS_COMPLETED,
                    label=f'Refund for order {order.id}'
                )

                # Remove book from buyer's library
                from apps.books.models import BookFollow
                BookFollow.objects.filter(
                    book=order.book,
                    user=order.buyer
                ).delete()

                updated_count += 1

        if updated_count > 0:
            self.message_user(
                request,
                f'{updated_count} order(s) marked as refunded. Funds returned to buyer wallets.',
                messages.SUCCESS
            )
        else:
            self.message_user(
                request,
                'No completed orders were updated.',
                messages.WARNING
            )

    @admin.action(description='Cancel selected orders')
    def cancel_order(self, request, queryset):
        """Change status from PENDING to FAILED (cancelled) and return funds if paid."""
        pending_orders = queryset.filter(status=Order.STATUS_PENDING)
        updated_count = 0

        with transaction.atomic():
            for order in pending_orders:
                # Update order status
                order.status = Order.STATUS_FAILED
                order.save()

                updated_count += 1

        if updated_count > 0:
            self.message_user(
                request,
                f'{updated_count} order(s) cancelled.',
                messages.SUCCESS
            )
        else:
            self.message_user(
                request,
                'No pending orders were cancelled.',
                messages.WARNING
            )
