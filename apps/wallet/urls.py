"""URL configuration for wallet app."""

from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.wallet.views import WalletDepositCallbackView, WalletViewSet

app_name = 'wallet'

router = DefaultRouter()
router.register(r'', WalletViewSet, basename='wallet')

urlpatterns = [
    path('deposit/callback/', WalletDepositCallbackView.as_view(), name='deposit-callback'),
] + router.urls
