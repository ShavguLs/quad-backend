from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from apps.books.models import Book


class Review(models.Model):
    book = models.ForeignKey(
        Book,
        on_delete=models.CASCADE,
        related_name='reviews',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='reviews',
    )
    rating = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Moderation fields
    is_flagged = models.BooleanField(default=False, db_index=True)
    is_hidden = models.BooleanField(default=False, db_index=True)
    moderation_reason = models.TextField(blank=True)
    moderated_at = models.DateTimeField(null=True, blank=True)
    moderated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='moderated_reviews',
    )

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['book', 'user'],
                name='unique_review_per_user_book'
            )
        ]
        indexes = [
            models.Index(fields=['is_flagged', 'is_hidden']),
        ]

    def __str__(self) -> str:
        return f"Review {self.rating}/5 by {self.user}"

    def flag(self, reason=''):
        """Flag review for moderation."""
        self.is_flagged = True
        if reason:
            self.moderation_reason = reason
        self.save(update_fields=['is_flagged', 'moderation_reason'])

    def hide(self, admin_user, reason=''):
        """Hide review from public view."""
        self.is_hidden = True
        self.is_flagged = False  # Clear flag when hidden
        self.moderated_by = admin_user
        self.moderated_at = timezone.now()
        if reason:
            self.moderation_reason = reason
        self.save(update_fields=[
            'is_hidden', 'is_flagged', 'moderated_by',
            'moderated_at', 'moderation_reason'
        ])

    def unhide(self):
        """Unhide review (make visible again)."""
        self.is_hidden = False
        self.save(update_fields=['is_hidden'])

    def unflag(self):
        """Remove flag without hiding."""
        self.is_flagged = False
        self.save(update_fields=['is_flagged'])


class ReviewVote(models.Model):
    UPVOTE = 1
    DOWNVOTE = -1

    VOTE_CHOICES = [
        (UPVOTE, 'Upvote'),
        (DOWNVOTE, 'Downvote'),
    ]

    review = models.ForeignKey(
        Review,
        on_delete=models.CASCADE,
        related_name='votes',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='review_votes',
    )
    vote_type = models.IntegerField(choices=VOTE_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['review', 'user']
        ordering = ['-created_at']

    def __str__(self) -> str:
        vote = "upvote" if self.vote_type == self.UPVOTE else "downvote"
        return f"{vote} by {self.user} on review {self.review.id}"


class ReviewReply(models.Model):
    review = models.ForeignKey(
        Review,
        on_delete=models.CASCADE,
        related_name='replies',
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='review_replies',
    )
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = 'Review Reply'
        verbose_name_plural = 'Review Replies'

    def __str__(self) -> str:
        return f"Reply by {self.author} on review {self.review.id}"


class CommunityPost(models.Model):
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='community_posts',
    )
    content = models.TextField()
    category = models.CharField(max_length=100, default='general')
    image_url = models.URLField(blank=True)
    likes = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f"Post by {self.author}"


class CommunityPostComment(models.Model):
    post = models.ForeignKey(
        CommunityPost,
        on_delete=models.CASCADE,
        related_name='post_comments',
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='community_comments',
    )
    parent = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='replies'
    )
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = 'Community Post Comment'
        verbose_name_plural = 'Community Post Comments'

    def __str__(self) -> str:
        return f"Comment by {self.author} on post {self.post.id}"


class SavedCommunityPost(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='saved_community_posts',
    )
    post = models.ForeignKey(
        CommunityPost,
        on_delete=models.CASCADE,
        related_name='saved_by_users',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ['user', 'post']
        verbose_name = 'Saved Community Post'
        verbose_name_plural = 'Saved Community Posts'

    def __str__(self) -> str:
        return f"{self.user} saved post {self.post.id}"


class CommunityPostLike(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='liked_community_posts',
    )
    post = models.ForeignKey(
        CommunityPost,
        on_delete=models.CASCADE,
        related_name='liked_by_users',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ['user', 'post']
        verbose_name = 'Community Post Like'
        verbose_name_plural = 'Community Post Likes'

    def __str__(self) -> str:
        return f"{self.user} liked post {self.post.id}"
