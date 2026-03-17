"""
Tests for the library app.
"""

from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.books.models import Book
from apps.library.views import MyLibraryViewSet, PurchasedLibraryViewSet, UserLibraryViewSet
from apps.orders.models import Order
from apps.users.models import User


class MyLibraryViewSetTests(TestCase):
    """Tests for MyLibraryViewSet."""
    
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = User.objects.create_user(
            email='test@example.com',
            password='testpass123',
            first_name='Test',
            last_name='User',
            handle='testuser'
        )
        self.other_user = User.objects.create_user(
            email='other@example.com',
            password='testpass123',
            first_name='Other',
            last_name='User',
            handle='otheruser'
        )
        
        # Create books for test user
        self.draft_book = Book.objects.create(
            owner=self.user,
            title='Draft Book',
            author='Test Author',
            description='A draft book',
            status='draft'
        )
        self.published_book = Book.objects.create(
            owner=self.user,
            title='Published Book',
            author='Test Author',
            description='A published book',
            status='published'
        )
        
        # Create book for other user
        self.other_book = Book.objects.create(
            owner=self.other_user,
            title='Other Book',
            author='Other Author',
            description='Another book',
            status='published'
        )
        self.pending_book = Book.objects.create(
            owner=self.other_user,
            title='Pending Book',
            author='Other Author',
            description='Pending book',
            status='published'
        )
    
    def test_my_library_requires_authentication(self):
        """Anonymous users should get 401 when accessing /library/me/."""
        request = self.factory.get('/library/me/')
        view = MyLibraryViewSet.as_view({'get': 'list'})
        response = view(request)
        
        self.assertEqual(response.status_code, 401)
    
    def test_my_library_returns_all_user_books(self):
        """Authenticated user should see all their books (drafts + published)."""
        request = self.factory.get('/library/me/')
        force_authenticate(request, user=self.user)
        
        view = MyLibraryViewSet.as_view({'get': 'list'})
        response = view(request)
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 2)
        
        # Check both books are present
        book_ids = [book['id'] for book in response.data['results']]
        self.assertIn(self.draft_book.id, book_ids)
        self.assertIn(self.published_book.id, book_ids)
    
    def test_my_library_does_not_show_other_user_books(self):
        """User should not see other users' books in their library."""
        request = self.factory.get('/library/me/')
        force_authenticate(request, user=self.user)
        
        view = MyLibraryViewSet.as_view({'get': 'list'})
        response = view(request)
        
        self.assertEqual(response.status_code, 200)
        
        # Check other user's book is not present
        book_ids = [book['id'] for book in response.data['results']]
        self.assertNotIn(self.other_book.id, book_ids)

    def test_my_library_includes_completed_purchases_only(self):
        """Completed purchases should appear; pending orders should not."""
        Order.objects.create(
            buyer=self.user,
            book=self.other_book,
            amount=Decimal('9.99'),
            status=Order.STATUS_COMPLETED
        )
        Order.objects.create(
            buyer=self.user,
            book=self.pending_book,
            amount=Decimal('7.50'),
            status=Order.STATUS_PENDING
        )

        request = self.factory.get('/library/me/')
        force_authenticate(request, user=self.user)

        view = MyLibraryViewSet.as_view({'get': 'list'})
        response = view(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 3)

        book_ids = [book['id'] for book in response.data['results']]
        self.assertIn(self.other_book.id, book_ids)
        self.assertNotIn(self.pending_book.id, book_ids)


