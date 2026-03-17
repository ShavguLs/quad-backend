"""URL configuration for the books app."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.books.views import BookViewSet, PageNoteViewSet, SavedPageViewSet, ReadingPositionViewSet
from apps.books.views.theme import BookThemeViewSet

router = DefaultRouter()
router.register(r'', BookViewSet, basename='book')

urlpatterns = [
    path('', include(router.urls)),
    path(
        '<int:book_id>/notes/',
        PageNoteViewSet.as_view({'get': 'list', 'post': 'create'}),
        name='book-page-notes'
    ),
    path(
        'notes/<int:pk>/',
        PageNoteViewSet.as_view({'delete': 'destroy'}),
        name='page-note-detail'
    ),
    path(
        '<int:pk>/theme/',
        BookThemeViewSet.as_view({'get': 'get_theme', 'patch': 'update_theme'}),
        name='book-theme'
    ),
    # Saved pages endpoints
    path(
        '<int:book_id>/saved-pages/',
        SavedPageViewSet.as_view({'get': 'list', 'post': 'create', 'delete': 'destroy_all'}),
        name='book-saved-pages'
    ),
    path(
        '<int:book_id>/saved-pages/<int:page_number>/',
        SavedPageViewSet.as_view({'delete': 'destroy'}),
        name='book-saved-page-detail'
    ),
    # Reading position (single cross-device bookmark)
    path(
        '<int:book_id>/reading-position/',
        ReadingPositionViewSet.as_view({'get': 'retrieve', 'put': 'update', 'delete': 'destroy'}),
        name='book-reading-position'
    ),
]
