"""
Admin configuration for social app.

Registers Review and CommunityPost models with moderation actions.
"""

from django.contrib import admin, messages
from django.utils import timezone

from apps.social.models import CommunityPost, Review


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    """Admin configuration for Review model with moderation actions."""

    list_display = [
        'id',
        'book',
        'user',
        'rating',
        'truncated_content',
        'is_flagged',
        'is_hidden',
        'created_at',
    ]
    list_filter = [
        'is_flagged',
        'is_hidden',
        'rating',
        'created_at',
    ]
    search_fields = [
        'content',
        'user__email',
        'user__handle',
        'book__title',
    ]
    raw_id_fields = ['book', 'user']
    actions = [
        'flag_reviews',
        'hide_reviews',
        'unhide_reviews',
        'unflag_reviews',
        'remove_reviews',
    ]
    readonly_fields = [
        'created_at',
        'updated_at',
        'moderated_at',
        'moderated_by',
    ]
    fieldsets = (
        ('Review Content', {
            'fields': ('book', 'user', 'rating', 'content')
        }),
        ('Moderation', {
            'fields': ('is_flagged', 'is_hidden', 'moderation_reason'),
            'classes': ('collapse',),
        }),
        ('Audit', {
            'fields': ('created_at', 'updated_at', 'moderated_at', 'moderated_by'),
            'classes': ('collapse',),
        }),
    )

    def truncated_content(self, obj):
        """Return truncated content for list display."""
        return obj.content[:100] + '...' if len(obj.content) > 100 else obj.content
    truncated_content.short_description = 'Content'

    @admin.action(description='Flag selected reviews for moderation')
    def flag_reviews(self, request, queryset):
        """Flag selected reviews for moderation."""
        count = queryset.update(is_flagged=True)
        self.message_user(
            request,
            f'{count} review(s) flagged.',
            messages.SUCCESS
        )

    @admin.action(description='Hide selected reviews from public')
    def hide_reviews(self, request, queryset):
        """Hide selected reviews from public view."""
        count = queryset.filter(is_hidden=False).update(
            is_hidden=True,
            is_flagged=False,
            moderated_by=request.user,
            moderated_at=timezone.now(),
        )
        self.message_user(
            request,
            f'{count} review(s) hidden.',
            messages.SUCCESS
        )

    @admin.action(description='Unhide selected reviews')
    def unhide_reviews(self, request, queryset):
        """Unhide selected reviews (make visible again)."""
        count = queryset.filter(is_hidden=True).update(is_hidden=False)
        self.message_user(
            request,
            f'{count} review(s) unhidden.',
            messages.SUCCESS
        )

    @admin.action(description='Remove flag from selected reviews')
    def unflag_reviews(self, request, queryset):
        """Remove flag from selected reviews."""
        count = queryset.filter(is_flagged=True).update(is_flagged=False)
        self.message_user(
            request,
            f'{count} review(s) unflagged.',
            messages.SUCCESS
        )

    @admin.action(description='PERMANENTLY DELETE selected reviews')
    def remove_reviews(self, request, queryset):
        """Permanently delete selected reviews."""
        count = queryset.count()
        queryset.delete()
        self.message_user(
            request,
            f'{count} review(s) permanently deleted.',
            messages.WARNING
        )


@admin.register(CommunityPost)
class CommunityPostAdmin(admin.ModelAdmin):
    """Admin configuration for CommunityPost model with moderation actions."""

    list_display = ['author', 'category', 'content_preview', 'likes', 'comment_count', 'created_at']
    list_filter = ['category', 'created_at']
    search_fields = ['author__email', 'content']
    raw_id_fields = ['author']
    fields = ['author', 'category', 'content', 'image_url', 'likes']
    readonly_fields = ['created_at', 'updated_at']
    actions = ['reset_likes', 'delete_posts']

    def content_preview(self, obj):
        """Return truncated content for list display."""
        return obj.content[:100] + '...' if len(obj.content) > 100 else obj.content
    content_preview.short_description = 'Content Preview'

    @admin.display(description='Comments')
    def comment_count(self, obj):
        """Return current comment count for list display."""
        return obj.post_comments.count()

    @admin.action(description='Reset likes on selected posts')
    def reset_likes(self, request, queryset):
        """Reset likes count to 0 for selected posts."""
        count = queryset.update(likes=0)
        self.message_user(
            request,
            f'{count} post(s) had their likes reset.',
            messages.SUCCESS
        )

    @admin.action(description='Delete selected posts')
    def delete_posts(self, request, queryset):
        """Permanently delete selected community posts."""
        count = queryset.count()
        queryset.delete()
        self.message_user(
            request,
            f'{count} post(s) deleted.',
            messages.SUCCESS
        )
