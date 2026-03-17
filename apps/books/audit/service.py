"""
Audit logging service for book lifecycle actions.

Provides functions to log and query audit records for upload,
edit, and publish actions with actor identity and timestamps.
"""

from datetime import date
from typing import Dict, List, Optional, Union

from django.db.models import QuerySet

from apps.books.models import Book, BookAuditLog


def log_upload(
    book_id: int,
    user,
    attempt: int = 1,
    ip_address: Optional[str] = None
) -> BookAuditLog:
    """
    Log an upload action for a book.
    
    Args:
        book_id: ID of the book being uploaded
        user: User performing the upload
        attempt: Upload attempt number (for retries)
        ip_address: Client IP address (optional)
    
    Returns:
        Created BookAuditLog instance
    """
    book = Book.objects.get(pk=book_id)
    return BookAuditLog.objects.create(
        book=book,
        user=user,
        action=BookAuditLog.ACTION_UPLOAD,
        details={'attempt': attempt},
        ip_address=ip_address,
    )


def log_edit(
    book_id: int,
    user,
    page_number: int,
    version: int,
    ip_address: Optional[str] = None
) -> BookAuditLog:
    """
    Log an edit action for a book page.
    
    Args:
        book_id: ID of the book being edited
        user: User performing the edit
        page_number: Page number that was edited
        version: Page version after edit
        ip_address: Client IP address (optional)
    
    Returns:
        Created BookAuditLog instance
    """
    book = Book.objects.get(pk=book_id)
    return BookAuditLog.objects.create(
        book=book,
        user=user,
        action=BookAuditLog.ACTION_EDIT,
        details={
            'page_number': page_number,
            'version': version,
        },
        ip_address=ip_address,
    )


def log_publish(
    book_id: int,
    user,
    page_count: int,
    ip_address: Optional[str] = None
) -> BookAuditLog:
    """
    Log a publish action for a book.
    
    Args:
        book_id: ID of the book being published
        user: User performing the publish
        page_count: Number of pages published
        ip_address: Client IP address (optional)
    
    Returns:
        Created BookAuditLog instance
    """
    book = Book.objects.get(pk=book_id)
    return BookAuditLog.objects.create(
        book=book,
        user=user,
        action=BookAuditLog.ACTION_PUBLISH,
        details={'page_count': page_count},
        ip_address=ip_address,
    )


def get_audit_log(
    book_id: int,
    action: Optional[str] = None,
    user_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    limit: int = 100
) -> QuerySet[BookAuditLog]:
    """
    Query audit log for a book with optional filters.
    
    Args:
        book_id: ID of the book to query
        action: Filter by action type ('upload', 'edit', 'publish')
        user_id: Filter by user ID
        start_date: Filter by start date (inclusive)
        end_date: Filter by end date (inclusive)
        limit: Maximum number of records to return
    
    Returns:
        QuerySet of BookAuditLog instances
    """
    queryset = BookAuditLog.objects.filter(book_id=book_id)
    
    if action:
        queryset = queryset.filter(action=action)
    
    if user_id:
        queryset = queryset.filter(user_id=user_id)
    
    if start_date:
        queryset = queryset.filter(timestamp__date__gte=start_date)
    
    if end_date:
        queryset = queryset.filter(timestamp__date__lte=end_date)
    
    return queryset.order_by('-timestamp')[:limit]


def get_user_audit_activity(
    user_id: int,
    action: Optional[str] = None,
    limit: int = 100
) -> QuerySet[BookAuditLog]:
    """
    Get audit log entries for a specific user.
    
    Args:
        user_id: ID of the user
        action: Filter by action type
        limit: Maximum number of records
    
    Returns:
        QuerySet of BookAuditLog instances
    """
    queryset = BookAuditLog.objects.filter(user_id=user_id)
    
    if action:
        queryset = queryset.filter(action=action)
    
    return queryset.order_by('-timestamp')[:limit]


def get_recent_audit_activity(
    action: Optional[str] = None,
    limit: int = 100
) -> QuerySet[BookAuditLog]:
    """
    Get recent audit activity across all books.
    
    Args:
        action: Filter by action type
        limit: Maximum number of records
    
    Returns:
        QuerySet of BookAuditLog instances
    """
    queryset = BookAuditLog.objects.all()
    
    if action:
        queryset = queryset.filter(action=action)
    
    return queryset.order_by('-timestamp')[:limit]
