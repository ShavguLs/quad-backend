import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from rest_framework import status
from rest_framework.test import APIClient

from apps.books.models import Book
from apps.orders.models import Order
from apps.users.models import User

pytestmark = pytest.mark.django_db

@pytest.fixture
def api_client():
    return APIClient()

@pytest.fixture
def user1(db):
    return User.objects.create_user(email="user1@example.com", password="password", first_name="u1", last_name="last1", handle="u1")

@pytest.fixture
def user2(db):
    return User.objects.create_user(email="user2@example.com", password="password", first_name="u2", last_name="last2", handle="u2")

@pytest.fixture
def pdf_content():
    return b"%PDF-1.4\n%EOF"

@pytest.fixture
def edu_book(db, user1, pdf_content):
    pdf = SimpleUploadedFile("test_edu.pdf", pdf_content, content_type="application/pdf")
    return Book.objects.create(
        owner=user1,
        title="Educational Book",
        author="Author 1",
        status="published",
        access_type=Book.ACCESS_TYPE_EDUCATIONAL,
        pdf_file=pdf,
    )

@pytest.fixture
def sci_book(db, user1, pdf_content):
    pdf = SimpleUploadedFile("test_sci.pdf", pdf_content, content_type="application/pdf")
    return Book.objects.create(
        owner=user1,
        title="Scientific Book",
        author="Author 1",
        status="published",
        access_type=Book.ACCESS_TYPE_SCIENTIFIC,
        pdf_file=pdf,
    )

def test_unauthenticated_cannot_read(api_client, edu_book):
    url = reverse("book-read", args=[edu_book.id])
    response = api_client.get(url)
    assert response.status_code == status.HTTP_403_FORBIDDEN

def test_unauthenticated_cannot_download(api_client, sci_book):
    url = reverse("book-download", args=[sci_book.id])
    response = api_client.get(url)
    assert response.status_code == status.HTTP_403_FORBIDDEN

def test_authenticated_non_buyer_cannot_read(api_client, user2, edu_book):
    api_client.force_authenticate(user=user2)
    url = reverse("book-read", args=[edu_book.id])
    response = api_client.get(url)
    assert response.status_code == status.HTTP_403_FORBIDDEN

def test_authenticated_non_buyer_cannot_download(api_client, user2, sci_book):
    api_client.force_authenticate(user=user2)
    url = reverse("book-download", args=[sci_book.id])
    response = api_client.get(url)
    assert response.status_code == status.HTTP_403_FORBIDDEN

def test_educational_buyer_can_read(api_client, user2, edu_book):
    Order.objects.create(buyer=user2, book=edu_book, status=Order.STATUS_COMPLETED, amount=0)
    api_client.force_authenticate(user=user2)
    url = reverse("book-read", args=[edu_book.id])
    response = api_client.get(url)
    assert response.status_code == status.HTTP_200_OK
    assert response.get("Content-Type") == "application/pdf"
    assert "inline" in response.get("Content-Disposition")

def test_educational_buyer_cannot_download(api_client, user2, edu_book):
    Order.objects.create(buyer=user2, book=edu_book, status=Order.STATUS_COMPLETED, amount=0)
    api_client.force_authenticate(user=user2)
    url = reverse("book-download", args=[edu_book.id])
    response = api_client.get(url)
    assert response.status_code == status.HTTP_403_FORBIDDEN

def test_scientific_buyer_can_read(api_client, user2, sci_book):
    Order.objects.create(buyer=user2, book=sci_book, status=Order.STATUS_COMPLETED, amount=0)
    api_client.force_authenticate(user=user2)
    url = reverse("book-read", args=[sci_book.id])
    response = api_client.get(url)
    assert response.status_code == status.HTTP_200_OK

def test_scientific_buyer_can_download(api_client, user2, sci_book):
    Order.objects.create(buyer=user2, book=sci_book, status=Order.STATUS_COMPLETED, amount=0)
    api_client.force_authenticate(user=user2)
    url = reverse("book-download", args=[sci_book.id])
    response = api_client.get(url)
    assert response.status_code == status.HTTP_200_OK
    assert response.get("Content-Type") == "application/pdf"
    assert "attachment" in response.get("Content-Disposition")

