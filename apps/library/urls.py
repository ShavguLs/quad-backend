"""
URL configuration for the library app.

Provides routes for:
- /library/me/ — Authenticated user's uploaded books
- /library/purchased/ — Authenticated user's purchased books
- /library/users/{handle}/ — Public library for a specific user
"""

from django.urls import path

from apps.library.views import MyLibraryViewSet, PurchasedLibraryViewSet, UserLibraryViewSet

urlpatterns = [
    path('me/', MyLibraryViewSet.as_view({'get': 'list'}), name='my-library'),
    path('purchased/', PurchasedLibraryViewSet.as_view({'get': 'list'}), name='purchased-library'),
    path(
        'purchased/<uuid:id>/',
        PurchasedLibraryViewSet.as_view({'get': 'retrieve'}),
        name='purchased-library-detail'
    ),
    path('users/<str:handle>/', UserLibraryViewSet.as_view({'get': 'list'}), name='user-library'),
]
