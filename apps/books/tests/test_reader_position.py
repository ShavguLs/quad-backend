import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.books.models import Book, ReadingPosition
from apps.orders.models import Order
from apps.users.models import User

pytestmark = pytest.mark.django_db


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def owner(db):
    return User.objects.create_user(
        email="owner@example.com",
        password="password",
        first_name="Owner",
        last_name="User",
        handle="owner_user",
    )


@pytest.fixture
def reader(db):
    return User.objects.create_user(
        email="reader@example.com",
        password="password",
        first_name="Reader",
        last_name="User",
        handle="reader_user",
    )


@pytest.fixture
def stranger(db):
    return User.objects.create_user(
        email="stranger@example.com",
        password="password",
        first_name="Stranger",
        last_name="User",
        handle="stranger_user",
    )


@pytest.fixture
def book(owner):
    return Book.objects.create(
        owner=owner,
        title="Test Book",
        author="Author",
        status="published",
        access_type=Book.ACCESS_TYPE_EDUCATIONAL,
        total_pages=100,
    )


@pytest.fixture
def reader_with_access(reader, book):
    Order.objects.create(
        buyer=reader, book=book, status=Order.STATUS_COMPLETED, amount=0
    )
    return reader


def _position_url(book_id):
    return reverse("book-reading-position", args=[book_id])


def test_get_position_returns_null_when_no_position(api_client, reader_with_access, book):
    api_client.force_authenticate(user=reader_with_access)
    response = api_client.get(_position_url(book.id))
    assert response.status_code == status.HTTP_200_OK
    assert response.data["page_number"] is None
    assert response.data["book_id"] == book.id


def test_patch_creates_position(api_client, reader_with_access, book):
    api_client.force_authenticate(user=reader_with_access)
    response = api_client.patch(
        _position_url(book.id), {"page_number": 55}, format="json"
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.data["page_number"] == 55
    assert response.data["bookId"] == book.id
    assert response.data["pageNumber"] == 55


def test_get_reads_saved_position(api_client, reader_with_access, book):
    api_client.force_authenticate(user=reader_with_access)
    api_client.patch(_position_url(book.id), {"page_number": 55}, format="json")

    response = api_client.get(_position_url(book.id))
    assert response.status_code == status.HTTP_200_OK
    assert response.data["page_number"] == 55


def test_patch_updates_existing_position(api_client, reader_with_access, book):
    api_client.force_authenticate(user=reader_with_access)
    api_client.patch(_position_url(book.id), {"page_number": 10}, format="json")
    response = api_client.patch(
        _position_url(book.id), {"page_number": 55}, format="json"
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.data["page_number"] == 55

    positions = ReadingPosition.objects.filter(book=book, user=reader_with_access)
    assert positions.count() == 1


def test_unauthenticated_get_rejected(api_client, book):
    response = api_client.get(_position_url(book.id))
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_unauthenticated_patch_rejected(api_client, book):
    response = api_client.patch(
        _position_url(book.id), {"page_number": 1}, format="json"
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_user_without_access_get_403(api_client, stranger, book):
    api_client.force_authenticate(user=stranger)
    response = api_client.get(_position_url(book.id))
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_user_without_access_patch_403(api_client, stranger, book):
    api_client.force_authenticate(user=stranger)
    response = api_client.patch(
        _position_url(book.id), {"page_number": 1}, format="json"
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_patch_invalid_page_zero(api_client, reader_with_access, book):
    api_client.force_authenticate(user=reader_with_access)
    response = api_client.patch(
        _position_url(book.id), {"page_number": 0}, format="json"
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_patch_page_exceeds_total_pages(api_client, reader_with_access, book):
    api_client.force_authenticate(user=reader_with_access)
    response = api_client.patch(
        _position_url(book.id), {"page_number": 200}, format="json"
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_patch_page_within_total_pages(api_client, reader_with_access, book):
    api_client.force_authenticate(user=reader_with_access)
    response = api_client.patch(
        _position_url(book.id), {"page_number": 100}, format="json"
    )
    assert response.status_code == status.HTTP_200_OK


def test_patch_page_when_total_pages_zero(api_client, owner):
    book = Book.objects.create(
        owner=owner,
        title="No Pages Book",
        author="Author",
        status="published",
        total_pages=0,
    )
    api_client.force_authenticate(user=owner)
    response = api_client.patch(
        _position_url(book.id), {"page_number": 5}, format="json"
    )
    assert response.status_code == status.HTTP_200_OK


def test_nonexistent_book_returns_404(api_client, reader):
    api_client.force_authenticate(user=reader)
    response = api_client.get(_position_url(9999))
    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_owner_can_save_position(api_client, owner, book):
    api_client.force_authenticate(user=owner)
    response = api_client.patch(
        _position_url(book.id), {"page_number": 42}, format="json"
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.data["page_number"] == 42