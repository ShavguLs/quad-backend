import pytest
from django.test import TestCase

from apps.books.models import Book, build_book_slug
from apps.users.models import User


class SlugGenerationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='test@example.com',
            password='testpass123',
            first_name='Test',
            last_name='User',
            handle='test_user',
        )

    def test_slug_generation_basic(self):
        book = Book.objects.create(
            title='ვეფხისტყაოსანი',
            author='შოთა რუსთაველი',
            owner=self.user,
            status='published',
            price='10.00',
            category='BOOKS',
        )
        self.assertEqual(book.slug, 'შოთა-რუსთაველი-ვეფხისტყაოსანი')

    def test_slug_generation_with_special_chars(self):
        book = Book.objects.create(
            title='Test Book: A Story',
            author='John Doe',
            owner=self.user,
            status='published',
            price='10.00',
            category='BOOKS',
        )
        self.assertEqual(book.slug, 'john-doe-test-book-a-story')

    def test_slug_generation_max_length_cap(self):
        # Create a very long author + title combination
        long_author = 'ა' * 200
        long_title = 'ბ' * 200
        
        book = Book.objects.create(
            title=long_title,
            author=long_author,
            owner=self.user,
            status='published',
            price='10.00',
            category='BOOKS',
        )
        
        # Slug should be capped at 255 characters
        self.assertLessEqual(len(book.slug), 255)
        # Should not end with a dash
        self.assertFalse(book.slug.endswith('-'))
        # Should not be empty
        self.assertTrue(book.slug)

    def test_slug_generation_empty_fallback(self):
        slug = build_book_slug('', '')
        self.assertEqual(slug, 'book')

    def test_slug_generation_special_chars_only(self):
        slug = build_book_slug('!!!', '???')
        self.assertEqual(slug, 'book')

    def test_slug_generation_preserves_georgian(self):
        slug = build_book_slug('შოთა რუსთაველი', 'ვეფხისტყაოსანი')
        self.assertEqual(slug, 'შოთა-რუსთაველი-ვეფხისტყაოსანი')
        # Verify Georgian characters are preserved
        self.assertIn('შ', slug)
        self.assertIn('ვ', slug)

    def test_slug_generation_mixed_georgian_latin(self):
        slug = build_book_slug('John Smith', 'ქართული წიგნი')
        self.assertEqual(slug, 'john-smith-ქართული-წიგნი')

    def test_slug_generation_removes_multiple_dashes(self):
        slug = build_book_slug('Author  Name', 'Book   Title')
        self.assertNotIn('--', slug)
        self.assertEqual(slug, 'author-name-book-title')

    def test_slug_generation_exact_255_chars(self):
        # Create input that results in exactly 255 chars
        # Each Georgian char is 1 char in Python string length
        author = 'ა' * 127
        title = 'ბ' * 127  # 127 + 1 (dash) + 127 = 255
        
        slug = build_book_slug(author, title)
        self.assertEqual(len(slug), 255)

    def test_slug_generation_over_255_chars_truncates(self):
        # Create input that exceeds 255 chars
        author = 'ა' * 200
        title = 'ბ' * 200
        
        slug = build_book_slug(author, title)
        self.assertEqual(len(slug), 255)
        self.assertFalse(slug.endswith('-'))

    def test_public_path_segment_includes_slug_and_id(self):
        book = Book.objects.create(
            title='ვეფხისტყაოსანი',
            author='შოთა რუსთაველი',
            owner=self.user,
            status='published',
            price='10.00',
            category='BOOKS',
        )
        
        path_segment = book.public_path_segment
        self.assertIn('შოთა-რუსთაველი-ვეფხისტყაოსანი', path_segment)
        self.assertIn(f'--{book.pk}', path_segment)
        self.assertEqual(path_segment, f'შოთა-რუსთაველი-ვეფხისტყაოსანი--{book.pk}')
