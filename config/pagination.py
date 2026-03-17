"""
Custom pagination classes for the API.

Provides standardized pagination response format matching frontend expectations.
"""

from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class StandardResultsSetPagination(PageNumberPagination):
    """
    Standard pagination class with configurable page size.
    
    Returns paginated response in the format:
    {
        "count": total_items,
        "next": url_or_null,
        "previous": url_or_null,
        "results": [items]
    }
    """
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class LargeResultsSetPagination(PageNumberPagination):
    """Pagination class for endpoints that need larger page sizes."""
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200
