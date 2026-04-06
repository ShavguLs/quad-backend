import pytest
from rest_framework import status
from rest_framework.test import APITestCase

from apps.ads.models import Ad
from apps.users.models import User


@pytest.mark.unit
class AdApiTests(APITestCase):
    def setUp(self):
        self.publisher = User.objects.create_user(
            email='publisher@example.com',
            password='testpass123',
            first_name='Publisher',
            last_name='One',
            handle='PublisherOne',
        )
        self.publisher_two = User.objects.create_user(
            email='publisher2@example.com',
            password='testpass123',
            first_name='Publisher',
            last_name='Two',
            handle='PublisherTwo',
        )

        self.published_ad = Ad.objects.create(
            publisher=self.publisher,
            title='First Promotion',
            slug='first-promotion',
            content='<p>Promo content</p>',
            category=Ad.CATEGORY_PROMO,
            is_published=True,
            seo_title='Promo SEO Title',
            seo_description='Promo SEO Description',
            seo_keywords='promo,book',
        )
        Ad.objects.create(
            publisher=self.publisher_two,
            title='Draft Showcase',
            slug='draft-showcase',
            content='<p>Hidden content</p>',
            category=Ad.CATEGORY_SHOWCASE,
            is_published=False,
        )

    def test_list_returns_paginated_contract(self):
        response = self.client.get('/blog/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('results', response.data)
        self.assertIn('count', response.data)
        self.assertIn('next', response.data)
        self.assertIn('previous', response.data)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['slug'], self.published_ad.slug)
        self.assertNotIn('content', response.data['results'][0])

    def test_list_filters_by_category_publisher_and_search(self):
        response = self.client.get('/blog/?category=promo&publisher=publisherone&search=First')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['slug'], self.published_ad.slug)

    def test_retrieve_returns_published_ad(self):
        response = self.client.get(f'/blog/{self.published_ad.slug}/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['slug'], self.published_ad.slug)
        self.assertEqual(response.data['content'], self.published_ad.content)

    def test_retrieve_returns_404_for_unpublished(self):
        response = self.client.get('/blog/draft-showcase/')

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_publishers_endpoint_lists_only_published_publishers(self):
        response = self.client.get('/blog/publishers/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['handle'], self.publisher.handle)

    def test_categories_endpoint_returns_category_counts(self):
        response = self.client.get('/blog/categories/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [{'category': Ad.CATEGORY_PROMO, 'count': 1}])

    def test_list_pagination_page_size(self):
        Ad.objects.create(
            publisher=self.publisher,
            title='Second Promotion',
            slug='second-promotion',
            content='<p>Promo content 2</p>',
            category=Ad.CATEGORY_PROMO,
            is_published=True,
        )

        response = self.client.get('/blog/?page=1&page_size=1')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 2)
        self.assertEqual(len(response.data['results']), 1)
        self.assertIsNotNone(response.data['next'])
