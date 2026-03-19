"""
Wallet serializers for API responses.
"""

from rest_framework import serializers

from apps.wallet.models import Transaction, Wallet


class WalletSerializer(serializers.ModelSerializer):
    """Serializer for wallet data with formatted currency fields."""
    
    balance = serializers.SerializerMethodField()
    total_made = serializers.SerializerMethodField()
    total_withdrawn = serializers.SerializerMethodField()
    
    class Meta:
        model = Wallet
        fields = ['balance', 'total_made', 'total_withdrawn']
    
    def get_balance(self, obj):
        return f'₾{obj.balance:.2f}'
    
    def get_total_made(self, obj):
        return f'₾{obj.total_made:.2f}'
    
    def get_total_withdrawn(self, obj):
        return f'₾{obj.total_withdrawn:.2f}'


class WalletStatsSerializer(serializers.ModelSerializer):
    """Serializer for wallet stats endpoint with formatted currency fields."""
    
    balance = serializers.SerializerMethodField()
    total_made = serializers.SerializerMethodField()
    total_withdrawn = serializers.SerializerMethodField()
    pending = serializers.SerializerMethodField()
    
    class Meta:
        model = Wallet
        fields = ['balance', 'total_made', 'pending', 'total_withdrawn']
    
    def get_balance(self, obj):
        return f'₾{obj.balance:.2f}'
    
    def get_total_made(self, obj):
        return f'₾{obj.total_made:.2f}'
    
    def get_total_withdrawn(self, obj):
        return f'₾{obj.total_withdrawn:.2f}'
    
    def get_pending(self, obj):
        return f'₾{obj.pending:.2f}'


class TransactionSerializer(serializers.ModelSerializer):
    """Serializer for transactions."""
    
    amount = serializers.SerializerMethodField()
    date = serializers.DateTimeField(source='created_at', read_only=True)
    
    class Meta:
        model = Transaction
        fields = ['id', 'type', 'amount', 'status', 'label', 'date']
    
    def get_amount(self, obj):
        """Format amount with +/- prefix based on transaction type."""
        if obj.type in [Transaction.TYPE_SALE, Transaction.TYPE_DEPOSIT]:
            return f"+₾{obj.amount}"
        else:
            return f"-₾{obj.amount}"
