from unittest.mock import patch
from datetime import timedelta
from urllib.parse import urlsplit

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.books.models import Book, BookContent, BookFile, ReadingPosition
from apps.orders.models import Order
from apps.users.models import User


def _minimal_pdf_file(name: str = "sample.pdf") -> SimpleUploadedFile:
    # Minimal PDF header/body that passes file-type checks.
    content = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 144] >>\nendobj\n"
        b"xref\n0 4\n0000000000 65535 f\n0000000010 00000 n\n0000000060 00000 n\n0000000120 00000 n\n"
        b"trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n180\n%%EOF"
    )
    return SimpleUploadedFile(name, content, content_type="application/pdf")


def _valid_pdf_bytes(page_count: int = 12) -> bytes:
    import fitz

    doc = fitz.open()
    for page_number in range(1, page_count + 1):
        page = doc.new_page(width=300, height=420)
        page.insert_text((72, 72), f"Quaduni test page {page_number}", fontsize=14)
    payload = doc.tobytes(garbage=4, deflate=True)
    doc.close()
    return payload


def _streaming_content(response) -> bytes:
    return b"".join(response.streaming_content)


class ReaderAccessApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(
            email="owner@example.com",
            password="testpass123",
            first_name="Owner",
            last_name="User",
            handle="owner_user",
            can_upload_books=True,
        )
        self.buyer = User.objects.create_user(
            email="buyer@example.com",
            password="testpass123",
            first_name="Buyer",
            last_name="User",
            handle="buyer_user",
        )

        self.book = Book.objects.create(
            title="Reader Test",
            author="Owner User",
            owner=self.owner,
            status="published",
            is_visible=True,
            extraction_status="completed",
            total_pages=11,
            price="10.00",
            category="BOOKS",
        )
        self.source_pdf_bytes = _valid_pdf_bytes(page_count=12)
        self.book_file = BookFile.objects.create(
            book=self.book,
            file=SimpleUploadedFile(
                "reader-test.pdf",
                self.source_pdf_bytes,
                content_type="application/pdf",
            ),
            original_filename="reader-test.pdf",
            file_size=len(self.source_pdf_bytes),
            mime_type="application/pdf",
        )

        for page_number in range(1, 12):
            BookContent.objects.create(
                book=self.book,
                page_number=page_number,
                version=1,
                blocks=[
                    {
                        "id": f"blk_{page_number}_0",
                        "type": "paragraph",
                        "text": f"Page {page_number} text",
                        "metadata": {
                            "render_mode": "html",
                            "render_html": f"<p>Page {page_number} text</p>",
                            "source": "extraction",
                            "confidence": 1.0,
                        },
                    }
                ],
            )

    def _create_draft_book(self, title: str = "Draft Upload Test") -> Book:
        return Book.objects.create(
            title=title,
            author="Owner User",
            owner=self.owner,
            status="draft",
            is_visible=False,
            extraction_status="pending",
            total_pages=0,
            price="10.00",
            category="BOOKS",
        )

    def test_new_reader_preview_access_returns_preview_document_only(self):
        response = self.client.get(f"/books/{self.book.id}/read/access/?preview=1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["mode"], "preview")
        self.assertTrue(response.data["can_read"])
        self.assertFalse(response.data["can_download"])
        self.assertIn("/read/document/", response.data["document_url"])
        self.assertIn("preview=1", response.data["document_url"])

        document_response = self.client.get(f"/books/{self.book.id}/read/document/?preview=1")
        self.assertEqual(document_response.status_code, 200)
        preview_bytes = _streaming_content(document_response)
        self.assertTrue(preview_bytes.startswith(b"%PDF"))
        self.assertNotEqual(preview_bytes, self.source_pdf_bytes)

        self.book_file.refresh_from_db()
        self.assertTrue(self.book_file.preview_file)

    def test_new_reader_guest_and_unpurchased_full_access_are_blocked(self):
        response = self.client.get(f"/books/{self.book.id}/read/access/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "purchase_required")
        self.assertFalse(response.data["can_read"])
        self.assertIsNone(response.data["document_url"])

        document_response = self.client.get(f"/books/{self.book.id}/read/document/")
        self.assertEqual(document_response.status_code, 403)
        self.assertEqual(document_response.data["code"], "purchase_required")

        non_buyer = User.objects.create_user(
            email="new_reader_nonbuyer@example.com",
            password="testpass123",
            first_name="Non",
            last_name="Buyer",
            handle="new_reader_nonbuyer",
        )
        self.client.force_authenticate(non_buyer)
        response = self.client.get(f"/books/{self.book.id}/read/access/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "purchase_required")

    def test_new_reader_expired_educational_buyer_is_blocked(self):
        Order.objects.create(
            buyer=self.buyer,
            book=self.book,
            amount=self.book.price,
            status=Order.STATUS_COMPLETED,
            expires_at=timezone.now() - timedelta(days=1),
        )
        self.client.force_authenticate(self.buyer)

        response = self.client.get(f"/books/{self.book.id}/read/access/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "expired")
        self.assertFalse(response.data["can_read"])

        document_response = self.client.get(f"/books/{self.book.id}/read/document/")
        self.assertEqual(document_response.status_code, 403)
        self.assertEqual(document_response.data["code"], "access_expired")

    def test_new_reader_active_educational_buyer_can_read_but_not_download(self):
        Order.objects.create(
            buyer=self.buyer,
            book=self.book,
            amount=self.book.price,
            status=Order.STATUS_COMPLETED,
            expires_at=timezone.now() + timedelta(days=180),
        )
        self.client.force_authenticate(self.buyer)

        response = self.client.get(f"/books/{self.book.id}/read/access/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "ready")
        self.assertTrue(response.data["can_read"])
        self.assertFalse(response.data["can_download"])
        self.assertIsNotNone(response.data["document_url"])
        self.assertIn("token=", response.data["document_url"])
        self.assertIsNone(response.data["download_url"])

        document_url = urlsplit(response.data["document_url"])
        self.client.force_authenticate(None)
        document_response = self.client.get(f"{document_url.path}?{document_url.query}")
        self.assertEqual(document_response.status_code, 200)
        self.assertEqual(_streaming_content(document_response), self.source_pdf_bytes)

        self.client.force_authenticate(self.buyer)
        download_response = self.client.get(f"/books/{self.book.id}/read/download/")
        self.assertEqual(download_response.status_code, 403)
        self.assertEqual(download_response.data["code"], "download_not_allowed")

    def test_owner_draft_document_token_works_without_session_cookies(self):
        draft_book = self._create_draft_book()
        BookFile.objects.create(
            book=draft_book,
            file=SimpleUploadedFile(
                "owner-draft.pdf",
                self.source_pdf_bytes,
                content_type="application/pdf",
            ),
            original_filename="owner-draft.pdf",
            file_size=len(self.source_pdf_bytes),
            mime_type="application/pdf",
        )
        self.client.force_authenticate(self.owner)

        response = self.client.get(f"/books/{draft_book.id}/read/access/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "ready")
        document_url = urlsplit(response.data["document_url"])

        self.client.force_authenticate(None)
        direct_response = self.client.get(f"/books/{draft_book.id}/read/document/")
        self.assertEqual(direct_response.status_code, 404)

        token_response = self.client.get(f"{document_url.path}?{document_url.query}")
        self.assertEqual(token_response.status_code, 200)
        self.assertEqual(_streaming_content(token_response), self.source_pdf_bytes)

    def test_reader_document_supports_byte_range_requests(self):
        Order.objects.create(
            buyer=self.buyer,
            book=self.book,
            amount=self.book.price,
            status=Order.STATUS_COMPLETED,
            expires_at=timezone.now() + timedelta(days=180),
        )
        self.client.force_authenticate(self.buyer)

        response = self.client.get(f"/books/{self.book.id}/read/access/")
        self.assertEqual(response.status_code, 200)
        document_url = urlsplit(response.data["document_url"])

        self.client.force_authenticate(None)
        range_response = self.client.get(
            f"{document_url.path}?{document_url.query}",
            HTTP_RANGE="bytes=0-7",
        )
        self.assertEqual(range_response.status_code, 206)
        self.assertEqual(range_response["Accept-Ranges"], "bytes")
        self.assertEqual(range_response["Content-Length"], "8")
        self.assertEqual(range_response["Content-Range"], f"bytes 0-7/{len(self.source_pdf_bytes)}")
        self.assertEqual(_streaming_content(range_response), self.source_pdf_bytes[:8])

    def test_new_reader_scientific_buyer_download_is_watermarked(self):
        self.book.access_type = Book.ACCESS_TYPE_SCIENTIFIC
        self.book.save(update_fields=["access_type"])
        Order.objects.create(
            buyer=self.buyer,
            book=self.book,
            amount=self.book.price,
            status=Order.STATUS_COMPLETED,
            expires_at=None,
        )
        self.client.force_authenticate(self.buyer)

        response = self.client.get(f"/books/{self.book.id}/read/access/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "ready")
        self.assertTrue(response.data["can_read"])
        self.assertTrue(response.data["can_download"])
        self.assertIsNotNone(response.data["download_url"])

        download_response = self.client.get(f"/books/{self.book.id}/read/download/")
        self.assertEqual(download_response.status_code, 200)
        watermarked_bytes = _streaming_content(download_response)
        self.assertTrue(watermarked_bytes.startswith(b"%PDF"))
        self.assertNotEqual(watermarked_bytes, self.source_pdf_bytes)
        import fitz

        doc = fitz.open(stream=watermarked_bytes, filetype="pdf")
        extracted_text = "\n".join(page.get_text() for page in doc)
        doc.close()
        self.assertIn("Quaduni", extracted_text)

    def test_new_reader_owner_downloads_original_for_both_book_types(self):
        for access_type in (Book.ACCESS_TYPE_EDUCATIONAL, Book.ACCESS_TYPE_SCIENTIFIC):
            self.book.access_type = access_type
            self.book.save(update_fields=["access_type"])
            self.client.force_authenticate(self.owner)

            response = self.client.get(f"/books/{self.book.id}/read/access/")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data["status"], "ready")
            self.assertTrue(response.data["can_download"])

            download_response = self.client.get(f"/books/{self.book.id}/read/download/")
            self.assertEqual(download_response.status_code, 200)
            self.assertEqual(_streaming_content(download_response), self.source_pdf_bytes)

    def test_create_book_stays_draft_until_explicit_publish(self):
        self.client.force_authenticate(self.owner)

        response = self.client.post(
            "/books/",
            {
                "title": "New Draft",
                "author": "Owner User",
                "price": "10.00",
                "category": "BOOKS",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], "draft")

        created_book = Book.objects.get(id=response.data["id"])
        self.assertEqual(created_book.status, "draft")

    def test_old_reader_manifest_and_page_endpoints_are_removed(self):
        self.client.force_authenticate(self.owner)

        manifest_response = self.client.get(f"/books/{self.book.id}/read/manifest/")
        page_response = self.client.get(f"/books/{self.book.id}/read/pages/1/")

        self.assertEqual(manifest_response.status_code, 404)
        self.assertEqual(page_response.status_code, 404)

    @patch("apps.books.tasks.process_book_upload_task.delay")
    def test_upload_response_does_not_expose_private_download_url(self, mocked_delay):
        draft_book = self._create_draft_book("Draft Upload Contract")
        self.client.force_authenticate(self.owner)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/books/{draft_book.id}/upload/",
                {"file": _minimal_pdf_file("contract.pdf")},
                format="multipart",
            )

        self.assertEqual(response.status_code, 202)
        self.assertIn("file", response.data)
        self.assertIn("download_url", response.data["file"])
        self.assertIsNone(response.data["file"]["download_url"])
        mocked_delay.assert_called_once_with(draft_book.id)

    def test_reading_position_returns_null_payload_when_missing(self):
        self.client.force_authenticate(self.owner)

        response = self.client.get(f"/books/{self.book.id}/reading-position/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"page_number": None})

    def test_reading_position_returns_saved_position_when_present(self):
        ReadingPosition.objects.create(
            book=self.book,
            user=self.owner,
            page_number=3,
        )
        self.client.force_authenticate(self.owner)

        response = self.client.get(f"/books/{self.book.id}/reading-position/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["page_number"], 3)
        self.assertIn("updated_at", response.data)

    def test_reading_position_returns_404_for_missing_book(self):
        self.client.force_authenticate(self.owner)

        response = self.client.get("/books/999999/reading-position/")

        self.assertEqual(response.status_code, 404)

    @patch("apps.books.tasks.process_book_upload_task.delay")
    def test_upload_is_async_and_marks_processing(self, mocked_delay):
        draft_book = self._create_draft_book()
        self.client.force_authenticate(self.owner)

        # captureOnCommitCallbacks(execute=True) forces on_commit hooks to run
        # within the test transaction so the mocked .delay() is actually called.
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/books/{draft_book.id}/upload/",
                {"file": _minimal_pdf_file()},
                format="multipart",
            )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data["extraction_status"], "processing")
        mocked_delay.assert_called_once_with(draft_book.id)

        draft_book.refresh_from_db()
        self.assertEqual(draft_book.extraction_status, "processing")
        self.assertFalse(draft_book.is_visible)
        self.assertEqual(
            draft_book.reader_render_preference,
            Book.RENDER_PREFERENCE_TEXT,
        )

    @patch("apps.books.tasks.process_book_upload_task.delay")
    def test_upload_accepts_and_persists_render_preference(self, mocked_delay):
        draft_book = self._create_draft_book()
        self.client.force_authenticate(self.owner)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/books/{draft_book.id}/upload/",
                {
                    "file": _minimal_pdf_file(),
                    "render_preference": Book.RENDER_PREFERENCE_EXACT_VISUAL,
                },
                format="multipart",
            )

        self.assertEqual(response.status_code, 202)
        mocked_delay.assert_called_once_with(draft_book.id)

        draft_book.refresh_from_db()
        self.assertEqual(
            draft_book.reader_render_preference,
            Book.RENDER_PREFERENCE_EXACT_VISUAL,
        )

    @patch("apps.books.tasks.process_book_upload_task.delay")
    def test_upload_rejects_invalid_render_preference(self, mocked_delay):
        draft_book = self._create_draft_book()
        self.client.force_authenticate(self.owner)

        response = self.client.post(
            f"/books/{draft_book.id}/upload/",
            {
                "file": _minimal_pdf_file(),
                "render_preference": "bitmap_mode",
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid render_preference", response.data["detail"])
        mocked_delay.assert_not_called()

    @patch("apps.books.tasks.process_book_upload_task.delay")
    def test_upload_requires_upload_privilege(self, mocked_delay):
        draft_book = self._create_draft_book()
        self.owner.can_upload_books = False
        self.owner.save(update_fields=["can_upload_books"])
        self.client.force_authenticate(self.owner)

        response = self.client.post(
            f"/books/{draft_book.id}/upload/",
            {"file": _minimal_pdf_file()},
            format="multipart",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["detail"], "You do not have upload privilege.")
        mocked_delay.assert_not_called()

    @patch("apps.books.tasks.process_book_upload_task.delay")
    def test_upload_requires_draft_book(self, mocked_delay):
        self.client.force_authenticate(self.owner)

        response = self.client.post(
            f"/books/{self.book.id}/upload/",
            {"file": _minimal_pdf_file()},
            format="multipart",
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn("draft", response.data["detail"].lower())
        mocked_delay.assert_not_called()

    @patch("apps.books.tasks.process_book_upload_task.delay")
    def test_upload_normalizes_mime_type_from_validated_file(self, mocked_delay):
        draft_book = self._create_draft_book("Draft MIME Test")
        self.client.force_authenticate(self.owner)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/books/{draft_book.id}/upload/",
                {"file": _minimal_pdf_file(name="mime-test.pdf")},
                format="multipart",
            )

        self.assertEqual(response.status_code, 202)
        stored_file = (
            BookFile.objects.filter(book=draft_book).order_by("-uploaded_at").first()
        )
        self.assertIsNotNone(stored_file)
        self.assertEqual(stored_file.mime_type, "application/pdf")
        mocked_delay.assert_called_once_with(draft_book.id)

    def test_saved_pages_requires_book_access(self):
        non_buyer = User.objects.create_user(
            email="nonbuyer2@example.com",
            password="testpass123",
            first_name="Non",
            last_name="Buyer2",
            handle="non_buyer2",
        )
        self.client.force_authenticate(non_buyer)

        response = self.client.get(f"/books/{self.book.id}/saved-pages/")
        self.assertEqual(response.status_code, 403)

        response = self.client.post(
            f"/books/{self.book.id}/saved-pages/",
            {"page_number": 1},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_reading_position_requires_book_access(self):
        non_buyer = User.objects.create_user(
            email="nonbuyer3@example.com",
            password="testpass123",
            first_name="Non",
            last_name="Buyer3",
            handle="non_buyer3",
        )
        self.client.force_authenticate(non_buyer)

        response = self.client.get(f"/books/{self.book.id}/reading-position/")
        self.assertEqual(response.status_code, 403)

        response = self.client.put(
            f"/books/{self.book.id}/reading-position/",
            {"page_number": 1},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_theme_update_requires_owner(self):
        self.client.force_authenticate(self.buyer)
        response = self.client.patch(
            f"/books/{self.book.id}/theme/",
            {"font_family": "serif"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("owner", response.data["detail"].lower())

        self.client.force_authenticate(self.owner)
        response = self.client.patch(
            f"/books/{self.book.id}/theme/",
            {"font_family": "sans"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)

    def test_old_reader_endpoints_are_removed_for_guests_and_buyers(self):
        Order.objects.create(
            buyer=self.buyer,
            book=self.book,
            amount=self.book.price,
            status=Order.STATUS_COMPLETED,
        )

        for user in (None, self.buyer):
            self.client.force_authenticate(user)
            manifest_response = self.client.get(f"/books/{self.book.id}/read/manifest/?preview=1")
            page_response = self.client.get(f"/books/{self.book.id}/read/pages/1/?preview=1")

            self.assertEqual(manifest_response.status_code, 404)
            self.assertEqual(page_response.status_code, 404)
