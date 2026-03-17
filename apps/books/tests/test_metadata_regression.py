"""Metadata regression tests for heading/alignment/style preservation.

These tests verify that PDF extraction preserves heading hierarchy, alignment,
color, and font metadata through the extraction-to-HTML pipeline.

Run with: pytest api/apps/books/tests/test_metadata_regression.py -v
"""
import json
from pathlib import Path
from typing import Any

from django.test import TestCase

from apps.books.converters.casting_contract import (
    CastDocument,
    ParagraphBlock,
    StyleMetadata,
)
from apps.books.converters.html_render import render_cast_blocks_to_html

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "casting" / "metadata"


def load_fixture(filename: str) -> dict[str, Any]:
    """Load a JSON fixture file."""
    fixture_path = FIXTURES_DIR / filename
    with open(fixture_path, "r", encoding="utf-8") as f:
        return json.load(f)


def create_paragraph_block(block_data: dict) -> ParagraphBlock:
    """Create a ParagraphBlock from fixture data.
    
    Args:
        block_data: Dict with type, text, attrs, formatting fields
        
    Returns:
        ParagraphBlock configured from the fixture
    """
    block_type = block_data.get("type", "paragraph")
    text = block_data.get("text", "")
    attrs = block_data.get("attrs", {})
    formatting = block_data.get("formatting", {})
    
    # Map block type to HTML tag
    if block_type == "heading":
        level = attrs.get("level", 1)
        tag = f"h{level}"
    elif block_type == "paragraph":
        tag = "p"
    elif block_type == "list_item":
        tag = "li"
    else:
        tag = "p"
    
    # Create style metadata from formatting
    style = StyleMetadata(
        is_bold=formatting.get("bold", False),
        is_italic=formatting.get("italic", False),
        color=formatting.get("color"),
        align=formatting.get("alignment", "left"),
        font_name=formatting.get("font_family"),
        font_size=formatting.get("font_size"),
    )
    
    return ParagraphBlock(
        block_id=block_data.get("id", ""),
        tag=tag,
        text_html=text,
        style=style,
    )


def create_document_from_fixture(test_case: dict) -> CastDocument:
    """Create a CastDocument from a test case fixture.
    
    Args:
        test_case: Dict with input_blocks list
        
    Returns:
        CastDocument with ParagraphBlock instances
    """
    blocks = [
        create_paragraph_block(block_data)
        for block_data in test_case.get("input_blocks", [])
    ]
    
    return CastDocument(blocks=blocks)


class HeadingAlignmentRegressionTests(TestCase):
    """Test heading hierarchy and alignment preservation from fixtures."""
    
    @classmethod
    def setUpClass(cls):
        """Load fixtures once for all tests."""
        super().setUpClass()
        cls.fixture = load_fixture("heading-alignment-fixtures.json")
        cls.test_cases = {
            case["name"]: case 
            for case in cls.fixture.get("test_cases", [])
        }
    
    def run_fixture_test(self, case_name: str):
        """Run a single fixture test case.
        
        Args:
            case_name: Name of the test case in the fixture
        """
        case = self.test_cases.get(case_name)
        if not case:
            self.fail(f"Test case '{case_name}' not found in fixture")
        
        # Create document from fixture
        doc = create_document_from_fixture(case)
        
        # Render to HTML
        html = render_cast_blocks_to_html(doc, include_metadata=False)
        
        # Check expected HTML
        if "expected_html" in case:
            self.assertEqual(
                html.strip(),
                case["expected_html"].strip(),
                f"HTML mismatch for test case: {case_name}"
            )
        
        # Check expected HTML contains patterns
        if "expected_html_contains" in case:
            for pattern in case["expected_html_contains"]:
                self.assertIn(
                    pattern,
                    html,
                    f"Expected pattern '{pattern}' not found in HTML for test case: {case_name}"
                )
    
    def test_h1_centered_preservation(self):
        """H1 with center alignment preserved through extraction."""
        self.run_fixture_test("h1_centered_preservation")
    
    def test_h2_right_aligned_preservation(self):
        """H2 with right alignment preserved."""
        self.run_fixture_test("h2_right_aligned_preservation")
    
    def test_h3_justify_alignment(self):
        """H3 with justify alignment."""
        self.run_fixture_test("h3_justify_alignment")
    
    def test_heading_hierarchy_h1_through_h6(self):
        """All heading levels H1-H6 render correctly."""
        self.run_fixture_test("heading_hierarchy_h1_through_h6")
    
    def test_color_extraction_and_rendering(self):
        """Color metadata extracted and rendered as inline style."""
        self.run_fixture_test("color_extraction_and_rendering")
    
    def test_color_and_bold_combined(self):
        """Both color and bold rendered together."""
        self.run_fixture_test("color_and_bold_combined")
    
    def test_bold_formatting_preserved(self):
        """Bold formatting renders with font-weight."""
        self.run_fixture_test("bold_formatting_preserved")
    
    def test_center_aligned_paragraph(self):
        """Center alignment on paragraph preserved."""
        self.run_fixture_test("center_aligned_paragraph")
    
    def test_right_aligned_paragraph(self):
        """Right alignment on paragraph preserved."""
        self.run_fixture_test("right_aligned_paragraph")
    
    def test_justify_aligned_paragraph(self):
        """Justify alignment on paragraph preserved."""
        self.run_fixture_test("justify_aligned_paragraph")
    
    def test_heading_with_color_and_alignment(self):
        """H2 with both color and center alignment."""
        self.run_fixture_test("heading_with_color_and_alignment")
    
    def test_mixed_content_preservation(self):
        """Mixed heading and paragraph content with various styles."""
        self.run_fixture_test("mixed_content_preservation")
    
    def test_default_alignment_no_class(self):
        """Left alignment produces no CSS class (default)."""
        self.run_fixture_test("default_alignment_no_class")
    
    def test_no_alignment_no_class(self):
        """No alignment specified produces no CSS class."""
        self.run_fixture_test("no_alignment_no_class")
    
    def test_heading_no_alignment_no_class(self):
        """Heading without alignment has no align class."""
        self.run_fixture_test("heading_no_alignment_no_class")
    
    def test_complex_styling_hierarchy(self):
        """Complex document with multiple style combinations."""
        self.run_fixture_test("complex_styling_hierarchy")


class MetadataEdgeCaseTests(TestCase):
    """Additional edge case tests for metadata handling."""
    
    def test_empty_document(self):
        """Empty document returns empty string."""
        doc = CastDocument(blocks=[])
        html = render_cast_blocks_to_html(doc)
        self.assertEqual(html, "")
    
    def test_paragraph_without_formatting(self):
        """Paragraph without any formatting renders correctly."""
        block = ParagraphBlock(
            block_id="1",
            tag="p",
            text_html="Plain text",
            style=StyleMetadata(),
        )
        doc = CastDocument(blocks=[block])
        html = render_cast_blocks_to_html(doc)
        self.assertIn("Plain text", html)
        self.assertIn("<p", html)
    
    def test_heading_with_all_formatting(self):
        """Heading with bold, italic, color, and alignment."""
        block = ParagraphBlock(
            block_id="1",
            tag="h2",
            text_html="Styled Heading",
            style=StyleMetadata(
                is_bold=True,
                is_italic=True,
                color="#FF0000",
                align="center",
            ),
        )
        doc = CastDocument(blocks=[block])
        html = render_cast_blocks_to_html(doc)
        # Should contain supported styling (italic not supported by backend renderer)
        self.assertIn("<h2", html)
        self.assertIn("color:#FF0000", html)
        self.assertIn("text-align:center", html)
        self.assertIn("font-weight:700", html)
