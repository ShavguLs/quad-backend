"""URL configuration for orders app."""

from rest_framework.routers import DefaultRouter

from apps.orders.views import OrderViewSet

app_name = 'orders'

router = DefaultRouter()
router.register(r'', OrderViewSet, basename='order')

urlpatterns = router.urls
