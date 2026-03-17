"""Base converter interface."""

from abc import ABC, abstractmethod
from typing import List

from apps.books.converters.casting_contract import UnsupportedStyle


class ConversionError(Exception):
    """Raised when file conversion fails."""
    pass


class BaseConverter(ABC):
    """Abstract base class for book file converters."""

    def __init__(self):
        """Initialize converter with empty unsupported styles list."""
        self.unsupported_styles: list[UnsupportedStyle] = []

    def get_unsupported_styles(self) -> list[UnsupportedStyle]:
        """Return list of unsupported styles detected during conversion."""
        return self.unsupported_styles

    @abstractmethod
    def convert(self, file_obj, book) -> List[dict]:
        """
        Convert a file to content data for BookContent creation.

        Args:
            file_obj: File-like object or bytes
            book: Book instance to associate content with

        Returns:
            List of content data dicts:
            {
                'page_number': int,
                'html_content': str,
                'text_content': str,
                'image_data': bytes (optional),
            }

        Raises:
            ConversionError: If conversion fails
        """
        pass

    @abstractmethod
    def supports(self, mime_type: str) -> bool:
        """Check if this converter supports the given MIME type."""
        pass
