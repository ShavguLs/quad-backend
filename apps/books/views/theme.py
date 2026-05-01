"""Book theme views.

Provides a public API endpoint for reading book themes.
"""

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny

from apps.books.models import Book
from apps.books.serializers import BookThemeSerializer


class BookThemeViewSet(viewsets.GenericViewSet):
    """ViewSet for book theme operations.
    
    Provides an endpoint for retrieving per-book themes.
    GET is public for readers.
    """
    
    queryset = Book.objects.all()
    serializer_class = BookThemeSerializer
    lookup_field = 'pk'

    def get_permissions(self):
        """Theme reads are public."""
        return [AllowAny()]
    
    @action(detail=True, methods=['get'], url_path='theme')
    def get_theme(self, request, pk=None):
        """Get the current theme for a book.
        
        Public endpoint — readers need theme data to apply author styles.
        
        Returns:
            Response with theme data including CSS variables
            
        Status Codes:
            200: Success with theme data
            404: Book not found
        """
        try:
            book = self.get_object()
        except Book.DoesNotExist:
            return Response(
                {'detail': 'Book not found.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Get theme data from book
        theme_data = book.get_theme()
        
        # Serialize and return
        serializer = self.get_serializer(theme_data)
        return Response(serializer.data)
