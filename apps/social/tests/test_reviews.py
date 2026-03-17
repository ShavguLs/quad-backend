"""
Unit tests for the reviews system.

Covers:
- Review model methods (flag, hide, unhide, unflag)
- ReviewVote model behavior
- ReviewReply model behavior
- ReviewViewSet API endpoints
- ReviewReplyViewSet API endpoints
- Permission checks (ownership, purchase requirement)
- 24-hour edit/delete window enforcement
- Voting system (upvote/downvote/remove)
- Moderation workflows
"""

import pytest
from datetime import timedelta
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from rest_framework.test import APITestCase
from rest_framework import status

from apps.social.models import Review, ReviewVote, ReviewReply
from apps.books.models import Book
from apps.orders.models import Order


User = get_user_model()


@pytest.mark.unit
class ReviewModelTests(APITestCase):
    """Unit tests for Review model methods and constraints."""

    def setUp(self):
        self.user = User.objects.create_user(
            email='test@example.com',
            password='testpass123',
            first_name='Test',
            last_name='User',
            handle='testuser'
        )
        self.admin_user = User.objects.create_user(
            email='admin@example.com',
            password='adminpass123',
            first_name='Admin',
            last_name='User',
            handle='adminuser',
            is_staff=True
        )
        self.book = Book.objects.create(
            title='Test Book',
            author='Test Author',
            owner=self.user,
            status='published'
        )
        self.review = Review.objects.create(
            book=self.book,
            user=self.user,
            rating=4,
            content='Great book!'
        )

    def test_review_str_representation(self):
        """Review string representation includes rating and user."""
        self.assertEqual(str(self.review), f"Review 4/5 by {self.user}")

    def test_unique_review_per_user_book_constraint(self):
        """User can only leave one review per book."""
        with self.assertRaises(IntegrityError):
            Review.objects.create(
                book=self.book,
                user=self.user,
                rating=3,
                content='Another review'
            )

    def test_flag_review(self):
        """Flagging a review sets is_flagged True."""
        self.assertFalse(self.review.is_flagged)
        self.review.flag(reason='Inappropriate content')
        self.review.refresh_from_db()
        self.assertTrue(self.review.is_flagged)
        self.assertEqual(self.review.moderation_reason, 'Inappropriate content')

    def test_hide_review(self):
        """Hiding a review sets is_hidden and clears flag."""
        self.review.flag()
        self.review.hide(self.admin_user, reason='Violates guidelines')
        self.review.refresh_from_db()
        self.assertTrue(self.review.is_hidden)
        self.assertFalse(self.review.is_flagged)
        self.assertEqual(self.review.moderated_by, self.admin_user)
        self.assertIsNotNone(self.review.moderated_at)

    def test_unhide_review(self):
        """Unhiding a review makes it visible again."""
        self.review.hide(self.admin_user)
        self.review.unhide()
        self.review.refresh_from_db()
        self.assertFalse(self.review.is_hidden)

    def test_unflag_review(self):
        """Unflagging removes flag without hiding."""
        self.review.flag()
        self.review.unflag()
        self.review.refresh_from_db()
        self.assertFalse(self.review.is_flagged)
        self.assertFalse(self.review.is_hidden)

    def test_review_ordering(self):
        """Reviews are ordered by created_at descending."""
        older_review = Review.objects.create(
            book=self.book,
            user=User.objects.create_user(
                email='older@example.com',
                password='testpass123',
                first_name='Older',
                last_name='User',
                handle='olderuser'
            ),
            rating=5,
            content='Older review'
        )
        # Force older timestamp
        older_review.created_at = timezone.now() - timedelta(days=1)
        older_review.save()
        
        reviews = list(Review.objects.all())
        self.assertEqual(reviews[0], self.review)
        self.assertEqual(reviews[1], older_review)


