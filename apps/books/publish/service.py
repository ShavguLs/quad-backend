"""
Simplified publish service - no image generation, just status change.

This module provides instant publishing by simply changing the book status.
Text content is served directly from the database, eliminating the need for
image generation and storage.
"""

import logging
from dataclasses import dataclass
from typing import Optional

from django.db import transaction

from apps.books.models import Book

from .exceptions import PublishError

logger = logging.getLogger(__name__)


@dataclass
class PublishResult:
    """
    Result of a publish operation.
    
    Attributes:
        success: Whether the publish succeeded
        book_id: ID of the book that was published
        pages_published: Number of pages successfully published
        error_message: Error description if publish failed
    """
    success: bool
    book_id: int
    pages_published: int = 0
    error_message: Optional[str] = None


class PublishService:
    """
    Simplified publish service - instant text-based publishing.
    
    No image generation required. Publishing simply changes the book status
    from 'draft' to 'published', making the text content available to readers.
    
    Usage:
        service = PublishService()
        result = service.publish_book(book_id, user)
    """
    
    def publish_book(self, book_id: int, user) -> PublishResult:
        """
        Publish a draft book instantly by changing status.
        
        Args:
            book_id: ID of the book to publish
            user: User requesting the publish (must be owner)
        
        Returns:
            PublishResult indicating success or failure
        
        Raises:
            PublishError: For invalid state or authorization issues
        """
        try:
            with transaction.atomic():
                book = Book.objects.select_for_update().get(pk=book_id)
                
                # Validate ownership
                if book.owner != user:
                    raise PublishError("Only book owner can publish")
                
                # Validate status
                if book.status == 'published':
                    raise PublishError("Book is already published")
                
                if book.status != 'draft':
                    raise PublishError(
                        f"Cannot publish book with status: {book.status}"
                    )
                
                # Get structured content page count
                pages_published = book.content_pages.count()
                if pages_published == 0:
                    raise PublishError("Cannot publish book with no pages")
                
                # Simply update status - no image generation needed
                book.status = 'published'
                book.save(update_fields=['status', 'updated_at'])
            
            logger.info(f"Published book {book_id}: {pages_published} pages (text-based)")
            return PublishResult(
                success=True,
                book_id=book_id,
                pages_published=pages_published
            )
            
        except PublishError:
            raise
        except Exception as e:
            logger.exception(f"Publish failed for book {book_id}")
            raise PublishError(f"Publish failed: {e}")
