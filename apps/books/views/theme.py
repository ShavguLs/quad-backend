"""Book theme views.

Provides API endpoints for getting and updating book themes.
GET is public (readers need the theme), PATCH requires authentication.
"""

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny

from apps.books.models import Book
from apps.books.serializers import BookThemeSerializer


class BookThemeViewSet(viewsets.GenericViewSet):
    """ViewSet for book theme operations.
    
    Provides endpoints for retrieving and updating per-book themes.
    GET is public for readers, PATCH requires authentication.
    """
    
    queryset = Book.objects.all()
    serializer_class = BookThemeSerializer
    lookup_field = 'pk'

    def get_permissions(self):
        """GET theme is public; PATCH theme requires auth."""
        if self.action == 'get_theme':
            return [AllowAny()]
        return [IsAuthenticated()]
    
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
    
    @action(detail=True, methods=['patch'], url_path='theme')
    def update_theme(self, request, pk=None):
        """Update the theme for a book.
        
        Requires authentication. Only the book owner can update.
        
        Request Body:
            paper_background: str (optional)
            font_family: str (optional)
            font_id: str (optional) - Draft Studio font profile
            palette_id: str (optional) - Draft Studio palette
            animation_id: str (optional) - Draft Studio animation effect
            base_font_size: float (optional) - Font size in px (14-24)
            line_height: float (optional) - Line height (1.0-3.0)
            letter_spacing: float (optional) - Letter spacing in em (0-0.1)
            content_width: float (optional) - Content max width in px (400-1000)
            
        Returns:
            Response with updated theme data including CSS variables
            
        Status Codes:
            200: Success with updated theme data
            400: Invalid theme data provided
            403: User doesn't have permission to access this book
            404: Book not found
        """
        try:
            book = self.get_object()
        except Book.DoesNotExist:
            return Response(
                {'detail': 'Book not found.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Check access permissions (only owner can update theme)
        if not book.can_user_access(request.user):
            return Response(
                {'detail': 'You do not have permission to access this book.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Validate incoming data
        serializer = self.get_serializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Update book theme
        try:
            book.set_theme(**serializer.validated_data)
        except ValueError as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Return updated theme
        serializer = self.get_serializer(book.get_theme())
        return Response(serializer.data)