@pytest.mark.unit
class ReviewVoteModelTests(APITestCase):
    """Unit tests for ReviewVote model."""

    def setUp(self):
        self.user1 = User.objects.create_user(
            email='user1@example.com',
            password='testpass123',
            first_name='User',
            last_name='One',
            handle='userone'
        )
        self.user2 = User.objects.create_user(
            email='user2@example.com',
            password='testpass123',
            first_name='User',
            last_name='Two',
            handle='usertwo'
        )
        self.book = Book.objects.create(
            title='Test Book',
            author='Test Author',
            owner=self.user1,
            status='published'
        )
        self.review = Review.objects.create(
            book=self.book,
            user=self.user1,
            rating=4,
            content='Good book'
        )

    def test_upvote_creation(self):
        """Can create upvote on review."""
        vote = ReviewVote.objects.create(
            review=self.review,
            user=self.user2,
            vote_type=ReviewVote.UPVOTE
        )
        self.assertEqual(vote.vote_type, 1)
        self.assertEqual(str(vote), f"upvote by {self.user2} on review {self.review.id}")

    def test_downvote_creation(self):
        """Can create downvote on review."""
        vote = ReviewVote.objects.create(
            review=self.review,
            user=self.user2,
            vote_type=ReviewVote.DOWNVOTE
        )
        self.assertEqual(vote.vote_type, -1)
        self.assertEqual(str(vote), f"downvote by {self.user2} on review {self.review.id}")

    def test_unique_vote_per_user_review(self):
        """User can only vote once per review."""
        ReviewVote.objects.create(
            review=self.review,
            user=self.user2,
            vote_type=ReviewVote.UPVOTE
        )
        with self.assertRaises(IntegrityError):
            ReviewVote.objects.create(
                review=self.review,
                user=self.user2,
                vote_type=ReviewVote.DOWNVOTE
            )

    def test_vote_ordering(self):
        """Votes ordered by created_at descending."""
        vote1 = ReviewVote.objects.create(
            review=self.review,
            user=self.user2,
            vote_type=ReviewVote.UPVOTE
        )
        vote2 = ReviewVote.objects.create(
            review=self.review,
            user=User.objects.create_user(
                email='user3@example.com',
                password='testpass123',
                first_name='User',
                last_name='Three',
                handle='userthree'
            ),
            vote_type=ReviewVote.UPVOTE
        )
        votes = list(ReviewVote.objects.all())
        self.assertEqual(votes[0], vote2)
        self.assertEqual(votes[1], vote1)


@pytest.mark.unit
class ReviewReplyModelTests(APITestCase):
    """Unit tests for ReviewReply model."""

    def setUp(self):
        self.user = User.objects.create_user(
            email='test@example.com',
            password='testpass123',
            first_name='Test',
            last_name='User',
            handle='testuser'
        )
        self.book = Book.objects.create(
            title='Test Book',
            author='Test Author',
            owner=self.user,
            status='published'
        )
        self.review = Review.objects.create(
            book=self.book,
            user=User.objects.create_user(
                email='reviewer@example.com',
                password='testpass123',
                first_name='Reviewer',
                last_name='User',
                handle='revieweruser'
            ),
            rating=4,
            content='Good book'
        )

    def test_reply_creation(self):
        """Can create reply to review."""
        reply = ReviewReply.objects.create(
            review=self.review,
            author=self.user,
            content='Thank you for your review!'
        )
        self.assertEqual(reply.review, self.review)
        self.assertEqual(reply.author, self.user)
        self.assertEqual(str(reply), f"Reply by {self.user} on review {self.review.id}")

    def test_reply_ordering(self):
        """Replies ordered by created_at ascending."""
        reply1 = ReviewReply.objects.create(
            review=self.review,
            author=self.user,
            content='First reply'
        )
        reply2 = ReviewReply.objects.create(
            review=self.review,
            author=self.user,
            content='Second reply'
        )
        replies = list(self.review.replies.all())
        self.assertEqual(replies[0], reply1)
        self.assertEqual(replies[1], reply2)


