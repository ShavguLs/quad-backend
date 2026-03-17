from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_nested.routers import NestedDefaultRouter

from .views import CommunityPostCommentViewSet, CommunityPostViewSet, ReviewReplyViewSet, ReviewViewSet

router = DefaultRouter()
router.register(r"reviews", ReviewViewSet, basename="reviews")
router.register(r"community/posts", CommunityPostViewSet, basename="community-posts")

# Nested router for review replies
reviews_router = NestedDefaultRouter(router, r"reviews", lookup="review")
reviews_router.register(r"replies", ReviewReplyViewSet, basename="review-replies")

# Nested router for post comments  →  /community/posts/{post_pk}/comments/
posts_router = NestedDefaultRouter(router, r"community/posts", lookup="post")
posts_router.register(r"comments", CommunityPostCommentViewSet, basename="post-comments")

urlpatterns = [
    path("", include(router.urls)),
    path("", include(reviews_router.urls)),
    path("", include(posts_router.urls)),
]
