from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.ads.views import AdViewSet

router = DefaultRouter()
router.register(r'', AdViewSet, basename='ad')

urlpatterns = [
    path('', include(router.urls)),
]
