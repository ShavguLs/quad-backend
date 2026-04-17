import pytest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from apps.books.models import (
    Book,
    BookContent,
    ContentVersion,
    PageNote,
    ReadingPosition,
    SavedPage,
)
from apps.books.tasks import _build_reader_blocks_from_page
from apps.books.converters.base import ConversionError
from apps.books.services.content import ContentService, OptimisticLockingError
from apps.books.views.main import SavedPageViewSet
from apps.users.models import User

pytestmark = pytest.mark.unit


class ReaderUnitTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="reader@example.com",
            password="testpass123",
            first_name="Reader",
            last_name="Unit",
            handle="reader_user",
        )
        self.book = Book.objects.create(
            title="Reader Unit Book",
            author="Unit Tester",
            owner=self.user,
            status="published",
            is_visible=True,
            extraction_status="completed",
            total_pages=1,
            price="0.00",
            category="BOOKS",
        )

    def _create_book_content(self, page_number=1, blocks=None):
        if blocks is None:
            blocks = [
                {
                    "id": f"blk_{page_number}_1",
                    "type": "paragraph",
                    "text": "Sample block text",
                }
            ]
        return BookContent.objects.create(
            book=self.book,
            page_number=page_number,
            blocks=blocks,
        )

    def test_reading_position_unique_constraint(self):
        ReadingPosition.objects.create(
            book=self.book,
            user=self.user,
            page_number=1,
        )

        with self.assertRaises(IntegrityError):
            ReadingPosition.objects.create(
                book=self.book,
                user=self.user,
                page_number=2,
            )

    def test_saved_page_limit_enforced_via_view(self):
        for page_number in range(1, SavedPage.MAX_PER_BOOK + 1):
            SavedPage.objects.create(
                book=self.book,
                user=self.user,
                page_number=page_number,
            )

        request = SimpleNamespace(
            data={"page_number": SavedPage.MAX_PER_BOOK + 1},
            user=self.user,
        )

        view = SavedPageViewSet()
        response = view.create(request, book_id=self.book.id)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "max_saved_pages_reached")

    def test_saved_page_duplicate_allowed_when_limit_reached(self):
        for page_number in range(1, SavedPage.MAX_PER_BOOK + 1):
            SavedPage.objects.create(
                book=self.book,
                user=self.user,
                page_number=page_number,
            )

        request = SimpleNamespace(
            data={"page_number": 1},
            user=self.user,
        )

        view = SavedPageViewSet()
        response = view.create(request, book_id=self.book.id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["page_number"], 1)
        self.assertEqual(
            SavedPage.objects.filter(book=self.book, user=self.user).count(),
            SavedPage.MAX_PER_BOOK,
        )

    def test_saved_page_page_number_bounds(self):
        with self.assertRaises(IntegrityError):
            SavedPage.objects.create(
                book=self.book,
                user=self.user,
                page_number=0,
            )

    def test_page_note_unique_constraint(self):
        PageNote.objects.create(
            book=self.book,
            user=self.user,
            page_number=4,
            content="first note",
        )

        with self.assertRaises(IntegrityError):
            PageNote.objects.create(
                book=self.book,
                user=self.user,
                page_number=4,
                content="second note",
            )

    def test_book_content_counts_and_stats(self):
        first_blocks = [
            {"id": "blk_a", "type": "paragraph", "text": "Hello world"},
            {"id": "blk_b", "type": "paragraph", "text": "Another block"},
        ]
        second_blocks = [
            {"id": "blk_c", "type": "paragraph", "text": "More content here"}
        ]

        first_page = self._create_book_content(page_number=1, blocks=first_blocks)
        second_page = self._create_book_content(page_number=2, blocks=second_blocks)

        self.assertEqual(first_page.block_count, len(first_blocks))
        self.assertEqual(first_page.word_count, 4)
        self.assertEqual(second_page.block_count, len(second_blocks))
        self.assertEqual(second_page.word_count, 3)

        stats = BookContent.get_stats_for_book(self.book.id)
        self.assertEqual(stats["page_count"], 2)
        self.assertEqual(stats["block_count"], len(first_blocks) + len(second_blocks))
        self.assertEqual(stats["word_count"], 7)

    def test_content_service_optimistic_locking_triggers(self):
        book_content = self._create_book_content(page_number=3)
        new_blocks = [{"id": "blk_new", "type": "paragraph", "text": "New draft"}]

        with patch("apps.books.services.content.ContentService.validate_blocks"):
            with self.assertRaises(OptimisticLockingError):
                ContentService.update_content(
                    book_content_id=book_content.id,
                    blocks=new_blocks,
                    expected_version=book_content.version + 1,
                    user=self.user,
                    change_summary="Attempted conflict",
                )

    def test_content_service_auto_save_throttles_quick_calls(self):
        book_content = self._create_book_content(page_number=4)
        blocks = [{"id": "blk_auto", "type": "paragraph", "text": "Auto save text"}]
        base_now = timezone.now()

        with patch("django.utils.timezone.now", return_value=base_now):
            with patch("apps.books.services.content.ContentService.validate_blocks"):
                version = ContentService.create_auto_save(
                    book_content_id=book_content.id,
                    blocks=blocks,
                    user=self.user,
                )
                throttled = ContentService.create_auto_save(
                    book_content_id=book_content.id,
                    blocks=blocks,
                    user=self.user,
                )

        self.assertIsNotNone(version)
        self.assertIsNone(throttled)
        self.assertEqual(
            ContentVersion.objects.filter(
                book_content=book_content, version_type="auto"
            ).count(),
            1,
        )

    def test_content_service_cleanup_old_versions(self):
        book_content = self._create_book_content(page_number=5)

        for version_number in range(1, 5):
            ContentVersion.objects.create(
                book_content=book_content,
                version_number=version_number,
                blocks_snapshot=[
                    {
                        "id": f"blk_{version_number}",
                        "type": "paragraph",
                        "text": "snapshot",
                    }
                ],
                version_type="auto",
            )

        old_time = timezone.now() - timedelta(days=10)
        ContentVersion.objects.filter(book_content=book_content).update(
            created_at=old_time
        )

        cleanup_now = timezone.now()
        with patch("django.utils.timezone.now", return_value=cleanup_now):
            deleted = ContentService.cleanup_old_versions(
                book_content_id=book_content.id,
                keep_count=2,
                keep_days=1,
            )

        remaining_versions = list(
            ContentVersion.objects.filter(book_content=book_content).values_list(
                "version_number", flat=True
            )
        )

        self.assertEqual(deleted, 2)
        self.assertCountEqual(remaining_versions, [3, 4])


