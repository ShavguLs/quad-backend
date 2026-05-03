import io

import pytest
import fitz
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.books.models import Book
from apps.users.models import User

pytestmark = pytest.mark.django_db


def _make_real_pdf(page_count=3):
    doc = fitz.open()
    for i in range(page_count):
        page = doc.new_page(width=612, height=792)
        page.insert_text(
            fitz.Point(72, 72),
            f"Page {i + 1}",
            fontsize=24,
            fontname="helv",
        )
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    buf.seek(0)
    return buf.read()


@pytest.fixture
def private_media_tmp(tmp_path):
    tmp_media = tmp_path / "private_media"
    tmp_media.mkdir()

    from django.core.files.storage import FileSystemStorage

    pdf_field = Book._meta.get_field("pdf_file")
    original_storage = pdf_field.storage
    pdf_field.storage = FileSystemStorage(location=str(tmp_media), base_url=None)

    yield tmp_media

    pdf_field.storage = original_storage


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def user1(db):
    return User.objects.create_user(
        email="user1@example.com", password="password",
        first_name="u1", last_name="last1", handle="u1",
    )


@pytest.fixture
def user2(db):
    return User.objects.create_user(
        email="user2@example.com", password="password",
        first_name="u2", last_name="last2", handle="u2",
    )


@pytest.fixture
def staff_user(db):
    return User.objects.create_user(
        email="staff@example.com", password="password",
        first_name="staff", last_name="user", handle="staff",
        is_staff=True,
    )


@pytest.fixture
def real_pdf():
    return _make_real_pdf(page_count=12)


@pytest.fixture
def published_book(db, user1, real_pdf, private_media_tmp):
    pdf = SimpleUploadedFile("preview_test.pdf", real_pdf, content_type="application/pdf")
    return Book.objects.create(
        owner=user1,
        title="Preview Test Book",
        author="Author",
        slug="preview-test-book",
        status="published",
        is_visible=True,
        access_type=Book.ACCESS_TYPE_EDUCATIONAL,
        pdf_file=pdf,
    )


@pytest.fixture
def draft_book(db, user1, real_pdf, private_media_tmp):
    pdf = SimpleUploadedFile("draft_test.pdf", real_pdf, content_type="application/pdf")
    return Book.objects.create(
        owner=user1,
        title="Draft Book",
        author="Author",
        slug="draft-book",
        status="draft",
        is_visible=True,
        access_type=Book.ACCESS_TYPE_EDUCATIONAL,
        pdf_file=pdf,
    )


@pytest.fixture
def invisible_book(db, user1, real_pdf, private_media_tmp):
    pdf = SimpleUploadedFile("invisible_test.pdf", real_pdf, content_type="application/pdf")
    return Book.objects.create(
        owner=user1,
        title="Invisible Book",
        author="Author",
        slug="invisible-book",
        status="published",
        is_visible=False,
        access_type=Book.ACCESS_TYPE_EDUCATIONAL,
        pdf_file=pdf,
    )


def test_unauthenticated_can_preview_published_visible_book(api_client, published_book):
    url = reverse("book-preview", args=[published_book.id])
    response = api_client.get(url)
    assert response.status_code == status.HTTP_200_OK
    assert response.get("Content-Type") == "application/pdf"
    assert "inline" in response.get("Content-Disposition")
    assert "preview" in response.get("Content-Disposition")
    assert response.get("Cache-Control") == "no-store"
    assert response.get("X-Content-Type-Options") == "nosniff"
    assert response.has_header("Accept-Ranges") is False


def test_authenticated_non_buyer_can_preview(api_client, user2, published_book):
    api_client.force_authenticate(user=user2)
    url = reverse("book-preview", args=[published_book.id])
    response = api_client.get(url)
    assert response.status_code == status.HTTP_200_OK
    assert response.get("Content-Type") == "application/pdf"


def test_preview_returns_generated_pdf_not_original(api_client, published_book, real_pdf):
    url = reverse("book-preview", args=[published_book.id])
    response = api_client.get(url)
    assert response.status_code == status.HTTP_200_OK

    preview_bytes = response.content

    assert len(preview_bytes) != len(real_pdf)

    doc = fitz.open(stream=preview_bytes, filetype="pdf")
    assert doc.page_count <= 10
    assert doc.page_count >= 1
    doc.close()


def test_preview_limits_pages_to_10(api_client, published_book):
    url = reverse("book-preview", args=[published_book.id])
    response = api_client.get(url)
    assert response.status_code == status.HTTP_200_OK

    preview_bytes = response.content

    doc = fitz.open(stream=preview_bytes, filetype="pdf")
    assert doc.page_count == 10
    doc.close()


def test_preview_missing_pdf_returns_404(api_client, user1, db):
    book = Book.objects.create(
        owner=user1,
        title="No PDF Book",
        author="Author",
        status="published",
        is_visible=True,
        access_type=Book.ACCESS_TYPE_EDUCATIONAL,
    )
    url = reverse("book-preview", args=[book.id])
    response = api_client.get(url)
    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_preview_draft_book_not_in_public_queryset(api_client, draft_book):
    url = reverse("book-preview", args=[draft_book.id])
    response = api_client.get(url)
    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_preview_invisible_book_not_in_public_queryset(api_client, invisible_book):
    url = reverse("book-preview", args=[invisible_book.id])
    response = api_client.get(url)
    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_staff_cannot_preview_draft_book(api_client, staff_user, draft_book):
    api_client.force_authenticate(user=staff_user)
    url = reverse("book-preview", args=[draft_book.id])
    response = api_client.get(url)
    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_staff_cannot_preview_invisible_book(api_client, staff_user, invisible_book):
    api_client.force_authenticate(user=staff_user)
    url = reverse("book-preview", args=[invisible_book.id])
    response = api_client.get(url)
    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_preview_contains_watermark(api_client, published_book):
    url = reverse("book-preview", args=[published_book.id])
    response = api_client.get(url)
    assert response.status_code == status.HTTP_200_OK

    preview_bytes = response.content

    doc = fitz.open(stream=preview_bytes, filetype="pdf")
    page = doc[0]
    text = page.get_text()
    assert "QUADUNI PREVIEW" in text
    doc.close()


def test_read_and_download_still_work(api_client, user1, published_book):
    api_client.force_authenticate(user=user1)

    read_url = reverse("book-read", args=[published_book.id])
    read_resp = api_client.get(read_url)
    assert read_resp.status_code == status.HTTP_200_OK

    download_url = reverse("book-download", args=[published_book.id])
    download_resp = api_client.get(download_url)
    assert download_resp.status_code == status.HTTP_403_FORBIDDEN