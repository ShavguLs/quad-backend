from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers

from apps.books.models import Book
from apps.orders.models import Order

from .models import CommunityPost, CommunityPostComment, Review, ReviewReply


def _display_name(user):
    first = (user.first_name or "").strip()
    last = (user.last_name or "").strip()
    full = " ".join(part for part in [first, last] if part)
    return full or user.handle


class ReviewReplySerializer(serializers.ModelSerializer):
    author = serializers.SerializerMethodField()
    createdAt = serializers.DateTimeField(source='created_at', format='iso-8601', read_only=True)

    class Meta:
        model = ReviewReply
        fields = [
            'id',
            'author',
            'content',
            'createdAt',
        ]
        read_only_fields = ['author', 'createdAt']

    def get_author(self, obj):
        avatar = None
        if obj.author.profile_image:
            request = self.context.get('request')
            if request:
                avatar = request.build_absolute_uri(obj.author.profile_image.url)
            else:
                avatar = obj.author.profile_image.url
        return {
            'name': _display_name(obj.author),
            'handle': obj.author.handle,
            'avatar': avatar
        }

class ReviewSerializer(serializers.ModelSerializer):
    user = serializers.SerializerMethodField()
    userHandle = serializers.SerializerMethodField()
    avatar = serializers.SerializerMethodField()
    bookTitle = serializers.CharField(source="book.title", read_only=True)
    bookId = serializers.IntegerField(source="book.id", read_only=True)
    date = serializers.DateTimeField(source="created_at", format="iso-8601", read_only=True)
    book = serializers.PrimaryKeyRelatedField(queryset=Book.objects.all(), write_only=True)
    upvotes = serializers.SerializerMethodField()
    downvotes = serializers.SerializerMethodField()
    netScore = serializers.SerializerMethodField()
    userVote = serializers.SerializerMethodField()
    replies = ReviewReplySerializer(many=True, read_only=True)
    moderationInfo = serializers.SerializerMethodField()

    class Meta:
        model = Review
        fields = [
            "id",
            "user",
            "userHandle",
            "avatar",
            "bookTitle",
            "bookId",
            "rating",
            "content",
            "date",
            "book",
            "upvotes",
            "downvotes",
            "netScore",
            "userVote",
            "replies",
            "moderationInfo",
        ]

    def get_upvotes(self, obj):
        return getattr(obj, 'upvotes_count', obj.votes.filter(vote_type=1).count())

    def get_downvotes(self, obj):
        return getattr(obj, 'downvotes_count', obj.votes.filter(vote_type=-1).count())

    def get_netScore(self, obj):
        annotated_score = getattr(obj, 'net_score', None)
        if annotated_score is not None:
            return annotated_score
        return obj.votes.aggregate(score=Sum('vote_type'))['score'] or 0

    def get_userVote(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            vote = obj.votes.filter(user=request.user).first()
            return vote.vote_type if vote else None
        return None

    def get_user(self, obj):
        return _display_name(obj.user)

    def get_userHandle(self, obj):
        return obj.user.handle

    def get_avatar(self, obj):
        if obj.user.profile_image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.user.profile_image.url)
            return obj.user.profile_image.url
        return None

    def get_moderationInfo(self, obj):
        """Return moderation info for staff users only."""
        request = self.context.get('request')
        # Only show moderation info to staff users
        if request and request.user.is_staff:
            return {
                'isFlagged': obj.is_flagged,
                'isHidden': obj.is_hidden,
                'moderationReason': obj.moderation_reason,
                'moderatedAt': obj.moderated_at.isoformat() if obj.moderated_at else None,
                'moderatedBy': _display_name(obj.moderated_by) if obj.moderated_by else None,
            }
        return None

    def validate(self, attrs):
        request = self.context.get("request")
        user = getattr(request, "user", None)

        # Validate content length (min 10 chars)
        content = attrs.get("content", "")
        if content and len(content.strip()) < 10:
            raise serializers.ValidationError({"content": "Review must be at least 10 characters."})

        if self.instance is not None:
            if "book" in attrs:
                raise serializers.ValidationError({"book": "Book cannot be updated."})

            if timezone.now() - self.instance.created_at > timedelta(hours=24):
                raise serializers.ValidationError("Reviews can only be edited within 24 hours.")

            return attrs

        book = attrs.get("book")
        if book is None:
            return attrs

        if book.status != "published":
            raise serializers.ValidationError({"book": "Reviews can only be left on published books."})

        if user and user.is_authenticated:
            has_purchase = Order.objects.filter(
                buyer=user,
                book=book,
                status=Order.STATUS_COMPLETED,
            ).exists()
            if not has_purchase:
                raise serializers.ValidationError("You must purchase a book before reviewing it.")

        return attrs