class ReaderRenderModeUnitTests(TestCase):
    def test_build_reader_blocks_prefers_html_in_text_mode(self):
        blocks = _build_reader_blocks_from_page(
            {
                "page_number": 1,
                "text_content": "Text body",
                "html_content": "<p>HTML body</p>",
                "page_width": 600,
                "page_height": 900,
            },
            page_number=1,
            book_id=99,
            render_preference=Book.RENDER_PREFERENCE_TEXT,
        )

        metadata = blocks[0]["metadata"]
        self.assertEqual(metadata["render_mode"], "html")
        self.assertEqual(metadata["render_html"], "<p>HTML body</p>")
        self.assertIsNone(metadata["fallback_image_path"])

    @patch(
        "apps.books.tasks.PrivateMediaStorage.save",
        return_value="reader_fallback/99/0001.jpg",
    )
    def test_build_reader_blocks_forces_image_in_exact_visual_mode(self, mocked_save):
        blocks = _build_reader_blocks_from_page(
            {
                "page_number": 1,
                "text_content": "Text body",
                "html_content": "<p>HTML body</p>",
                "image_data": b"jpeg-bytes",
                "page_width": 600,
                "page_height": 900,
            },
            page_number=1,
            book_id=99,
            render_preference=Book.RENDER_PREFERENCE_EXACT_VISUAL,
        )

        metadata = blocks[0]["metadata"]
        self.assertEqual(metadata["render_mode"], "image")
        self.assertEqual(metadata["fallback_image_path"], "reader_fallback/99/0001.jpg")
        mocked_save.assert_called_once()

    def test_build_reader_blocks_raises_when_exact_visual_image_missing(self):
        with self.assertRaises(ConversionError):
            _build_reader_blocks_from_page(
                {
                    "page_number": 1,
                    "text_content": "Text body",
                    "html_content": "<p>HTML body</p>",
                },
                page_number=1,
                book_id=99,
                render_preference=Book.RENDER_PREFERENCE_EXACT_VISUAL,
            )
