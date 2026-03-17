"""ContentService with optimistic locking for concurrent edit safety.

Provides business logic for content updates with version-based conflict detection,
auto-save throttling, and version management.
"""

import logging
from datetime import timedelta
from typing import List, Optional

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.books.models import BookContent, ContentVersion

logger = logging.getLogger(__name__)


class OptimisticLockingError(Exception):
    """Raised when concurrent modification is detected.
    
    Attributes:
        expected_version: The version the client expected
        current_version: The actual current version in database
        message: Human-readable error description
    """
    
    def __init__(
        self,
        expected_version: int,
        current_version: int,
        message: Optional[str] = None
    ):
        self.expected_version = expected_version
        self.current_version = current_version
        if message is None:
            message = (
                f"Concurrent modification detected. "
                f"Expected version {expected_version}, "
                f"but current version is {current_version}. "
                f"Please refresh and try again."
            )
        super().__init__(message)


class ContentService:
    """Service for content operations with optimistic locking.
    
    All update operations use select_for_update() to prevent race conditions
    and implement version checking for conflict detection.
    """
    
    # Auto-save throttling constants
    AUTO_SAVE_MIN_INTERVAL_SECONDS = 30
    AUTO_SAVE_MAX_COUNT = 20
    
    @staticmethod
    @transaction.atomic
    def update_content(
        book_content_id: int,
        blocks: List[dict],
        expected_version: int,
        user=None,
        change_summary: str = ''
    ) -> BookContent:
        """Update content with optimistic locking.
        
        Args:
            book_content_id: ID of the BookContent to update
            blocks: New blocks content
            expected_version: Version number client expects (for locking)
            user: User making the update (for version tracking)
            change_summary: Human-readable description of changes
            
        Returns:
            Updated BookContent instance
            
        Raises:
            OptimisticLockingError: If version mismatch detected (409 CONFLICT)
            ValidationError: If blocks fail validation
            BookContent.DoesNotExist: If content not found
        """
        # Lock the row to prevent concurrent updates
        book_content = BookContent.objects.select_for_update().get(
            id=book_content_id
        )
        
        # Check version for optimistic locking
        if book_content.version != expected_version:
            raise OptimisticLockingError(
                expected_version=expected_version,
                current_version=book_content.version
            )
        
        # Validate blocks
        ContentService.validate_blocks(blocks)
        
        # Update content
        book_content.blocks = blocks
        book_content.version += 1
        book_content.save()
        
        # Create version record
        ContentVersion.create_version(
            book_content_id=book_content.id,
            blocks=blocks,
            version_type='manual',
            user=user,
            change_summary=change_summary
        )
        
        logger.info(
            f"Content {book_content_id} updated: "
            f"version {expected_version} -> {book_content.version}"
        )
        
        return book_content
    
    @staticmethod
    def get_content_for_edit(book_content_id: int) -> dict:
        """Get content with version for optimistic locking.
        
        Args:
            book_content_id: ID of the BookContent
            
        Returns:
            Dict with content data including version for locking
            
        Raises:
            BookContent.DoesNotExist: If content not found
        """
        book_content = BookContent.objects.get(id=book_content_id)
        
        return {
            'id': book_content.id,
            'book_id': book_content.book_id,
            'page_number': book_content.page_number,
            'blocks': book_content.blocks,
            'version': book_content.version,
            'block_count': book_content.block_count,
            'word_count': book_content.word_count,
            'updated_at': book_content.updated_at.isoformat(),
            'created_at': book_content.created_at.isoformat(),
        }
    
    @staticmethod
    @transaction.atomic
    def create_auto_save(
        book_content_id: int,
        blocks: List[dict],
        user=None
    ) -> Optional[ContentVersion]:
        """Create auto-save version with throttling.
        
        Auto-saves are throttled to:
        - Max 1 per AUTO_SAVE_MIN_INTERVAL_SECONDS (30 seconds)
        - Max AUTO_SAVE_MAX_COUNT (20) auto-saves retained per content
        
        Args:
            book_content_id: ID of the BookContent
            blocks: Current blocks to save
            user: User creating the auto-save
            
        Returns:
            Created ContentVersion or None if throttled
        """
        # Lock the content
        book_content = BookContent.objects.select_for_update().get(
            id=book_content_id
        )
        
        # Check throttle - don't save if recent auto-save exists
        recent_cutoff = timezone.now() - timedelta(
            seconds=ContentService.AUTO_SAVE_MIN_INTERVAL_SECONDS
        )
        
        recent_auto_save = ContentVersion.objects.filter(
            book_content=book_content,
            version_type='auto',
            created_at__gte=recent_cutoff
        ).first()
        
        if recent_auto_save:
            logger.debug(
                f"Auto-save throttled for content {book_content_id}: "
                f"last save at {recent_auto_save.created_at}"
            )
            return None
        
        # Validate blocks (but don't fail - just log)
        try:
            ContentService.validate_blocks(blocks)
        except ValidationError as e:
            logger.warning(
                f"Auto-save validation warning for content {book_content_id}: {e}"
            )
        
        # Update content version (for edit tracking, not locking)
        book_content.blocks = blocks
        book_content.save()
        
        # Create auto-save version
        version = ContentVersion.create_version(
            book_content_id=book_content.id,
            blocks=blocks,
            version_type='auto',
            user=user,
            change_summary='Auto-saved'
        )
        
        # Clean up old auto-saves
        ContentService._cleanup_auto_saves(book_content_id)
        
        logger.info(
            f"Auto-save created for content {book_content_id}: "
            f"version {version.version_number}"
        )
        
        return version
    
    @staticmethod
    def validate_blocks(blocks: List[dict]) -> None:
        """Validate blocks using schema validation.
        
        Args:
            blocks: List of block dictionaries to validate
            
        Raises:
            ValidationError: If blocks fail validation
        """
        from apps.books.validators import validate_blocks as validator
        
        try:
            validator(blocks, strict=False)
        except Exception as e:
            raise ValidationError(f"Block validation failed: {e}")
    
    @staticmethod
    def _cleanup_auto_saves(book_content_id: int) -> int:
        """Clean up old auto-saves keeping only AUTO_SAVE_MAX_COUNT.
        
        Args:
            book_content_id: ID of the BookContent
            
        Returns:
            Number of auto-saves deleted
        """
        # Get auto-saves ordered by newest first
        auto_saves = ContentVersion.objects.filter(
            book_content_id=book_content_id,
            version_type='auto'
        ).order_by('-version_number')
        
        count = auto_saves.count()
        if count <= ContentService.AUTO_SAVE_MAX_COUNT:
            return 0
        
        # Delete excess auto-saves
        to_delete = auto_saves[ContentService.AUTO_SAVE_MAX_COUNT:]
        delete_ids = [v.id for v in to_delete]
        
        deleted, _ = ContentVersion.objects.filter(
            id__in=delete_ids
        ).delete()
        
        logger.debug(
            f"Cleaned up {deleted} old auto-saves for content {book_content_id}"
        )
        
        return deleted
    
    @staticmethod
    @transaction.atomic
    def restore_version(
        book_content_id: int,
        version_id: int,
        user=None
    ) -> BookContent:
        """Restore content to a specific version.
        
        Creates an auto-save of current state before restoring.
        
        Args:
            book_content_id: ID of the BookContent to restore
            version_id: ID of the ContentVersion to restore to
            user: User performing the restore
            
        Returns:
            Updated BookContent instance
            
        Raises:
            ContentVersion.DoesNotExist: If version not found
            BookContent.DoesNotExist: If content not found
        """
        # Lock the content
        book_content = BookContent.objects.select_for_update().get(
            id=book_content_id
        )
        
        # Get the version to restore
        target_version = ContentVersion.objects.get(
            id=version_id,
            book_content=book_content
        )
        
        # Save current state as auto-save first
        ContentVersion.create_version(
            book_content_id=book_content.id,
            blocks=book_content.blocks,
            version_type='auto',
            user=user,
            change_summary='Auto-saved before restore'
        )
        
        # Restore blocks
        book_content.blocks = target_version.blocks_snapshot
        book_content.version += 1
        book_content.save()
        
        # Create revert version record
        ContentVersion.create_version(
            book_content_id=book_content.id,
            blocks=target_version.blocks_snapshot,
            version_type='revert',
            user=user,
            change_summary=f'Restored to version {target_version.version_number}'
        )
        
        logger.info(
            f"Content {book_content_id} restored to version {version_id} "
            f"(v{target_version.version_number})"
        )
        
        return book_content
    
    @staticmethod
    def cleanup_old_versions(
        book_content_id: int,
        keep_count: int = 100,
        keep_days: int = 90
    ) -> int:
        """Remove old versions while keeping important ones.
        
        Args:
            book_content_id: ID of the BookContent
            keep_count: Minimum number of versions to keep
            keep_days: Delete versions older than this many days
            
        Returns:
            Number of versions deleted
        """
        return ContentVersion.cleanup_old_versions(
            book_content_id=book_content_id,
            keep_count=keep_count,
            keep_days=keep_days
        )