class CommunityPostCommentSerializer(serializers.ModelSerializer):
    author = serializers.SerializerMethodField()
    handle = serializers.SerializerMethodField()
    avatar = serializers.SerializerMethodField()
    createdAt = serializers.DateTimeField(source='created_at', format='iso-8601', read_only=True)

    class Meta:
        model = CommunityPostComment
        fields = ['id', 'author', 'handle', 'avatar', 'content', 'createdAt', 'parent']
        read_only_fields = ['author', 'handle', 'avatar', 'createdAt']

    def get_author(self, obj):
        return _display_name(obj.author)

    def get_handle(self, obj):
        return obj.author.handle

    def get_avatar(self, obj):
        if obj.author.profile_image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.author.profile_image.url)
            return obj.author.profile_image.url
        return None

    def validate(self, attrs):
        if self.instance is not None:
            return attrs

        request = self.context.get("request")
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return attrs

        post = getattr(self.instance, "post", None)
        if post is None:
            view = self.context.get("view")
            post_pk = None
            if view is not None:
                post_pk = view.kwargs.get("post_pk")
            if post_pk is None:
                return attrs
            post = CommunityPost.objects.filter(pk=post_pk).only("id").first()

        if post is None:
            return attrs

        parent = attrs.get("parent")
        if parent is None:
            top_level_count = CommunityPostComment.objects.filter(
                post=post,
                author=user,
                parent__isnull=True,
            ).count()
            if top_level_count >= 3:
                raise serializers.ValidationError("You can add at most 3 comments on one post.")
            return attrs

        if parent.post_id != post.id:
            raise serializers.ValidationError("Reply must belong to the same post.")

        reply_count = CommunityPostComment.objects.filter(
            post=post,
            author=user,
            parent=parent,
        ).count()
        if reply_count >= 10:
            raise serializers.ValidationError("You can add at most 10 replies to one comment.")

        return attrs

class CommunityPostSerializer(serializers.ModelSerializer):
    author = serializers.SerializerMethodField()
    handle = serializers.CharField(source="author.handle", read_only=True)
    avatar = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()
    timestamp = serializers.DateTimeField(source="created_at", format="iso-8601", read_only=True)
    comments = serializers.SerializerMethodField()
    recent_comments = serializers.SerializerMethodField()
    is_saved = serializers.SerializerMethodField()
    is_liked = serializers.SerializerMethodField()
    image_url = serializers.URLField(required=False, allow_blank=True, write_only=True)

    class Meta:
        model = CommunityPost
        fields = [
            "id",
            "author",
            "handle",
            "avatar",
            "content",
            "image",
            "timestamp",
            "likes",
            "comments",
            "recent_comments",
            "is_saved",
            "is_liked",
            "category",
            "image_url",
        ]
        extra_kwargs = {
            "category": {"required": False, "allow_blank": True},
        }

    def get_author(self, obj):
        return _display_name(obj.author)

    def get_avatar(self, obj):
        if obj.author.profile_image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.author.profile_image.url)
            return obj.author.profile_image.url
        return None

    def get_image(self, obj):
        return obj.image_url or None

    def get_likes(self, obj):
        return obj.likes or 0

    def get_comments(self, obj):
        return obj.post_comments.count()

    def get_recent_comments(self, obj):
        # We slice first 2 comments from the prefetched post_comments
        comments = list(obj.post_comments.all())[:2]
        return CommunityPostCommentSerializer(comments, many=True, context=self.context).data

    def get_is_saved(self, obj):
        request = self.context.get('request')
        if getattr(obj, "is_saved", None) is not None:
            return obj.is_saved
            
        if request and request.user.is_authenticated:
            # First try checking prefetched data if it was set
            if hasattr(obj, '_prefetched_objects_cache') and 'saved_by_users' in obj._prefetched_objects_cache:
                return any(save.user_id == request.user.id for save in obj.saved_by_users.all())
            return obj.saved_by_users.filter(user=request.user).exists()
        return False

    def get_is_liked(self, obj):
        request = self.context.get('request')
        if getattr(obj, "is_liked", None) is not None:
            return obj.is_liked
            
        if request and request.user.is_authenticated:
            if hasattr(obj, '_prefetched_objects_cache') and 'liked_by_users' in obj._prefetched_objects_cache:
                return any(like.user_id == request.user.id for like in obj.liked_by_users.all())
            return obj.liked_by_users.filter(user=request.user).exists()
        return False
