"""Books services package.

Provides business logic services for book operations.
"""

from apps.books.services.content import (
    ContentService,
    OptimisticLockingError,
)
from apps.books.services.extraction_integration import (
    ExtractionToContentService,
    ContentCreationResult,
)

__all__ = [
    'ContentService',
    'OptimisticLockingError',
    'ExtractionToContentService',
    'ContentCreationResult',
]
