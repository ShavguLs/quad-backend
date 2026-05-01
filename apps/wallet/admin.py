"""
Admin configuration for wallet app.

Registers Wallet and Transaction models in Django admin.
Provides full CRUD for Wallet balance fields and Transaction status workflow.
"""

from django.contrib import admin
from django.contrib import messages
from django.db import transaction
from django.db.models import F

from apps.wallet.keepz_client import KeepzClient, KeepzError
from apps.wallet.models import Transaction, Wallet
from apps.wallet.views import _credit_wallet_if_needed, _extract_keepz_status, _merge_provider_payload


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    """Admin configuration for Wallet model.
    
    Allows superusers to edit balance fields for manual corrections.
    All balance fields (balance, total_made, total_withdrawn) are editable.
    """

    list_display = [
        'user',
        'balance',
        'total_made',
        'total_withdrawn',
        'updated_at',
    ]
    list_filter = ['created_at', 'updated_at']
    search_fields = ['user__email', 'user__handle']
    fields = ['user', 'balance', 'total_made', 'total_withdrawn']
    readonly_fields = ['created_at', 'updated_at']
    raw_id_fields = ['user']  # Better UX for user selection with many users


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    """Admin configuration for Transaction model.
    
    Provides custom actions for transaction status workflow:
    - Mark PENDING transactions as COMPLETED
    - Mark PENDING transactions as FAILED
    - Refund COMPLETED transactions (mark as FAILED and reverse balance)
    """

    list_display = [
        'wallet',
        'type',
        'amount',
        'status',
        'provider',
        'provider_status',
        'credited_at',
        'label',
        'created_at',
    ]
    list_filter = ['type', 'status', 'provider', 'provider_status', 'created_at']
    search_fields = ['wallet__user__email', 'label', 'provider_order_id']
    fields = [
        'wallet',
        'type',
        'amount',
        'status',
        'label',
        'provider',
        'provider_order_id',
        'provider_status',
        'provider_payload',
        'credited_at',
    ]
    readonly_fields = ['created_at', 'credited_at']
    raw_id_fields = ['wallet']  # Better UX for wallet selection
    actions = ['reconcile_keepz_deposits', 'mark_completed', 'mark_failed', 'refund_transaction']

    @admin.action(description='Verify selected Keepz deposits and update wallet')
    def reconcile_keepz_deposits(self, request, queryset):
        keepz_transactions = queryset.filter(
            type=Transaction.TYPE_DEPOSIT,
            provider=Transaction.PROVIDER_KEEPZ,
            provider_order_id__isnull=False,
        )

        if not keepz_transactions.exists():
            self.message_user(
                request,
                'No Keepz deposit transactions with order IDs selected.',
                messages.WARNING,
            )
            return

        keepz_client = KeepzClient()
        completed_count = 0
        failed_count = 0
        pending_count = 0
        error_count = 0

        for txn in keepz_transactions:
            try:
                keepz_response = keepz_client.get_order_status(txn.provider_order_id)
            except KeepzError as exc:
                error_count += 1
                self.message_user(
                    request,
                    f'Keepz status check failed for {txn.provider_order_id}: {exc.message}',
                    messages.WARNING,
                )
                continue

            provider_status = _extract_keepz_status(keepz_response)
            merged_payload = _merge_provider_payload(txn, 'admin_order_status', keepz_response)
            updated_txn = _credit_wallet_if_needed(txn.pk, provider_status, merged_payload)

            if updated_txn.status == Transaction.STATUS_COMPLETED:
                completed_count += 1
            elif updated_txn.status == Transaction.STATUS_FAILED:
                failed_count += 1
            else:
                pending_count += 1

        self.message_user(
            request,
            (
                'Keepz reconciliation finished: '
                f'{completed_count} completed, {pending_count} pending, '
                f'{failed_count} failed, {error_count} errors.'
            ),
            messages.SUCCESS if error_count == 0 else messages.WARNING,
        )

    @admin.action(description='Mark selected transactions as COMPLETED')
    def mark_completed(self, request, queryset):
        """Mark PENDING transactions as COMPLETED.
        
        For DEPOSIT transactions, adds amount to wallet balance.
        Only processes transactions currently in PENDING status.
        """
        pending_transactions = queryset.filter(status=Transaction.STATUS_PENDING)
        
        if not pending_transactions.exists():
            self.message_user(
                request,
                'No PENDING transactions selected. Only PENDING transactions can be marked as COMPLETED.',
                messages.WARNING
            )
            return
        
        completed_count = 0
        
        with transaction.atomic():
            for txn in pending_transactions.select_related('wallet').select_for_update():
                # Update wallet balance based on transaction type using F() expressions
                # to avoid stale read-modify-write races at the database level.
                if txn.type == Transaction.TYPE_DEPOSIT:
                    Wallet.objects.filter(pk=txn.wallet_id).update(
                        balance=F('balance') + txn.amount,
                    )
                elif txn.type == Transaction.TYPE_SALE:
                    Wallet.objects.filter(pk=txn.wallet_id).update(
                        balance=F('balance') + txn.amount,
                        total_made=F('total_made') + txn.amount,
                    )
                elif txn.type == Transaction.TYPE_WITHDRAW:
                    Wallet.objects.filter(pk=txn.wallet_id).update(
                        balance=F('balance') - txn.amount,
                        total_withdrawn=F('total_withdrawn') + txn.amount,
                    )

                txn.status = Transaction.STATUS_COMPLETED
                txn.save(update_fields=['status'])
                completed_count += 1
        
        self.message_user(
            request,
            f'{completed_count} transaction(s) marked as COMPLETED.',
            messages.SUCCESS
        )

    @admin.action(description='Mark selected transactions as FAILED')
    def mark_failed(self, request, queryset):
        """Mark PENDING transactions as FAILED.
        
        No balance changes - simply cancels the pending transaction.
        Only processes transactions currently in PENDING status.
        """
        pending_transactions = queryset.filter(status=Transaction.STATUS_PENDING)
        
        if not pending_transactions.exists():
            self.message_user(
                request,
                'No PENDING transactions selected. Only PENDING transactions can be marked as FAILED.',
                messages.WARNING
            )
            return
        
        failed_count = pending_transactions.update(status=Transaction.STATUS_FAILED)
        
        self.message_user(
            request,
            f'{failed_count} transaction(s) marked as FAILED.',
            messages.SUCCESS
        )

    @admin.action(description='Refund selected COMPLETED transactions')
    def refund_transaction(self, request, queryset):
        """Refund COMPLETED transactions by marking as FAILED and reversing balance.
        
        Only processes transactions currently in COMPLETED status.
        Reverses the balance change based on transaction type:
        - DEPOSIT: Subtracts amount from wallet balance
        - SALE: Adds amount back to wallet balance (if it was a purchase)
        """
        completed_transactions = queryset.filter(status=Transaction.STATUS_COMPLETED)
        
        if not completed_transactions.exists():
            self.message_user(
                request,
                'No COMPLETED transactions selected. Only COMPLETED transactions can be refunded.',
                messages.WARNING
            )
            return
        
        refunded_count = 0
        skipped_count = 0
        
        with transaction.atomic():
            for txn in completed_transactions.select_related('wallet').select_for_update():
                wallet = txn.wallet

                # Reverse the balance change using F() expressions to avoid
                # stale read-modify-write races at the database level.
                if txn.type == Transaction.TYPE_DEPOSIT:
                    # For deposits, subtract the amount (reverse the credit).
                    # Skip if balance would go negative.
                    if wallet.balance >= txn.amount:
                        Wallet.objects.filter(pk=txn.wallet_id).update(
                            balance=F('balance') - txn.amount,
                        )
                    else:
                        skipped_count += 1
                        continue
                elif txn.type == Transaction.TYPE_SALE:
                    # For sales (purchases), add amount back to buyer's wallet.
                    Wallet.objects.filter(pk=txn.wallet_id).update(
                        balance=F('balance') + txn.amount,
                    )
                elif txn.type == Transaction.TYPE_WITHDRAW:
                    # For withdrawals, add amount back to wallet.
                    Wallet.objects.filter(pk=txn.wallet_id).update(
                        balance=F('balance') + txn.amount,
                    )

                txn.status = Transaction.STATUS_FAILED
                txn.save(update_fields=['status'])
                refunded_count += 1
        
        if skipped_count > 0:
            self.message_user(
                request,
                f'{refunded_count} transaction(s) refunded. {skipped_count} transaction(s) skipped due to insufficient balance.',
                messages.WARNING
            )
        else:
            self.message_user(
                request,
                f'{refunded_count} transaction(s) refunded successfully.',
                messages.SUCCESS
            )
