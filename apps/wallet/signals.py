"""
Wallet signals for auto-creating wallets when users are created.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.users.models import User
from apps.wallet.models import Wallet


@receiver(post_save, sender=User)
def create_user_wallet(sender, instance, created, **kwargs):
    """Auto-create a wallet for new users."""
    if created:
        Wallet.objects.create(user=instance)