def test_educational_buyer_can_range_read(api_client, user2, edu_book):
    Order.objects.create(buyer=user2, book=edu_book, status=Order.STATUS_COMPLETED, amount=0)
    api_client.force_authenticate(user=user2)
    url = reverse("book-read", args=[edu_book.id])
    
    # Test valid range
    response = api_client.get(url, HTTP_RANGE="bytes=2-6")
    assert response.status_code == status.HTTP_206_PARTIAL_CONTENT
    assert response.get("Content-Range") == "bytes 2-6/13"
    assert response.get("Content-Length") == "5"
    assert response.get("Accept-Ranges") == "bytes"
    assert b"".join(response.streaming_content) == b"DF-1."

def test_unauthorized_user_cannot_range_read(api_client, user2, edu_book):
    api_client.force_authenticate(user=user2)
    url = reverse("book-read", args=[edu_book.id])
    response = api_client.get(url, HTTP_RANGE="bytes=2-6")
    assert response.status_code == status.HTTP_403_FORBIDDEN

def test_unauthenticated_cannot_range_read(api_client, edu_book):
    url = reverse("book-read", args=[edu_book.id])
    response = api_client.get(url, HTTP_RANGE="bytes=2-6")
    assert response.status_code == status.HTTP_403_FORBIDDEN

def test_invalid_range_returns_416(api_client, user2, edu_book):
    Order.objects.create(buyer=user2, book=edu_book, status=Order.STATUS_COMPLETED, amount=0)
    api_client.force_authenticate(user=user2)
    url = reverse("book-read", args=[edu_book.id])
    
    response = api_client.get(url, HTTP_RANGE="bytes=20-30")
    assert response.status_code == status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE
    assert response.get("Content-Range") == "bytes */13"

def test_open_ended_range(api_client, user2, edu_book):
    Order.objects.create(buyer=user2, book=edu_book, status=Order.STATUS_COMPLETED, amount=0)
    api_client.force_authenticate(user=user2)
    url = reverse("book-read", args=[edu_book.id])
    
    response = api_client.get(url, HTTP_RANGE="bytes=10-")
    assert response.status_code == status.HTTP_206_PARTIAL_CONTENT
    assert response.get("Content-Range") == "bytes 10-12/13"
    assert response.get("Content-Length") == "3"
    assert b"".join(response.streaming_content) == b"EOF"

def test_expired_educational_buyer_cannot_read(api_client, user2, edu_book):
    expired_time = timezone.now() - timedelta(days=1)
    Order.objects.create(buyer=user2, book=edu_book, status=Order.STATUS_COMPLETED, expires_at=expired_time, amount=0)
    api_client.force_authenticate(user=user2)
    url = reverse("book-read", args=[edu_book.id])
    response = api_client.get(url)
    assert response.status_code == status.HTTP_403_FORBIDDEN

def test_expired_educational_buyer_cannot_download(api_client, user2, edu_book):
    expired_time = timezone.now() - timedelta(days=1)
    Order.objects.create(buyer=user2, book=edu_book, status=Order.STATUS_COMPLETED, expires_at=expired_time, amount=0)
    api_client.force_authenticate(user=user2)
    url = reverse("book-download", args=[edu_book.id])
    response = api_client.get(url)
    assert response.status_code == status.HTTP_403_FORBIDDEN

def test_owner_can_read_own_book(api_client, user1, edu_book):
    api_client.force_authenticate(user=user1)
    url = reverse("book-read", args=[edu_book.id])
    response = api_client.get(url)
    assert response.status_code == status.HTTP_200_OK

def test_owner_can_download_own_scientific_book(api_client, user1, sci_book):
    api_client.force_authenticate(user=user1)
    url = reverse("book-download", args=[sci_book.id])
    response = api_client.get(url)
    assert response.status_code == status.HTTP_200_OK

def test_missing_pdf_returns_404(api_client, user1, db):
    book = Book.objects.create(
        owner=user1,
        title="No PDF Book",
        author="Author",
        status="published",
        access_type=Book.ACCESS_TYPE_EDUCATIONAL,
    )
    api_client.force_authenticate(user=user1)
    url = reverse("book-read", args=[book.id])
    response = api_client.get(url)
    assert response.status_code == status.HTTP_404_NOT_FOUND

def test_missing_pdf_file_on_storage_returns_404(api_client, user1, db):
    book = Book.objects.create(
        owner=user1,
        title="Dangling PDF Book",
        author="Author",
        status="published",
        access_type=Book.ACCESS_TYPE_EDUCATIONAL,
        pdf_file="books/pdfs/missing.pdf",
    )
    api_client.force_authenticate(user=user1)

    url = reverse("book-read", args=[book.id])
    response = api_client.get(url)

    assert response.status_code == status.HTTP_404_NOT_FOUND
