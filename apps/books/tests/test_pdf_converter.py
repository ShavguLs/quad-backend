from unittest import TestCase
from unittest.mock import patch

from apps.books.converters.pdf_converter import PDFConverter
from apps.books.converters.html_render import (
    render_cast_blocks_to_html,
    render_simple_list,
)
from apps.books.converters.casting_contract import (
    CastDocument,
    ListBlock,
    ListItem,
)
from apps.books.models import Book


class _FakePage:
    def __init__(self, payload):
        self.payload = payload

    def get_text(self, mode):
        if mode != "dict":
            raise ValueError("Unexpected mode")
        return self.payload


class _FakeConvertPixmap:
    def tobytes(self, _format):
        return b'png-bytes'


class _FakeConvertPage:
    def __init__(self, payload):
        self.payload = payload
        self.get_text_calls = 0

    def get_text(self, mode):
        if mode != "dict":
            raise ValueError("Unexpected mode")
        self.get_text_calls += 1
        return self.payload

    def get_pixmap(self, dpi):
        if dpi <= 0:
            raise ValueError("Invalid DPI")
        return _FakeConvertPixmap()

    def get_links(self):
        return []

    def get_drawings(self):
        return []

    def find_tables(self):
        return None


class _FakeConvertDoc:
    def __init__(self, pages):
        self.pages = pages

    def __len__(self):
        return len(self.pages)

    def load_page(self, index):
        return self.pages[index]

    def close(self):
        return None


class PDFConverterFormattingTests(TestCase):
    def setUp(self):
        self.converter = PDFConverter()

    def test_extract_page_html_preserves_heading_size_spacing_and_emphasis(self):
        payload = {
            "width": 600,
            "blocks": [
                {
                    "type": 0,
                    "lines": [
                        {
                            "spans": [
                                {
                                    "text": "Chapter 1",
                                    "font": "Times-Bold",
                                    "size": 24,
                                    "bbox": [50, 60, 250, 88],
                                }
                            ]
                        },
                        {
                            "spans": [
                                {
                                    "text": "This is body text.",
                                    "font": "Times-Roman",
                                    "size": 12,
                                    "bbox": [50, 120, 260, 136],
                                }
                            ]
                        },
                        {
                            "spans": [
                                {
                                    "text": "Emphasis",
                                    "font": "Times-Italic",
                                    "size": 12,
                                    "bbox": [50, 142, 145, 158],
                                }
                            ]
                        },
                    ]
                }
            ]
        }

        html = self.converter._extract_page_html(_FakePage(payload))

        self.assertRegex(html, r"<h[1-3]")
        self.assertIn("Chapter 1", html)
        self.assertIn("font-size:24.0px", html)
        self.assertIn("margin-bottom:", html)
        self.assertIn("<p", html)
        self.assertIn("This is body text.", html)
        self.assertIn("<em>Emphasis</em>", html)

    def test_extract_page_html_uses_flags_for_bold_and_detects_center_alignment(self):
        payload = {
            "width": 600,
            "blocks": [
                {
                    "type": 0,
                    "lines": [
                        {
                            "spans": [
                                {
                                    "text": "Centered Title",
                                    "font": "Custom-Regular",
                                    "flags": 16,
                                    "size": 22,
                                    "bbox": [190, 70, 410, 96],
                                }
                            ]
                        },
                        {
                            "spans": [
                                {
                                    "text": "Body line",
                                    "font": "Custom-Regular",
                                    "size": 12,
                                    "bbox": [50, 120, 220, 136],
                                }
                            ]
                        },
                    ]
                }
            ]
        }

        html = self.converter._extract_page_html(_FakePage(payload))

        self.assertIn("text-align:center", html)
        self.assertIn("<strong>Centered Title</strong>", html)

    def test_extract_page_html_returns_placeholder_when_no_text(self):
        payload = {"blocks": [{"type": 0, "lines": [{"spans": [{"text": "   "}]}]}]}

        html = self.converter._extract_page_html(_FakePage(payload))

        self.assertEqual(html, "<p>Start writing here...</p>")

    def test_convert_reuses_single_page_text_extraction_for_detection_and_html(self):
        payload = {
            "width": 600,
            "blocks": [
                {"type": 1, "bbox": [0, 0, 10, 10]},
                {
                    "type": 0,
                    "lines": [
                        {
                            "spans": [
                                {
                                    "text": "Body text",
                                    "font": "Times-Roman",
                                    "size": 12,
                                    "bbox": [50, 100, 140, 116],
                                }
                            ]
                        }
                    ],
                },
            ],
        }
        fake_page = _FakeConvertPage(payload)
        fake_doc = _FakeConvertDoc([fake_page])
        fake_book = Book(id=101)

        with patch('apps.books.converters.pdf_converter.pymupdf.open', return_value=fake_doc):
            with patch('apps.books.models.BookPage.objects.create', return_value=object()) as mocked_create:
                converted_pages = self.converter.convert(b'%PDF-1.4', fake_book)

        self.assertEqual(fake_page.get_text_calls, 1)
        self.assertEqual(len(converted_pages), 1)
        self.assertEqual(mocked_create.call_count, 1)
        self.assertEqual(len(self.converter.unsupported_styles), 1)
        self.assertEqual(self.converter.unsupported_styles[0].style_type, 'image')


