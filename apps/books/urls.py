"""URL configuration for the books app."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.books.views import BookViewSet, PageNoteViewSet
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
        BookThemeViewSet.as_view({'get': 'get_theme'}),
        name='book-theme'
    ),
]
