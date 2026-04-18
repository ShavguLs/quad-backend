from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from .models import CommunityPost, SavedCommunityPost, CommunityPostLike

User = get_user_model()

class CommunitySystemTests(APITestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(
            email='testuser1@example.com',
            password='testpassword123',
            first_name='Test',
            last_name='User 1',
            handle='testuser1'
        )
        self.user2 = User.objects.create_user(
            email='testuser2@example.com',
            password='testpassword123',
            first_name='Test',
            last_name='User 2',
            handle='testuser2'
        )
        
        # User 1 creates a post
        self.post1 = CommunityPost.objects.create(
            author=self.user1,
            content="This is a test community post by user 1.",
            category="discussion"
        )
        
        self.client.force_authenticate(user=self.user1)

    def test_create_post(self):
        url = '/community/posts/'
        data = {
            "content": "Newly created post",
            "category": "market"
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(CommunityPost.objects.count(), 2)
        
    def test_save_post(self):
        url = f'/community/posts/{self.post1.id}/save_post/'
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(SavedCommunityPost.objects.count(), 1)
        
        # Saving again should return 200 OK without duplicating
        response2 = self.client.post(url)
        self.assertEqual(response2.status_code, status.HTTP_200_OK)
        self.assertEqual(SavedCommunityPost.objects.count(), 1)

    def test_unsave_post(self):
        SavedCommunityPost.objects.create(user=self.user1, post=self.post1)
        url = f'/community/posts/{self.post1.id}/unsave_post/'
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(SavedCommunityPost.objects.count(), 0)
        
        # Unsaving a post that is not saved should return 404
        response2 = self.client.delete(url)
        self.assertEqual(response2.status_code, status.HTTP_404_NOT_FOUND)

    def test_unsave_post_only_removes_request_user_save(self):
        SavedCommunityPost.objects.create(user=self.user1, post=self.post1)
        SavedCommunityPost.objects.create(user=self.user2, post=self.post1)

        url = f'/community/posts/{self.post1.id}/unsave_post/'
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(SavedCommunityPost.objects.filter(user=self.user1, post=self.post1).exists())
        self.assertTrue(SavedCommunityPost.objects.filter(user=self.user2, post=self.post1).exists())

    def test_get_saved_posts(self):
        # User 1 saves the post
        SavedCommunityPost.objects.create(user=self.user1, post=self.post1)
        
        url = '/community/posts/saved/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # It's returning a paginated response potentially, or a list, check length of results
        results = response.data.get('results', response.data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], self.post1.id)
        self.assertTrue(results[0]['is_saved'])

    def test_get_saved_posts_is_user_scoped(self):
        post2 = CommunityPost.objects.create(
            author=self.user2,
            content='Post saved only by user 2.',
            category='discussion',
        )
        SavedCommunityPost.objects.create(user=self.user1, post=self.post1)
        SavedCommunityPost.objects.create(user=self.user2, post=post2)

        url = '/community/posts/saved/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get('results', response.data)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], self.post1.id)
        self.assertTrue(results[0]['is_saved'])

    def test_like_post(self):
        url = f'/community/posts/{self.post1.id}/like_post/'
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(CommunityPostLike.objects.count(), 1)
        
        self.post1.refresh_from_db()
        self.assertEqual(self.post1.likes, 1)
        
        # Should not double like
        response2 = self.client.post(url)
        self.assertEqual(response2.status_code, status.HTTP_200_OK)
        self.assertEqual(CommunityPostLike.objects.count(), 1)
        
        self.post1.refresh_from_db()
        self.assertEqual(self.post1.likes, 1)

    def test_unlike_post(self):
        # Setup initial like
        CommunityPostLike.objects.create(user=self.user1, post=self.post1)
        self.post1.likes = 1
        self.post1.save()
        
        url = f'/community/posts/{self.post1.id}/unlike_post/'
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(CommunityPostLike.objects.count(), 0)
        
        self.post1.refresh_from_db()
        self.assertEqual(self.post1.likes, 0)
        
        # Unlike a post not previously liked
        response2 = self.client.delete(url)
        self.assertEqual(response2.status_code, status.HTTP_404_NOT_FOUND)

    def test_get_community_posts_metadata(self):
        # Make a post, like it with user 2, save it with user 1
        CommunityPostLike.objects.create(user=self.user2, post=self.post1)
        SavedCommunityPost.objects.create(user=self.user1, post=self.post1)
        
        url = '/community/posts/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get('results', response.data)
        self.assertEqual(len(results), 1)
        
        post_data = results[0]
        # Current user is user1
        self.assertTrue(post_data['is_saved'])
        self.assertFalse(post_data['is_liked'])
        
        # Switch to user 2
        self.client.force_authenticate(user=self.user2)
        response2 = self.client.get(url)
        results2 = response2.data.get('results', response2.data)
        
        post_data2 = results2[0]
        self.assertFalse(post_data2['is_saved'])
        self.assertTrue(post_data2['is_liked'])

    def test_user_can_create_up_to_three_posts_per_day(self):
        CommunityPost.objects.filter(pk=self.post1.pk).delete()
        url = '/community/posts/'

        for index in range(3):
            response = self.client.post(
                url,
                {
                    "content": f"Allowed post {index + 1}",
                    "category": "discussion",
                },
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.assertEqual(CommunityPost.objects.filter(author=self.user1).count(), 3)

    def test_fourth_post_same_day_is_rejected(self):
        url = '/community/posts/'

        CommunityPost.objects.create(author=self.user1, content='Second post today', category='discussion')
        CommunityPost.objects.create(author=self.user1, content='Third post today', category='discussion')

        response = self.client.post(
            url,
            {
                "content": "Fourth post should fail",
                "category": "discussion",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data['non_field_errors'][0],
            'You can add at most 3 community posts per day.',
        )

    def test_other_user_is_not_blocked_by_daily_limit(self):
        url = '/community/posts/'

        CommunityPost.objects.create(author=self.user1, content='Second post today', category='discussion')
        CommunityPost.objects.create(author=self.user1, content='Third post today', category='discussion')

        self.client.force_authenticate(user=self.user2)
        response = self.client.post(
            url,
            {
                "content": "User 2 can still post",
                "category": "discussion",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_user_can_post_again_on_next_day(self):
        url = '/community/posts/'

        CommunityPost.objects.create(author=self.user1, content='Second post today', category='discussion')
        CommunityPost.objects.create(author=self.user1, content='Third post today', category='discussion')

        with patch('apps.social.serializers.timezone.localdate', return_value=self.post1.created_at.date() + timedelta(days=1)):
            response = self.client.post(
                url,
                {
                    "content": "Next day post is allowed",
                    "category": "discussion",
                },
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_unauthenticated_user_still_cannot_create_post(self):
        self.client.force_authenticate(user=None)

        response = self.client.post(
            '/community/posts/',
            {
                "content": "Anonymous post attempt",
                "category": "discussion",
            },
        )

        self.assertIn(response.status_code, {status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN})

    def test_create_post_ignores_client_supplied_likes(self):
        response = self.client.post(
            '/community/posts/',
            {
                'content': 'Attempt to set likes field from client',
                'category': 'discussion',
                'likes': 99999,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        created_post = CommunityPost.objects.get(pk=response.data['id'])
        self.assertEqual(created_post.likes, 0)
        self.assertEqual(response.data['likes'], 0)
