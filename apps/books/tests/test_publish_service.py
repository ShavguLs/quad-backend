"""Tests for publish service behavior."""

from django.test import TestCase

from apps.books.models import Book, BookContent
from apps.books.publish import PublishError, PublishService
from apps.users.models import User


class PublishServiceTests(TestCase):
    """Tests for the current status-based PublishService."""

    def setUp(self):
        self.user = User.objects.create_user(
            email='test@example.com',
            password='testpass123',
            first_name='Test',
            last_name='User',
            handle='testuser',
        )
        self.other_user = User.objects.create_user(
            email='other@example.com',
            password='testpass123',
            first_name='Other',
            last_name='User',
            handle='otheruser',
        )
        self.book = Book.objects.create(
            title='Test Book',
            author='Test Author',
            owner=self.user,
            status='draft',
            total_pages=2,
        )
        BookContent.objects.create(
            book=self.book,
            page_number=1,
            blocks=[{'type': 'paragraph', 'text': 'Page 1 content'}],
        )
        BookContent.objects.create(
            book=self.book,
            page_number=2,
            blocks=[{'type': 'paragraph', 'text': 'Page 2 content'}],
        )

    def test_successful_publish(self):
        service = PublishService()

        result = service.publish_book(self.book.id, self.user)

        self.assertTrue(result.success)
        self.assertEqual(result.book_id, self.book.id)
        self.assertEqual(result.pages_published, 2)
        self.assertIsNone(result.error_message)

        self.book.refresh_from_db()
        self.assertEqual(self.book.status, 'published')

    def test_only_owner_can_publish(self):
        service = PublishService()

        with self.assertRaises(PublishError) as cm:
            service.publish_book(self.book.id, self.other_user)

        self.assertIn('owner', str(cm.exception).lower())

    def test_only_draft_can_be_published(self):
        self.book.status = 'published'
        self.book.save(update_fields=['status'])
        service = PublishService()

        with self.assertRaises(PublishError) as cm:
            service.publish_book(self.book.id, self.user)

        self.assertIn('already published', str(cm.exception).lower())

    def test_invalid_status_cannot_publish(self):
        self.book.status = 'queued'
        self.book.save(update_fields=['status'])
        service = PublishService()

        with self.assertRaises(PublishError) as cm:
            service.publish_book(self.book.id, self.user)

        self.assertIn('cannot publish', str(cm.exception).lower())

    def test_publish_requires_content_pages(self):
        empty_book = Book.objects.create(
            title='Empty Book',
            author='Test Author',
            owner=self.user,
            status='draft',
            total_pages=0,
        )
        service = PublishService()

        with self.assertRaises(PublishError) as cm:
            service.publish_book(empty_book.id, self.user)

        self.assertIn('no pages', str(cm.exception).lower())

    def test_publish_result_dataclass(self):
        from apps.books.publish.service import PublishResult

        success_result = PublishResult(
            success=True,
            book_id=123,
            pages_published=5,
            error_message=None,
        )
        self.assertTrue(success_result.success)
        self.assertEqual(success_result.book_id, 123)
        self.assertEqual(success_result.pages_published, 5)

        failure_result = PublishResult(
            success=False,
            book_id=456,
            pages_published=0,
            error_message='Something went wrong',
        )
        self.assertFalse(failure_result.success)
        self.assertEqual(failure_result.error_message, 'Something went wrong')
