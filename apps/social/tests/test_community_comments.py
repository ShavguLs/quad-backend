import pytest
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from apps.social.models import CommunityPost, CommunityPostComment


User = get_user_model()


@pytest.mark.unit
class CommunityPostCommentViewSetTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="commenter@example.com",
            password="testpass123",
            first_name="Comment",
            last_name="Author",
            handle="commentauthor",
        )
        self.other_user = User.objects.create_user(
            email="other@example.com",
            password="testpass123",
            first_name="Other",
            last_name="User",
            handle="otheruser",
        )

        self.post = CommunityPost.objects.create(
            author=self.other_user,
            content="Primary community post",
            category="discussion",
        )
        self.other_post = CommunityPost.objects.create(
            author=self.other_user,
            content="Secondary community post",
            category="discussion",
        )
        self.parent_comment = CommunityPostComment.objects.create(
            post=self.post,
            author=self.other_user,
            content="Parent comment",
        )
        self.other_parent_comment = CommunityPostComment.objects.create(
            post=self.post,
            author=self.other_user,
            content="Another parent comment",
        )
        self.cross_post_parent = CommunityPostComment.objects.create(
            post=self.other_post,
            author=self.other_user,
            content="Cross post parent",
        )

        self.client.force_authenticate(user=self.user)

    def comment_url(self, post_id):
        return f"/community/posts/{post_id}/comments/"

    def create_comment(self, post_id, content, parent=None):
        payload = {"content": content}
        if parent is not None:
            payload["parent"] = parent
        return self.client.post(self.comment_url(post_id), payload, format="json")

    def assert_error_message(self, response, expected_message):
        messages = response.data.get("non_field_errors", response.data)
        if isinstance(messages, list):
            self.assertEqual(messages[0], expected_message)
            return
        self.fail(f"Unexpected error payload: {response.data}")

    def test_user_can_create_three_top_level_comments_on_same_post(self):
        for index in range(3):
            response = self.create_comment(self.post.id, f"Top level comment {index}")
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.assertEqual(
            CommunityPostComment.objects.filter(
                post=self.post,
                author=self.user,
                parent__isnull=True,
            ).count(),
            3,
        )

    def test_fourth_top_level_comment_on_same_post_is_rejected(self):
        for index in range(3):
            self.create_comment(self.post.id, f"Top level comment {index}")

        response = self.create_comment(self.post.id, "Top level comment 3")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assert_error_message(response, "You can add at most 3 comments on one post.")

    def test_user_can_still_comment_on_different_post_after_hitting_limit(self):
        for index in range(3):
            self.create_comment(self.post.id, f"Top level comment {index}")

        response = self.create_comment(self.other_post.id, "Different post comment")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_user_can_create_ten_replies_on_same_parent_comment(self):
        for index in range(10):
            response = self.create_comment(
                self.post.id,
                f"Reply {index}",
                parent=self.parent_comment.id,
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.assertEqual(
            CommunityPostComment.objects.filter(
                post=self.post,
                author=self.user,
                parent=self.parent_comment,
            ).count(),
            10,
        )

    def test_eleventh_reply_on_same_parent_comment_is_rejected(self):
        for index in range(10):
            self.create_comment(self.post.id, f"Reply {index}", parent=self.parent_comment.id)

        response = self.create_comment(self.post.id, "Reply 10", parent=self.parent_comment.id)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assert_error_message(response, "You can add at most 10 replies to one comment.")

    def test_user_can_reply_to_different_parent_after_hitting_reply_limit(self):
        for index in range(10):
            self.create_comment(self.post.id, f"Reply {index}", parent=self.parent_comment.id)

        response = self.create_comment(self.post.id, "Reply on other parent", parent=self.other_parent_comment.id)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_other_user_is_not_blocked_by_another_users_limit(self):
        for index in range(3):
            self.create_comment(self.post.id, f"Top level comment {index}")

        self.client.force_authenticate(user=self.other_user)
        response = self.create_comment(self.post.id, "Other user comment")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_reply_parent_must_belong_to_same_post(self):
        response = self.create_comment(self.post.id, "Invalid cross-post reply", parent=self.cross_post_parent.id)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assert_error_message(response, "Reply must belong to the same post.")

    def test_unauthenticated_user_cannot_create_comment(self):
        self.client.force_authenticate(user=None)

        response = self.create_comment(self.post.id, "Anonymous comment")

        self.assertIn(
            response.status_code,
            {status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN},
        )

    def test_comment_listing_behavior_remains_unchanged(self):
        top_level = CommunityPostComment.objects.create(
            post=self.post,
            author=self.user,
            content="Listed top level comment",
        )
        reply = CommunityPostComment.objects.create(
            post=self.post,
            author=self.user,
            parent=top_level,
            content="Listed reply",
        )

        response = self.client.get(self.comment_url(self.post.id))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get("results", response.data)
        self.assertEqual(len(results), 4)
        self.assertEqual(results[-2]["id"], top_level.id)
        self.assertEqual(results[-2]["parent"], None)
        self.assertEqual(results[-1]["id"], reply.id)
        self.assertEqual(results[-1]["parent"], top_level.id)