@pytest.mark.unit
class ReviewViewSetTests(APITestCase):
    """Unit tests for ReviewViewSet API endpoints."""

    def setUp(self):
        self.book_owner = User.objects.create_user(
            email='owner@example.com',
            password='testpass123',
            first_name='Book',
            last_name='Owner',
            handle='bookowner'
        )
        self.reviewer = User.objects.create_user(
            email='reviewer@example.com',
            password='testpass123',
            first_name='Reviewer',
            last_name='User',
            handle='revieweruser'
        )
        self.other_user = User.objects.create_user(
            email='other@example.com',
            password='testpass123',
            first_name='Other',
            last_name='User',
            handle='otheruser'
        )
        self.admin_user = User.objects.create_user(
            email='admin@example.com',
            password='adminpass123',
            first_name='Admin',
            last_name='User',
            handle='adminuser',
            is_staff=True
        )
        
        self.published_book = Book.objects.create(
            title='Published Book',
            author='Test Author',
            owner=self.book_owner,
            status='published',
            price=10.00
        )
        self.draft_book = Book.objects.create(
            title='Draft Book',
            author='Test Author',
            owner=self.book_owner,
            status='draft'
        )
        
        # Create completed order for reviewer
        Order.objects.create(
            buyer=self.reviewer,
            book=self.published_book,
            amount=10.00,
            status=Order.STATUS_COMPLETED
        )

    def test_list_reviews(self):
        """Can list reviews for a published book."""
        review = Review.objects.create(
            book=self.published_book,
            user=self.reviewer,
            rating=4,
            content='Great book!'
        )
        
        url = '/reviews/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['id'], review.id)

    def test_list_reviews_filter_by_book(self):
        """Can filter reviews by book ID."""
        review = Review.objects.create(
            book=self.published_book,
            user=self.reviewer,
            rating=4,
            content='Great book!'
        )
        
        url = f'/reviews/?book={self.published_book.id}'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)

    def test_hidden_reviews_excluded_for_public(self):
        """Hidden reviews are not visible to public users."""
        review = Review.objects.create(
            book=self.published_book,
            user=self.reviewer,
            rating=4,
            content='Great book!'
        )
        review.hide(self.admin_user)
        
        url = '/reviews/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 0)

    def test_hidden_reviews_visible_to_staff(self):
        """Hidden reviews are visible to staff users."""
        review = Review.objects.create(
            book=self.published_book,
            user=self.reviewer,
            rating=4,
            content='Great book!'
        )
        review.hide(self.admin_user)
        
        self.client.force_authenticate(user=self.admin_user)
        url = '/reviews/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)

    def test_create_review_requires_auth(self):
        """Creating review requires authentication."""
        url = '/reviews/'
        data = {
            'book': self.published_book.id,
            'rating': 5,
            'content': 'Excellent!'
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_create_review_requires_purchase(self):
        """Creating review requires purchasing the book."""
        self.client.force_authenticate(user=self.other_user)
        url = '/reviews/'
        data = {
            'book': self.published_book.id,
            'rating': 5,
            'content': 'Excellent!'
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('purchase', str(response.data).lower())

    def test_create_review_requires_published_book(self):
        """Can only review published books."""
        # Create order for draft book
        Order.objects.create(
            buyer=self.reviewer,
            book=self.draft_book,
            amount=10.00,
            status=Order.STATUS_COMPLETED
        )
        
        self.client.force_authenticate(user=self.reviewer)
        url = '/reviews/'
        data = {
            'book': self.draft_book.id,
            'rating': 5,
            'content': 'Excellent!'
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('published', str(response.data).lower())

    def test_create_review_success(self):
        """Purchaser can create review for published book."""
        self.client.force_authenticate(user=self.reviewer)
        url = '/reviews/'
        data = {
            'book': self.published_book.id,
            'rating': 5,
            'content': 'Excellent book!'
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Review.objects.count(), 1)
        self.assertEqual(response.data['rating'], 5)

    def test_create_duplicate_review_returns_conflict(self):
        """Creating duplicate review returns 409 conflict."""
        Review.objects.create(
            book=self.published_book,
            user=self.reviewer,
            rating=4,
            content='First review'
        )
        
        self.client.force_authenticate(user=self.reviewer)
        url = '/reviews/'
        data = {
            'book': self.published_book.id,
            'rating': 5,
            'content': 'Second review'
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_update_review_within_24h(self):
        """Can update review within 24 hours."""
        review = Review.objects.create(
            book=self.published_book,
            user=self.reviewer,
            rating=4,
            content='Original content'
        )
        
        self.client.force_authenticate(user=self.reviewer)
        url = f'/reviews/{review.id}/'
        data = {
            'rating': 5,
            'content': 'Updated content'
        }
        response = self.client.patch(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        review.refresh_from_db()
        self.assertEqual(review.rating, 5)
        self.assertEqual(review.content, 'Updated content')

    def test_update_review_after_24h_fails(self):
        """Cannot update review after 24 hours."""
        review = Review.objects.create(
            book=self.published_book,
            user=self.reviewer,
            rating=4,
            content='Original content'
        )
        # Force created_at to be older than 24h
        review.created_at = timezone.now() - timedelta(hours=25)
        review.save()
        
        self.client.force_authenticate(user=self.reviewer)
        url = f'/reviews/{review.id}/'
        data = {
            'rating': 5,
            'content': 'Updated content'
        }
        response = self.client.patch(url, data)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_review_within_24h(self):
        """Can delete review within 24 hours."""
        review = Review.objects.create(
            book=self.published_book,
            user=self.reviewer,
            rating=4,
            content='Review to delete'
        )
        
        self.client.force_authenticate(user=self.reviewer)
        url = f'/reviews/{review.id}/'
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(Review.objects.count(), 0)

    def test_delete_review_after_24h_fails(self):
        """Cannot delete review after 24 hours."""
        review = Review.objects.create(
            book=self.published_book,
            user=self.reviewer,
            rating=4,
            content='Review to delete'
        )
        # Force created_at to be older than 24h
        review.created_at = timezone.now() - timedelta(hours=25)
        review.save()
        
        self.client.force_authenticate(user=self.reviewer)
        url = f'/reviews/{review.id}/'
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(Review.objects.count(), 1)

    def test_only_owner_can_update_review(self):
        """Only review owner can update their review."""
        review = Review.objects.create(
            book=self.published_book,
            user=self.reviewer,
            rating=4,
            content='Original'
        )
        
        self.client.force_authenticate(user=self.other_user)
        url = f'/reviews/{review.id}/'
        data = {
            'book': self.published_book.id,
            'rating': 5,
            'content': 'Hacked!'
        }
        response = self.client.put(url, data)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_vote_upvote(self):
        """Can upvote a review."""
        review = Review.objects.create(
            book=self.published_book,
            user=self.reviewer,
            rating=4,
            content='Good book'
        )

        self.client.force_authenticate(user=self.other_user)
        url = f'/reviews/{review.id}/vote/'
        data = {'vote_type': 1}
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['vote_type'], 1)
        self.assertEqual(response.data['upvotes'], 1)
        self.assertEqual(response.data['downvotes'], 0)

    def test_vote_downvote(self):
        """Can downvote a review."""
        review = Review.objects.create(
            book=self.published_book,
            user=self.reviewer,
            rating=4,
            content='Good book'
        )

        self.client.force_authenticate(user=self.other_user)
        url = f'/reviews/{review.id}/vote/'
        data = {'vote_type': -1}
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['vote_type'], -1)
        self.assertEqual(response.data['upvotes'], 0)
        self.assertEqual(response.data['downvotes'], 1)

    def test_vote_invalid_type(self):
        """Invalid vote type returns 400."""
        review = Review.objects.create(
            book=self.published_book,
            user=self.reviewer,
            rating=4,
            content='Good book'
        )

        self.client.force_authenticate(user=self.other_user)
        url = f'/reviews/{review.id}/vote/'
        data = {'vote_type': 2}
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_change_vote(self):
        """Can change existing vote."""
        review = Review.objects.create(
            book=self.published_book,
            user=self.reviewer,
            rating=4,
            content='Good book'
        )

        self.client.force_authenticate(user=self.other_user)
        url = f'/reviews/{review.id}/vote/'

        # First upvote
        self.client.post(url, {'vote_type': 1}, format='json')
        # Then change to downvote
        response = self.client.post(url, {'vote_type': -1}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['vote_type'], -1)
        self.assertEqual(response.data['upvotes'], 0)
        self.assertEqual(response.data['downvotes'], 1)

    def test_remove_vote(self):
        """Can remove vote from review."""
        review = Review.objects.create(
            book=self.published_book,
            user=self.reviewer,
            rating=4,
            content='Good book'
        )
        
        self.client.force_authenticate(user=self.other_user)
        # First add a vote
        self.client.post(f'/reviews/{review.id}/vote/', {'vote_type': 1}, format='json')

        # Then remove it
        url = f'/reviews/{review.id}/remove_vote/'
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['upvotes'], 0)

    def test_remove_nonexistent_vote(self):
        """Removing vote that doesn't exist returns 404."""
        review = Review.objects.create(
            book=self.published_book,
            user=self.reviewer,
            rating=4,
            content='Good book'
        )
        
        self.client.force_authenticate(user=self.other_user)
        url = f'/reviews/{review.id}/remove_vote/'
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_review_serializer_includes_vote_counts(self):
        """Review serializer includes upvotes, downvotes, and netScore."""
        review = Review.objects.create(
            book=self.published_book,
            user=self.reviewer,
            rating=4,
            content='Good book'
        )
        ReviewVote.objects.create(
            review=review,
            user=self.other_user,
            vote_type=ReviewVote.UPVOTE
        )
        user3 = User.objects.create_user(
            email='user3@example.com',
            password='testpass123',
            first_name='User',
            last_name='Three',
            handle='userthree'
        )
        ReviewVote.objects.create(
            review=review,
            user=user3,
            vote_type=ReviewVote.UPVOTE
        )
        
        self.client.force_authenticate(user=self.reviewer)
        url = '/reviews/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        review_data = response.data['results'][0]
        self.assertEqual(review_data['upvotes'], 2)
        self.assertEqual(review_data['downvotes'], 0)
        self.assertEqual(review_data['netScore'], 2)

    def test_review_serializer_user_vote(self):
        """Review serializer includes current user's vote."""
        review = Review.objects.create(
            book=self.published_book,
            user=self.reviewer,
            rating=4,
            content='Good book'
        )
        ReviewVote.objects.create(
            review=review,
            user=self.other_user,
            vote_type=ReviewVote.DOWNVOTE
        )
        
        self.client.force_authenticate(user=self.other_user)
        url = '/reviews/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        review_data = response.data['results'][0]
        self.assertEqual(review_data['userVote'], -1)

    def test_moderation_info_for_staff(self):
        """Moderation info only shown to staff users."""
        review = Review.objects.create(
            book=self.published_book,
            user=self.reviewer,
            rating=4,
            content='Good book'
        )
        review.flag(reason='Spam')
        
        # Non-staff user
        self.client.force_authenticate(user=self.reviewer)
        url = '/reviews/'
        response = self.client.get(url)
        self.assertIsNone(response.data['results'][0]['moderationInfo'])
        
        # Staff user
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(url)
        mod_info = response.data['results'][0]['moderationInfo']
        self.assertIsNotNone(mod_info)
        self.assertTrue(mod_info['isFlagged'])
        self.assertEqual(mod_info['moderationReason'], 'Spam')


@pytest.mark.unit
class ReviewReplyViewSetTests(APITestCase):
    """Unit tests for ReviewReplyViewSet API endpoints."""

    def setUp(self):
        self.book_owner = User.objects.create_user(
            email='owner@example.com',
            password='testpass123',
            first_name='Book',
            last_name='Owner',
            handle='bookowner'
        )
        self.reviewer = User.objects.create_user(
            email='reviewer@example.com',
            password='testpass123',
            first_name='Reviewer',
            last_name='User',
            handle='revieweruser'
        )
        self.other_user = User.objects.create_user(
            email='other@example.com',
            password='testpass123',
            first_name='Other',
            last_name='User',
            handle='otheruser'
        )
        
        self.published_book = Book.objects.create(
            title='Published Book',
            author='Test Author',
            owner=self.book_owner,
            status='published'
        )
        self.review = Review.objects.create(
            book=self.published_book,
            user=self.reviewer,
            rating=4,
            content='Great book!'
        )

    def test_list_replies(self):
        """Can list replies for a review."""
        reply = ReviewReply.objects.create(
            review=self.review,
            author=self.book_owner,
            content='Thank you!'
        )
        
        url = f'/reviews/{self.review.id}/replies/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['content'], 'Thank you!')

    def test_create_reply_requires_auth(self):
        """Creating reply requires authentication."""
        url = f'/reviews/{self.review.id}/replies/'
        data = {'content': 'Thank you for the review!'}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_create_reply_success(self):
        """Book owner can reply to review."""
        self.client.force_authenticate(user=self.book_owner)
        url = f'/reviews/{self.review.id}/replies/'
        data = {'content': 'Thank you for the review!'}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ReviewReply.objects.count(), 1)

    def test_delete_reply_by_author(self):
        """Reply author can delete their reply."""
        reply = ReviewReply.objects.create(
            review=self.review,
            author=self.book_owner,
            content='Thank you!'
        )
        
        self.client.force_authenticate(user=self.book_owner)
        url = f'/reviews/{self.review.id}/replies/{reply.id}/'
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(ReviewReply.objects.count(), 0)

    def test_delete_reply_by_non_author_fails(self):
        """Non-author cannot delete someone else's reply."""
        reply = ReviewReply.objects.create(
            review=self.review,
            author=self.book_owner,
            content='Thank you!'
        )
        
        self.client.force_authenticate(user=self.other_user)
        url = f'/reviews/{self.review.id}/replies/{reply.id}/'
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(ReviewReply.objects.count(), 1)

    def test_reply_included_in_review_detail(self):
        """Replies are included in review detail response."""
        reply = ReviewReply.objects.create(
            review=self.review,
            author=self.book_owner,
            content='Thank you for the kind words!'
        )
        
        url = f'/reviews/{self.review.id}/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['replies']), 1)
        self.assertEqual(response.data['replies'][0]['content'], 'Thank you for the kind words!')
