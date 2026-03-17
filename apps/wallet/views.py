"""
Wallet views for the wallet app.

Provides WalletViewSet for wallet operations:
- stats: GET /wallet/stats returns wallet statistics
- transactions: GET /wallet/transactions returns transaction history
"""

from decimal import Decimal, InvalidOperation

from django.db import transaction as db_transaction
from django.db.models import F
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.wallet.models import Transaction, Wallet
from apps.wallet.serializers import (
    TransactionSerializer,
    WalletStatsSerializer,
)


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
                'balance': '£0.00',
                'totalMade': '£0.00',
                'pending': '£0.00',
                'withdrawals': '£0.00',
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
    @db_transaction.atomic
    def deposit(self, request):
        """
        POST /wallet/deposit
        
        Add funds to the user's wallet.
        Creates a DEPOSIT transaction and updates wallet balance.
        """
        wallet = self.get_queryset().select_for_update().first()
        if not wallet:
            return Response(
                {'error': 'Wallet not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        amount = request.data.get('amount')
        if not amount:
            return Response(
                {'error': 'Amount is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            amount = Decimal(str(amount))
            if amount <= 0:
                raise ValueError('Amount must be positive')
        except (ValueError, TypeError, InvalidOperation):
            return Response(
                {'error': 'Invalid amount'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Create transaction
        Transaction.objects.create(
            wallet=wallet,
            type=Transaction.TYPE_DEPOSIT,
            amount=amount,
            status=Transaction.STATUS_COMPLETED,
            label='Manual deposit',
        )
        
        # Update wallet balance atomically
        Wallet.objects.filter(pk=wallet.pk).update(balance=F('balance') + amount)
        wallet.refresh_from_db()
        
        return Response({
            'message': 'Deposit successful',
            'amount': f'£{amount}',
            'new_balance': f'£{wallet.balance}'
        })
