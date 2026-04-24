from datetime import timedelta

from django.db import IntegrityError
from django.db.models import BooleanField, Count, Exists, F, OuterRef, Q, Sum, Value
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from .models import CommunityPost, CommunityPostComment, Review, ReviewReply, ReviewVote, SavedCommunityPost, CommunityPostLike
from .permissions import IsAuthor, IsOwnerOrReadOnly
from .serializers import CommunityPostCommentSerializer, CommunityPostSerializer, ReviewSerializer, ReviewReplySerializer


class ReviewViewSet(viewsets.ModelViewSet):
    serializer_class = ReviewSerializer
    permission_classes = [IsAuthenticatedOrReadOnly, IsOwnerOrReadOnly]

    def get_queryset(self):
        # Base queryset - exclude hidden reviews for public, only visible books
        queryset = Review.objects.filter(
            book__status="published",
            book__is_visible=True,
            is_hidden=False,
        ).select_related("book", "user")
        
        # Admin users can see all reviews including hidden
        if self.request.user.is_staff:
            queryset = Review.objects.filter(
                book__status="published"
            ).select_related("book", "user")
        
        # Filter by book if provided
        book_id = self.request.query_params.get('book')
        if book_id:
            queryset = queryset.filter(book_id=book_id)

        queryset = queryset.annotate(
            upvotes_count=Count('votes', filter=Q(votes__vote_type=1)),
            downvotes_count=Count('votes', filter=Q(votes__vote_type=-1)),
            net_score=Sum('votes__vote_type'),
        )
        
        return queryset

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            self.perform_create(serializer)
        except IntegrityError:
            return Response(
                {"error": "Review already exists for this book."},
                status=status.HTTP_409_CONFLICT,
            )

        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def update(self, request, *args, **kwargs):
        """Update review within 24h window."""
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)

        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError as exc:
            # Check if it's the 24h error
            if 'Reviews can only be edited within 24 hours.' in str(exc.detail):
                return Response(
                    {"error": "Reviews can only be edited within 24 hours of posting."},
                    status=status.HTTP_403_FORBIDDEN
                )
            raise

        self.perform_update(serializer)
        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        """Delete review within 24h window."""
        instance = self.get_object()

        # Check 24h window for deletion
        if timezone.now() - instance.created_at > timedelta(hours=24):
            return Response(
                {"error": "Reviews can only be deleted within 24 hours of posting."},
                status=status.HTTP_403_FORBIDDEN
            )

        self.perform_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def vote(self, request, pk=None):
        """Cast or change vote on a review."""
        review = self.get_object()
        vote_type = request.data.get('vote_type')

        if vote_type not in [1, -1]:
            return Response(
                {"error": "vote_type must be 1 (upvote) or -1 (downvote)"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Create or update vote
        vote, created = ReviewVote.objects.update_or_create(
            review=review,
            user=request.user,
            defaults={'vote_type': vote_type}
        )

        return Response({
            "message": "Vote recorded",
            "vote_type": vote.vote_type,
            "upvotes": review.votes.filter(vote_type=1).count(),
            "downvotes": review.votes.filter(vote_type=-1).count(),
        })

    @action(detail=True, methods=['delete'], permission_classes=[IsAuthenticated])
    def remove_vote(self, request, pk=None):
        """Remove user's vote from a review."""
        review = self.get_object()
        deleted, _ = ReviewVote.objects.filter(
            review=review,
            user=request.user
        ).delete()

        if deleted:
            return Response({
                "message": "Vote removed",
                "upvotes": review.votes.filter(vote_type=1).count(),
                "downvotes": review.votes.filter(vote_type=-1).count(),
            })
        return Response(
            {"error": "No vote found"},
            status=status.HTTP_404_NOT_FOUND
        )


class CommunityPostViewSet(viewsets.ModelViewSet):
    serializer_class = CommunityPostSerializer
    permission_classes = [IsAuthenticatedOrReadOnly, IsOwnerOrReadOnly]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'community_writes'

    def get_queryset(self):
        queryset = CommunityPost.objects.select_related("author").annotate(
            comments_count=Count("post_comments")
        ).order_by("-created_at")
        user = self.request.user

        if user.is_authenticated:
            queryset = queryset.annotate(
                is_saved=Exists(
                    SavedCommunityPost.objects.filter(post=OuterRef('pk'), user=user)
                ),
                is_liked=Exists(
                    CommunityPostLike.objects.filter(post=OuterRef('pk'), user=user)
                )
            )

        return queryset

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def save_post(self, request, pk=None):
        post = self.get_object()
        saved, created = SavedCommunityPost.objects.get_or_create(user=request.user, post=post)
        if created:
            return Response({"status": "Post saved"}, status=status.HTTP_201_CREATED)
        return Response({"status": "Post already saved"}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['delete'], permission_classes=[IsAuthenticated])
    def unsave_post(self, request, pk=None):
        post = self.get_object()
        deleted, _ = SavedCommunityPost.objects.filter(user=request.user, post=post).delete()
        if deleted:
            return Response({"status": "Post unsaved"}, status=status.HTTP_204_NO_CONTENT)
        return Response({"error": "Post not saved"}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def like_post(self, request, pk=None):
        post = self.get_object()
        liked, created = CommunityPostLike.objects.get_or_create(user=request.user, post=post)
        if created:
            post.likes = F('likes') + 1
            post.save(update_fields=['likes'])
            post.refresh_from_db(fields=['likes'])
            return Response({"status": "Post liked", "likes": post.likes}, status=status.HTTP_201_CREATED)
        return Response({"status": "Post already liked", "likes": post.likes}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['delete'], permission_classes=[IsAuthenticated])
    def unlike_post(self, request, pk=None):
        post = self.get_object()
        deleted, _ = CommunityPostLike.objects.filter(user=request.user, post=post).delete()
        if deleted:
            CommunityPost.objects.filter(pk=post.pk, likes__gt=0).update(likes=F('likes') - 1)
            post.refresh_from_db(fields=['likes'])
            return Response({"status": "Post unliked", "likes": post.likes}, status=status.HTTP_204_NO_CONTENT)
        return Response({"error": "Post not liked"}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def saved(self, request):
        saved_posts = CommunityPost.objects.filter(
            saved_by_users__user=request.user
        ).select_related("author").annotate(
            comments_count=Count("post_comments"),
            is_saved=Value(True, output_field=BooleanField()),
            is_liked=Exists(
                CommunityPostLike.objects.filter(post=OuterRef('pk'), user=request.user)
            )
        ).order_by("-saved_by_users__created_at")

        page = self.paginate_queryset(saved_posts)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(saved_posts, many=True)
        return Response(serializer.data)


class CommunityPostCommentViewSet(viewsets.ModelViewSet):
    serializer_class = CommunityPostCommentSerializer
    permission_classes = [IsAuthenticatedOrReadOnly, IsAuthor]
    http_method_names = ['get', 'post', 'delete', 'head', 'options']
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'community_writes'

    def get_queryset(self):
        post_id = self.kwargs.get('post_pk')
        if post_id:
            return CommunityPostComment.objects.filter(post_id=post_id).select_related('author')
        return CommunityPostComment.objects.none()

    def perform_create(self, serializer):
        post_id = self.kwargs.get('post_pk')
        post = get_object_or_404(CommunityPost, pk=post_id)
        serializer.save(post=post, author=self.request.user)


class ReviewReplyViewSet(viewsets.ModelViewSet):
    serializer_class = ReviewReplySerializer
    permission_classes = [IsAuthenticatedOrReadOnly, IsAuthor]

    def get_queryset(self):
        review_id = self.kwargs.get('review_pk')
        if review_id:
            return ReviewReply.objects.filter(review_id=review_id).select_related('author')
        return ReviewReply.objects.none()

    def perform_create(self, serializer):
        review_id = self.kwargs.get('review_pk')
        serializer.save(review_id=review_id, author=self.request.user)