class PDFConverterListSemanticsTests(TestCase):
    """Tests for CAST-05 list semantics in PDF converter output."""

    def setUp(self):
        self.converter = PDFConverter()

    def test_extract_page_html_preserves_ordered_unordered_semantics(self):
        """Ordered and unordered structures should be distinct semantic containers."""
        payload = {
            "width": 600,
            "blocks": [
                {
                    "type": 0,
                    "lines": [
                        {
                            "spans": [
                                {
                                    "text": "1. First ordered item",
                                    "font": "Times-Roman",
                                    "size": 12,
                                    "bbox": [50, 100, 250, 116],
                                }
                            ]
                        },
                        {
                            "spans": [
                                {
                                    "text": "2. Second ordered item",
                                    "font": "Times-Roman",
                                    "size": 12,
                                    "bbox": [50, 120, 250, 136],
                                }
                            ]
                        },
                        {
                            "spans": [
                                {
                                    "text": "• First bullet item",
                                    "font": "Times-Roman",
                                    "size": 12,
                                    "bbox": [50, 150, 250, 166],
                                }
                            ]
                        },
                        {
                            "spans": [
                                {
                                    "text": "• Second bullet item",
                                    "font": "Times-Roman",
                                    "size": 12,
                                    "bbox": [50, 170, 250, 186],
                                }
                            ]
                        },
                    ]
                }
            ]
        }

        html = self.converter._extract_page_html(_FakePage(payload))

        # Should have separate ol and ul containers
        self.assertIn("<ol", html)
        self.assertIn("</ol>", html)
        self.assertIn("<ul", html)
        self.assertIn("</ul>", html)

        # Should have list items
        self.assertIn("<li", html)
        self.assertIn("</li>", html)

    def test_extract_page_html_preserves_ordered_start_value(self):
        """Ordered lists with non-1 start should preserve start value."""
        payload = {
            "width": 600,
            "blocks": [
                {
                    "type": 0,
                    "lines": [
                        {
                            "spans": [
                                {
                                    "text": "3. Third item",
                                    "font": "Times-Roman",
                                    "size": 12,
                                    "bbox": [50, 100, 200, 116],
                                }
                            ]
                        },
                        {
                            "spans": [
                                {
                                    "text": "4. Fourth item",
                                    "font": "Times-Roman",
                                    "size": 12,
                                    "bbox": [50, 120, 200, 136],
                                }
                            ]
                        },
                    ]
                }
            ]
        }

        html = self.converter._extract_page_html(_FakePage(payload))

        # Should have start attribute
        self.assertIn('start="3"', html)

    def test_extract_page_html_includes_cast_metadata(self):
        """HTML output should include deterministic data-cast-* metadata."""
        payload = {
            "width": 600,
            "blocks": [
                {
                    "type": 0,
                    "lines": [
                        {
                            "spans": [
                                {
                                    "text": "1. Test item",
                                    "font": "Times-Roman",
                                    "size": 12,
                                    "bbox": [50, 100, 200, 116],
                                }
                            ]
                        },
                    ]
                }
            ]
        }

        html = self.converter._extract_page_html(_FakePage(payload))

        # Should have version metadata
        self.assertIn('data-cast-version="cast-list-v1"', html)

        # Should have depth metadata
        self.assertIn('data-cast-depth="0"', html)

        # Should have marker metadata
        self.assertIn('data-cast-marker-kind="decimal"', html)
        self.assertIn('data-cast-marker-raw="1"', html)

    def test_extract_page_html_handles_nested_lists(self):
        """Nested list structures should have proper depth metadata."""
        payload = {
            "width": 600,
            "blocks": [
                {
                    "type": 0,
                    "lines": [
                        {
                            "spans": [
                                {
                                    "text": "1. Parent item",
                                    "font": "Times-Roman",
                                    "size": 12,
                                    "bbox": [50, 100, 200, 116],
                                }
                            ]
                        },
                        {
                            "spans": [
                                {
                                    "text": "• Nested bullet",
                                    "font": "Times-Roman",
                                    "size": 12,
                                    "bbox": [80, 120, 220, 136],  # Indented
                                }
                            ]
                        },
                    ]
                }
            ]
        }

        html = self.converter._extract_page_html(_FakePage(payload))

        # Should have depth=1 for nested item
        self.assertIn('data-cast-depth="1"', html)

    def test_extract_page_html_mixed_style_splits_blocks(self):
        """Mixed ordered/unordered at same depth should create separate blocks."""
        payload = {
            "width": 600,
            "blocks": [
                {
                    "type": 0,
                    "lines": [
                        {
                            "spans": [
                                {
                                    "text": "1. Ordered item",
                                    "font": "Times-Roman",
                                    "size": 12,
                                    "bbox": [50, 100, 200, 116],
                                }
                            ]
                        },
                        {
                            "spans": [
                                {
                                    "text": "• Unordered item",
                                    "font": "Times-Roman",
                                    "size": 12,
                                    "bbox": [50, 120, 200, 136],
                                }
                            ]
                        },
                        {
                            "spans": [
                                {
                                    "text": "2. Back to ordered",
                                    "font": "Times-Roman",
                                    "size": 12,
                                    "bbox": [50, 140, 200, 156],
                                }
                            ]
                        },
                    ]
                }
            ]
        }

        html = self.converter._extract_page_html(_FakePage(payload))

        # Should have multiple ol/ul containers (at least 2)
        ol_count = html.count("<ol")
        ul_count = html.count("<ul")

        # Should have at least 2 list containers total
        self.assertGreaterEqual(ol_count + ul_count, 2)


