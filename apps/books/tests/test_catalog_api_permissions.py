from django.urls import reverse
from rest_framework.test import APITestCase

from apps.books.models import Book
from apps.users.models import User


class CatalogApiPermissionTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='reader@example.com',
            password='testpass123',
            first_name='Reader',
            last_name='User',
            handle='reader_user',
        )
        self.staff = User.objects.create_user(
            email='staff@example.com',
            password='testpass123',
            first_name='Staff',
            last_name='User',
            handle='staff_user',
            is_staff=True,
        )
        self.book = Book.objects.create(
            title='Catalog Book',
            author='Author',
            owner=self.staff,
            status='published',
            price='10.00',
            category='BOOKS',
        )

    def test_non_staff_cannot_create_update_or_delete_books(self):
        self.client.force_authenticate(self.user)

        create_response = self.client.post(reverse('book-list'), {
            'title': 'User Book',
            'author': 'User',
            'price': '1.00',
            'status': 'published',
        })
        patch_response = self.client.patch(reverse('book-detail', args=[self.book.pk]), {
            'title': 'Changed',
        })
        delete_response = self.client.delete(reverse('book-detail', args=[self.book.pk]))

        self.assertEqual(create_response.status_code, 403)
        self.assertEqual(patch_response.status_code, 403)
        self.assertEqual(delete_response.status_code, 403)

    def test_removed_author_and_reader_endpoints_are_not_available(self):
        self.client.force_authenticate(self.user)

        removed_paths = [
            f'/books/{self.book.pk}/upload/',
            f'/books/{self.book.pk}/retry-extraction/',
            f'/books/{self.book.pk}/publish/',
            f'/books/{self.book.pk}/read/access/',
            f'/books/{self.book.pk}/saved-pages/',
            f'/books/{self.book.pk}/reading-position/',
            '/me/books/',
        ]

        for path in removed_paths:
            response = self.client.post(path)
            self.assertIn(response.status_code, {404, 405})

    def test_public_catalog_reads_still_work(self):
        list_response = self.client.get(reverse('book-list'))
        detail_response = self.client.get(reverse('book-detail', args=[self.book.pk]))

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(detail_response.status_code, 200)
