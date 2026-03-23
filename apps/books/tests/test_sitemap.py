from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.books.models import Book
from apps.users.models import User


@override_settings(SITE_BASE_URL='https://quaduni.com')
class SitemapXmlTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(
            email='owner@example.com',
            password='testpass123',
            first_name='Owner',
            last_name='User',
            handle='owner_user',
        )

    def test_sitemap_includes_public_routes_and_visible_books_only(self):
        public_book = Book.objects.create(
            title='ვეფხისტყაოსანი',
            author='შოთა რუსთაველი',
            owner=self.owner,
            status='published',
            is_visible=True,
            price='10.00',
            category='BOOKS',
        )
        Book.objects.create(
            title='Draft Book',
            author='Owner User',
            owner=self.owner,
            status='draft',
            is_visible=True,
            price='10.00',
            category='BOOKS',
        )
        Book.objects.create(
            title='Hidden Book',
            author='Owner User',
            owner=self.owner,
            status='published',
            is_visible=False,
            price='10.00',
            category='BOOKS',
        )

        response = self.client.get('/sitemap.xml')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/xml')

        content = response.content.decode('utf-8')

        self.assertIn('https://quaduni.com/', content)
        self.assertIn('https://quaduni.com/books', content)
        self.assertIn('https://quaduni.com/community', content)
        self.assertIn('https://quaduni.com/reviews', content)
        self.assertIn(
            f'https://quaduni.com/book/{public_book.public_path_segment}',
            content,
        )

        self.assertNotIn('/reader/', content)
        self.assertNotIn('/wallet/', content)
        self.assertNotIn('/upload/', content)
        self.assertNotIn('/draft/', content)
        self.assertNotIn('/my-books/', content)
        self.assertNotIn('/profile/', content)
        self.assertNotIn('/library/', content)
        self.assertNotIn('Draft Book', content)
        self.assertNotIn('Hidden Book', content)

    def test_book_slug_preserves_georgian_text_for_public_urls(self):
        book = Book.objects.create(
            title='ვეფხისტყაოსანი',
            author='შოთა რუსთაველი',
            owner=self.owner,
            status='published',
            is_visible=True,
            price='10.00',
            category='BOOKS',
        )

        self.assertEqual(book.slug, 'შოთა-რუსთაველი-ვეფხისტყაოსანი')
        self.assertEqual(book.public_path_segment, f'{book.slug}--{book.id}')
