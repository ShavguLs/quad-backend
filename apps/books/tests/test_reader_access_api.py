from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
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

    def test_manifest_access_modes_owner_buyer_unauthenticated(self):
        # Owner => full
        self.client.force_authenticate(self.owner)
        response = self.client.get(f"/books/{self.book.id}/read/manifest/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["access_mode"], "full")

        # Buyer => full
        Order.objects.create(
            buyer=self.buyer,
            book=self.book,
            amount=self.book.price,
            status=Order.STATUS_COMPLETED,
        )
        self.client.force_authenticate(self.buyer)
        response = self.client.get(f"/books/{self.book.id}/read/manifest/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["access_mode"], "full")

        # Unauthenticated => 401 (no preview allowed)
        self.client.force_authenticate(None)
        response = self.client.get(f"/books/{self.book.id}/read/manifest/")
        self.assertEqual(response.status_code, 401)

    def test_reader_cache_is_scoped_by_access(self):
        Order.objects.create(
            buyer=self.buyer,
            book=self.book,
            amount=self.book.price,
            status=Order.STATUS_COMPLETED,
        )

        # Warm full-access cache as buyer.
        self.client.force_authenticate(self.buyer)
        full_manifest = self.client.get(f"/books/{self.book.id}/read/manifest/")
        self.assertEqual(full_manifest.status_code, 200)
        self.assertEqual(full_manifest.data["access_mode"], "full")

        full_page = self.client.get(f"/books/{self.book.id}/read/pages/4/")
        self.assertEqual(full_page.status_code, 200)
        self.assertEqual(full_page.data["page_number"], 4)

        # Unauthenticated user cannot access reader endpoints.
        self.client.force_authenticate(None)
        manifest_resp = self.client.get(f"/books/{self.book.id}/read/manifest/")
        self.assertEqual(manifest_resp.status_code, 401)

        page_resp = self.client.get(f"/books/{self.book.id}/read/pages/11/")
        self.assertEqual(page_resp.status_code, 401)

    def test_purchase_required_for_non_buyer(self):
        non_buyer = User.objects.create_user(
            email="nonbuyer@example.com",
            password="testpass123",
            first_name="Non",
            last_name="Buyer",
            handle="non_buyer",
        )
        self.client.force_authenticate(non_buyer)

        response = self.client.get(f"/books/{self.book.id}/read/manifest/")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], "purchase_required")

        page_resp = self.client.get(f"/books/{self.book.id}/read/pages/1/")
        self.assertEqual(page_resp.status_code, 403)
        self.assertEqual(page_resp.data["code"], "purchase_required")

    def test_read_page_redacts_private_storage_urls_from_html_and_blocks(self):
        BookContent.objects.filter(book=self.book, page_number=2).update(
            blocks=[
                {
                    "id": "blk_2_0",
                    "type": "paragraph",
                    "text": "private link",
                    "metadata": {
                        "render_mode": "html",
                        "render_html": '<p><img src="https://media.quaduni.com/books/files/2026/04/secret.pdf" /></p>',
                    },
                },
                {
                    "id": "blk_2_1",
                    "type": "image",
                    "metadata": {
                        "source_url": "https://media.quaduni.com/extracted_images/test/page-2.png",
                        "safe_label": "page image",
                    },
                },
            ]
        )

        self.client.force_authenticate(self.owner)
        response = self.client.get(f"/books/{self.book.id}/read/pages/2/")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("books/files/", response.data["render_html"])
        self.assertIn('src="#"', response.data["render_html"])
        self.assertEqual(response.data["blocks"][1]["metadata"]["source_url"], None)
        self.assertEqual(response.data["blocks"][1]["metadata"]["safe_label"], "page image")

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

    def test_manifest_uses_tallest_page_frame_dimensions(self):
        BookContent.objects.filter(book=self.book, page_number=1).update(
            blocks=[
                {
                    "id": "blk_1_0",
                    "type": "paragraph",
                    "text": "Page 1 text",
                    "metadata": {
                        "render_mode": "html",
                        "render_html": "<p>Page 1 text</p>",
                        "page_width": 510.0,
                        "page_height": 760.0,
                    },
                }
            ]
        )
        BookContent.objects.filter(book=self.book, page_number=2).update(
            blocks=[
                {
                    "id": "blk_2_0",
                    "type": "paragraph",
                    "text": "Page 2 text",
                    "metadata": {
                        "render_mode": "html",
                        "render_html": "<p>Page 2 text</p>",
                        "page_width": 540.0,
                        "page_height": 900.0,
                    },
                }
            ]
        )
        BookContent.objects.filter(book=self.book, page_number=3).update(
            blocks=[
                {
                    "id": "blk_3_0",
                    "type": "paragraph",
                    "text": "Page 3 text",
                    "metadata": {
                        "render_mode": "html",
                        "render_html": "<p>Page 3 text</p>",
                        "page_width": 560.0,
                        "page_height": 900.0,
                    },
                }
            ]
        )

        self.client.force_authenticate(self.owner)
        response = self.client.get(f"/books/{self.book.id}/read/manifest/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["page_frame_height"], 900.0)
        self.assertEqual(response.data["page_frame_width"], 560.0)

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

    @patch("apps.books.tasks.process_book_upload_task.delay")
    def test_auto_backfill_queues_when_content_missing(self, mocked_delay):
        book = Book.objects.create(
            title="Backfill Needed",
            author="Owner User",
            owner=self.owner,
            status="published",
            is_visible=True,
            extraction_status="failed",
            total_pages=0,
            price="12.00",
            category="BOOKS",
        )
        BookFile.objects.create(
            book=book,
            file=_minimal_pdf_file("backfill.pdf"),
            original_filename="backfill.pdf",
            file_size=128,
            mime_type="application/pdf",
        )

        self.client.force_authenticate(self.owner)
        response = self.client.get(f"/books/{book.id}/read/manifest/")
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data["status"], "processing")
        mocked_delay.assert_called_once_with(book.id)

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
