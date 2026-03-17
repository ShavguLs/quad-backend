"""
URL configuration for wallet app.

Routes wallet endpoints:
- /wallet/stats/ - Wallet statistics
- /wallet/transactions/ - Transaction history
"""

from rest_framework.routers import DefaultRouter

from apps.wallet.views import WalletViewSet

app_name = 'wallet'

router = DefaultRouter()
router.register(r'', WalletViewSet, basename='wallet')

urlpatterns = router.urls
