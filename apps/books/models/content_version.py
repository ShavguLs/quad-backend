"""ContentVersion model for snapshot-based content versioning.

Provides version history tracking for BookContent with optimistic locking support.
Uses deepdiff for comparing version differences.
"""

from typing import List, Optional

from django.conf import settings
from django.db import models, transaction


def get_changed_blocks(old_blocks: list, new_blocks: list) -> List[str]:
    """Compare two block lists and return IDs of blocks that changed.
    
    Args:
        old_blocks: Previous version blocks
        new_blocks: Current version blocks
        
    Returns:
        List of block IDs that changed
    """
    changed_ids = []
    
    # Create lookup by ID
    old_by_id = {b.get('id'): b for b in old_blocks if b.get('id')}
    new_by_id = {b.get('id'): b for b in new_blocks if b.get('id')}
    
    # Find all unique IDs
    all_ids = set(old_by_id.keys()) | set(new_by_id.keys())
    
    for block_id in all_ids:
        old_block = old_by_id.get(block_id)
        new_block = new_by_id.get(block_id)
        
        if old_block != new_block:
            changed_ids.append(block_id)
    
    return changed_ids


class ContentVersion(models.Model):
    """Stores a complete snapshot of content blocks for version history.
    
    Each version captures the entire state of a BookContent page at a point in time,
    enabling rollback, comparison, and audit trails.
    """
    
    VERSION_TYPE_CHOICES = [
        ('auto', 'Auto-saved'),
        ('manual', 'Manual save'),
        ('publish', 'Published'),
        ('revert', 'Reverted'),
    ]
    
    book_content = models.ForeignKey(
        'BookContent',
        on_delete=models.CASCADE,
        related_name='versions',
        help_text='The content page this version belongs to'
    )
    version_number = models.PositiveIntegerField(
        help_text='Sequential version number (1, 2, 3...)'
    )
    blocks_snapshot = models.JSONField(
        default=list,
        help_text='Complete copy of blocks at this version'
    )
    version_type = models.CharField(
        max_length=20,
        choices=VERSION_TYPE_CHOICES,
        default='manual',
        help_text='Type of version: auto-save, manual save, publish, or revert'
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text='User who created this version'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text='When this version was created'
    )
    change_summary = models.TextField(
        blank=True,
        help_text='Human-readable summary of changes'
    )
    blocks_changed = models.JSONField(
        default=list,
        help_text='List of block IDs that changed from previous version'
    )
    
    class Meta:
        ordering = ['-version_number']  # Newest first
        constraints = [
            models.UniqueConstraint(
                fields=['book_content', 'version_number'],
                name='unique_content_version_number'
            )
        ]
        indexes = [
            models.Index(
                fields=['book_content', 'version_number'],
                name='content_version_lookup_idx'
            ),
            models.Index(
                fields=['created_at'],
                name='content_version_created_idx'
            ),
        ]
        verbose_name = 'Content Version'
        verbose_name_plural = 'Content Versions'
    
    def __str__(self) -> str:
        return f"{self.book_content} - v{self.version_number} ({self.version_type})"
    
    @property
    def blocks(self) -> list:
        """Return the blocks snapshot (convenience accessor)."""
        return self.blocks_snapshot
    
    def compare_with(self, other_version: 'ContentVersion') -> dict:
        """Compare this version with another using DeepDiff.
        
        Args:
            other_version: Another ContentVersion to compare against
            
        Returns:
            DeepDiff result dictionary showing differences
        """
        from deepdiff import DeepDiff
        
        return DeepDiff(
            self.blocks_snapshot,
            other_version.blocks_snapshot,
            ignore_order=True,
            verbose_level=2
        )
    
    @classmethod
    def create_version(
        cls,
        book_content_id: int,
        blocks: list,
        version_type: str = 'manual',
        user=None,
        change_summary: str = ''
    ) -> 'ContentVersion':
        """Create a new version for a BookContent.
        
        Automatically calculates:
        - Next version number
        - Changed blocks compared to previous version
        
        Args:
            book_content_id: ID of the BookContent
            blocks: Current blocks to snapshot
            version_type: Type of version (auto, manual, publish, revert)
            user: User creating the version (optional)
            change_summary: Human-readable change description
            
        Returns:
            Created ContentVersion instance
        """
        with transaction.atomic():
            # Lock the book content row to prevent race conditions
            from apps.books.models import BookContent
            book_content = BookContent.objects.select_for_update().get(
                id=book_content_id
            )
            
            # Get next version number
            latest = cls.objects.filter(
                book_content=book_content
            ).order_by('-version_number').first()
            next_version = (latest.version_number + 1) if latest else 1
            
            # Calculate changed blocks
            blocks_changed = []
            if latest:
                blocks_changed = get_changed_blocks(
                    latest.blocks_snapshot,
                    blocks
                )
            
            # Create the version
            version = cls.objects.create(
                book_content=book_content,
                version_number=next_version,
                blocks_snapshot=list(blocks),
                version_type=version_type,
                created_by=user,
                change_summary=change_summary,
                blocks_changed=blocks_changed
            )
            
            return version
    
    @classmethod
    def get_latest_for_content(cls, book_content_id: int) -> Optional['ContentVersion']:
        """Get the latest version for a BookContent.
        
        Args:
            book_content_id: ID of the BookContent
            
        Returns:
            Latest ContentVersion or None
        """
        return cls.objects.filter(
            book_content_id=book_content_id
        ).order_by('-version_number').first()
    
    @classmethod
    def cleanup_old_versions(
        cls,
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
        from datetime import timedelta
        from django.utils import timezone
        
        cutoff_date = timezone.now() - timedelta(days=keep_days)
        
        with transaction.atomic():
            # Get versions to potentially delete (auto saves only, not publish/manual)
            candidates = cls.objects.filter(
                book_content_id=book_content_id,
                version_type='auto',
                created_at__lt=cutoff_date
            ).order_by('version_number')
            
            # Count total versions
            total_count = cls.objects.filter(
                book_content_id=book_content_id
            ).count()
            
            # Only delete if we have more than keep_count
            to_delete = []
            for version in candidates:
                if total_count - len(to_delete) <= keep_count:
                    break
                to_delete.append(version.id)
            
            if to_delete:
                deleted, _ = cls.objects.filter(
                    id__in=to_delete
                ).delete()
                return deleted
            
            return 0