class UserLibraryViewSetTests(TestCase):
    """Tests for UserLibraryViewSet."""
    
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = User.objects.create_user(
            email='test@example.com',
            password='testpass123',
            first_name='Test',
            last_name='User',
            handle='testuser'
        )
        
        # Create books for test user
        self.draft_book = Book.objects.create(
            owner=self.user,
            title='Draft Book',
            author='Test Author',
            description='A draft book',
            status='draft'
        )
        self.published_book = Book.objects.create(
            owner=self.user,
            title='Published Book',
            author='Test Author',
            description='A published book',
            status='published'
        )
    
    def test_user_library_is_public(self):
        """Anonymous users can access /library/users/{handle}/."""
        request = self.factory.get(f'/library/users/{self.user.handle}/')
        view = UserLibraryViewSet.as_view({'get': 'list'})
        response = view(request, handle=self.user.handle)
        
        self.assertEqual(response.status_code, 200)
    
    def test_user_library_shows_only_published(self):
        """User library should only show published books."""
        request = self.factory.get(f'/library/users/{self.user.handle}/')
        view = UserLibraryViewSet.as_view({'get': 'list'})
        response = view(request, handle=self.user.handle)
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        
        # Only published book should be present
        book_ids = [book['id'] for book in response.data['results']]
        self.assertIn(self.published_book.id, book_ids)
        self.assertNotIn(self.draft_book.id, book_ids)
    
    def test_user_library_handles_nonexistent_user(self):
        """Non-existent user should return empty list, not 404."""
        request = self.factory.get('/library/users/nonexistentuser/')
        view = UserLibraryViewSet.as_view({'get': 'list'})
        response = view(request, handle='nonexistentuser')
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 0)
        self.assertEqual(len(response.data['results']), 0)
    
    def test_user_library_is_case_insensitive(self):
        """Handle lookup should be case-insensitive."""
        # Test with uppercase handle
        request = self.factory.get('/library/users/TESTUSER/')
        view = UserLibraryViewSet.as_view({'get': 'list'})
        response = view(request, handle='TESTUSER')
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)

    def test_user_library_normalizes_whitespace_and_nfkc(self):
        """Handle lookup should normalize whitespace and unicode forms."""
        request = self.factory.get('/library/users/%20%20%EF%BC%B4%EF%BC%A5%EF%BC%B3%EF%BC%B4%EF%BC%B5%EF%BC%B3%EF%BC%A5%EF%BC%B2%20%20/')
        view = UserLibraryViewSet.as_view({'get': 'list'})
        response = view(request, handle='  ＴＥＳＴＵＳＥＲ  ')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
    
    def test_user_library_includes_pagination(self):
        """Response should include pagination fields."""
        request = self.factory.get(f'/library/users/{self.user.handle}/')
        view = UserLibraryViewSet.as_view({'get': 'list'})
        response = view(request, handle=self.user.handle)
        
        self.assertEqual(response.status_code, 200)
        self.assertIn('count', response.data)
        self.assertIn('next', response.data)
        self.assertIn('previous', response.data)
        self.assertIn('results', response.data)


class PurchasedLibraryViewSetTests(TestCase):
    """Tests for PurchasedLibraryViewSet."""

    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = User.objects.create_user(
            email='buyer@example.com',
            password='testpass123',
            first_name='Buyer',
            last_name='User',
            handle='buyeruser'
        )
        self.seller = User.objects.create_user(
            email='seller@example.com',
            password='testpass123',
            first_name='Seller',
            last_name='User',
            handle='selleruser'
        )

        self.published_book = Book.objects.create(
            owner=self.seller,
            title='Published Purchase',
            author='Seller Author',
            description='Published book',
            status='published'
        )
        self.draft_book = Book.objects.create(
            owner=self.seller,
            title='Draft Purchase',
            author='Seller Author',
            description='Draft book',
            status='draft'
        )

    def test_purchased_library_requires_authentication(self):
        """Anonymous users should get 401 when accessing /library/purchased/."""
        request = self.factory.get('/library/purchased/')
        view = PurchasedLibraryViewSet.as_view({'get': 'list'})
        response = view(request)

        self.assertEqual(response.status_code, 401)

    def test_purchased_library_returns_only_completed_published_books(self):
        """List should include only completed purchases of published books."""
        pending_published_book = Book.objects.create(
            owner=self.seller,
            title='Pending Published Purchase',
            author='Seller Author',
            description='Pending published book',
            status='published'
        )

        Order.objects.create(
            buyer=self.user,
            book=self.published_book,
            amount=Decimal('10.00'),
            status=Order.STATUS_COMPLETED
        )
        Order.objects.create(
            buyer=self.user,
            book=self.draft_book,
            amount=Decimal('10.00'),
            status=Order.STATUS_COMPLETED
        )
        Order.objects.create(
            buyer=self.user,
            book=pending_published_book,
            amount=Decimal('10.00'),
            status=Order.STATUS_PENDING
        )

        request = self.factory.get('/library/purchased/')
        force_authenticate(request, user=self.user)

        view = PurchasedLibraryViewSet.as_view({'get': 'list'})
        response = view(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['id'], self.published_book.id)

    def test_purchased_library_retrieve_blocks_unpurchased_books(self):
        """Retrieve should return 404 for books the user did not purchase."""
        request = self.factory.get(f'/library/purchased/{self.published_book.id}/')
        force_authenticate(request, user=self.user)

        view = PurchasedLibraryViewSet.as_view({'get': 'retrieve'})
        response = view(request, id=self.published_book.id)

        self.assertEqual(response.status_code, 404)