class HTMLRendererContractTests(TestCase):
    """Tests for HTML renderer contract compliance."""

    def test_render_cast_blocks_emits_semantic_list_tags(self):
        """Renderer should emit semantic ol/ul/li tags."""
        block = ListBlock(
            block_id="list-1",
            list_type="ordered",
            depth_base=0,
            items=[
                ListItem(
                    text_html="Item 1",
                    depth=0,
                    list_type="ordered",
                    marker_raw="1",
                    marker_kind="decimal",
                    marker_value=1,
                ),
                ListItem(
                    text_html="Item 2",
                    depth=0,
                    list_type="ordered",
                    marker_raw="2",
                    marker_kind="decimal",
                    marker_value=2,
                ),
            ]
        )
        document = CastDocument(blocks=[block])

        html = render_cast_blocks_to_html(document)

        self.assertIn("<ol", html)
        self.assertIn("</ol>", html)
        self.assertIn("<li", html)
        self.assertIn("Item 1", html)
        self.assertIn("Item 2", html)
        self.assertIn("</li>", html)

    def test_render_cast_blocks_preserves_unordered_semantics(self):
        """Renderer should use ul for unordered lists."""
        block = ListBlock(
            block_id="list-1",
            list_type="unordered",
            depth_base=0,
            items=[
                ListItem(
                    text_html="Bullet 1",
                    depth=0,
                    list_type="unordered",
                    marker_raw="•",
                    marker_kind="symbol",
                    symbol="bullet",
                ),
            ]
        )
        document = CastDocument(blocks=[block])

        html = render_cast_blocks_to_html(document)

        self.assertIn("<ul", html)
        self.assertIn("</ul>", html)
        self.assertIn('data-cast-symbol="bullet"', html)

    def test_render_cast_blocks_includes_depth_metadata(self):
        """Renderer should include depth metadata on list items."""
        block = ListBlock(
            block_id="list-1",
            list_type="ordered",
            depth_base=0,
            items=[
                ListItem(
                    text_html="Parent",
                    depth=0,
                    list_type="ordered",
                    marker_raw="1",
                    marker_kind="decimal",
                    marker_value=1,
                ),
                ListItem(
                    text_html="Nested",
                    depth=1,
                    list_type="unordered",
                    marker_raw="•",
                    marker_kind="symbol",
                    symbol="bullet",
                ),
            ]
        )
        document = CastDocument(blocks=[block])

        html = render_cast_blocks_to_html(document)

        # Should have both depth values
        self.assertIn('data-cast-depth="0"', html)
        self.assertIn('data-cast-depth="1"', html)

    def test_render_cast_blocks_preserves_start_value(self):
        """Renderer should preserve non-1 start values for ordered lists."""
        block = ListBlock(
            block_id="list-1",
            list_type="ordered",
            depth_base=0,
            start_value=5,
            items=[
                ListItem(
                    text_html="Item 5",
                    depth=0,
                    list_type="ordered",
                    marker_raw="5",
                    marker_kind="decimal",
                    marker_value=5,
                ),
            ]
        )
        document = CastDocument(blocks=[block])

        html = render_cast_blocks_to_html(document)

        self.assertIn('start="5"', html)

    def test_render_cast_blocks_is_deterministic(self):
        """Same input should produce identical output."""
        block = ListBlock(
            block_id="list-1",
            list_type="ordered",
            depth_base=0,
            items=[
                ListItem(
                    text_html="Item",
                    depth=0,
                    list_type="ordered",
                    marker_raw="1",
                    marker_kind="decimal",
                    marker_value=1,
                ),
            ]
        )
        document = CastDocument(blocks=[block])

        html1 = render_cast_blocks_to_html(document)
        html2 = render_cast_blocks_to_html(document)

        self.assertEqual(html1, html2)
