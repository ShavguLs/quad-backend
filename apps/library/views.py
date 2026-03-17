"""
Views for the library app.

Provides ViewSets for user-specific library browsing:
- MyLibraryViewSet: Authenticated user's complete library (all books)
- UserLibraryViewSet: Public library for a specific user (published only)
"""

from unicodedata import normalize

from django.db.models import Q
from rest_framework import viewsets
from rest_framework.permissions import AllowAny, IsAuthenticated

from apps.books.models import Book
from apps.books.serializers import BookSerializer
from apps.orders.models import Order
from apps.users.models import User


class MyLibraryViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for authenticated user's complete library.
    
    Returns all books owned by the current user (both drafts and published).
    Requires authentication.
    """
    serializer_class = BookSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Return all books owned or purchased by the current user."""
        return (
            Book.objects.select_related('owner')
            .prefetch_related('files')
            .filter(
                Q(owner=self.request.user)
                | Q(
                    orders__buyer=self.request.user,
                    orders__status=Order.STATUS_COMPLETED,
                    status='published'
                )
            )
            .distinct()
        )


class PurchasedLibraryViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for authenticated user's purchased library.

    Returns books the user has purchased (completed orders only).
    Different from MyLibraryViewSet which returns uploaded books.
    Only published books are included (drafts are hidden).
    """

    serializer_class = BookSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = 'id'

    def get_queryset(self):
        """Return published books purchased by the current user."""
        from apps.orders.models import Order

        purchased_book_ids = Order.objects.filter(
            buyer=self.request.user,
            status=Order.STATUS_COMPLETED
        ).values_list('book_id', flat=True)

        return Book.objects.filter(
            id__in=purchased_book_ids,
            status='published'
        ).select_related('owner').prefetch_related('files')


class UserLibraryViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for public library browsing by user handle.
    
    Returns only published books for the specified user.
    Accessible to anyone (no authentication required).
    """
    serializer_class = BookSerializer
    permission_classes = [AllowAny]
    lookup_field = 'handle_normalized'
    lookup_url_kwarg = 'handle'
    
    def get_queryset(self):
        """
        Return published books for the user specified by handle.
        
        Handle is normalized using NFKC + strip + lowercase for
        case-insensitive matching.
        """
        handle = self.kwargs.get(self.lookup_url_kwarg)
        
        if not handle:
            return Book.objects.none()
        
        # Normalize handle using same logic as User model
        handle_normalized = normalize("NFKC", handle.strip()).lower()
        
        try:
            user = User.objects.get(handle_normalized=handle_normalized)
        except User.DoesNotExist:
            # Return empty queryset if user not found
            return Book.objects.none()
        
        return Book.objects.select_related('owner').filter(
            owner=user,
            status='published'
        )
