"""
Publish module for safe book publication with transaction safety.

This module provides the publish service infrastructure that bridges
draft editing (BookContent) with reader artifacts.

Usage:
    from apps.books.publish import PublishService, PageImageGenerator
    
    with PageImageGenerator() as generator:
        service = PublishService(generator)
        result = service.publish_book(book_id, user)
"""

from .exceptions import DraftChangedError, PublishError
from .image_generator import PageImageGenerator
from .service import PublishResult, PublishService

__all__ = [
    'DraftChangedError',
    'PageImageGenerator',
    'PublishError',
    'PublishResult',
    'PublishService',
]
