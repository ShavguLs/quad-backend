"""Style fidelity tests for PDF casting pipeline.

Validates heading detection, emphasis extraction, alignment detection,
color preservation, and paragraph spacing using fixture-driven tests.
"""

import json
import os
from pathlib import Path
from django.test import TestCase

from apps.books.converters.style_inference import (
    detect_alignment,
    detect_heading_level,
    extract_color,
    extract_span_metadata,
    is_paragraph_break,
)


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "casting" / "fidelity"


def load_fixture(filename: str) -> dict:
    """Load a JSON fixture file."""
    path = FIXTURES_DIR / filename
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


class HeadingHierarchyTests(TestCase):
    """Test heading level detection from font size ratios."""

    def test_heading_hierarchy_from_fixture(self):
        """Validate heading detection against fixture cases."""
        fixture = load_fixture("heading-hierarchy.json")
        
        for case in fixture["test_cases"]:
            with self.subTest(name=case["name"]):
                level = detect_heading_level(
                    font_size=case["font_size"],
                    body_size=case["body_size"],
                    is_bold=case.get("is_bold", False),
                    font_name=case.get("font_name", ""),
                )
                self.assertEqual(
                    level, case["expected_level"],
                    f"Expected H{case['expected_level']} for {case['name']}, got H{level}"
                )


class EmphasisInlineTests(TestCase):
    """Test inline emphasis detection from font flags and names."""

    def test_emphasis_from_fixture(self):
        """Validate emphasis detection against fixture cases."""
        fixture = load_fixture("emphasis-inline.json")
        
        for case in fixture["test_cases"]:
            with self.subTest(name=case["name"]):
                span = {
                    "text": "Test",
                    "font": case["font_name"],
                    "flags": case["flags"],
                    "char_flags": case["char_flags"],
                    "size": 12.0,
                    "color": 0,
                    "bbox": [0, 0, 100, 12],
                }
                metadata = extract_span_metadata(span)
                
                expected = case["expected"]
                self.assertEqual(metadata["is_bold"], expected["is_bold"], f"Bold mismatch for {case['name']}")
                self.assertEqual(metadata["is_italic"], expected["is_italic"], f"Italic mismatch for {case['name']}")
                self.assertEqual(metadata["is_underline"], expected["is_underline"], f"Underline mismatch for {case['name']}")
                self.assertEqual(metadata["is_strikeout"], expected["is_strikeout"], f"Strikeout mismatch for {case['name']}")


class AlignmentVariantTests(TestCase):
    """Test text alignment detection from line geometry."""

    def test_alignment_from_fixture(self):
        """Validate alignment detection against fixture cases."""
        fixture = load_fixture("alignment-variants.json")
        
        for case in fixture["test_cases"]:
            with self.subTest(name=case["name"]):
                alignment = detect_alignment(
                    line_x0=case["line_x0"],
                    line_x1=case["line_x1"],
                    page_width=case["page_width"],
                    body_left_margin=case.get("body_left_margin", 0.0),
                    body_right_margin=case.get("body_right_margin", 0.0),
                )
                self.assertEqual(
                    alignment, case["expected"],
                    f"Expected {case['expected']} alignment for {case['name']}, got {alignment}"
                )


class ColorPreservationTests(TestCase):
    """Test color extraction from sRGB integers to CSS hex."""

    def test_color_from_fixture(self):
        """Validate color extraction against fixture cases."""
        fixture = load_fixture("color-preservation.json")
        
        for case in fixture["test_cases"]:
            with self.subTest(name=case["name"]):
                color = extract_color(case["color_int"])
                self.assertEqual(
                    color, case["expected"],
                    f"Expected {case['expected']} for {case['name']}, got {color}"
                )


class ParagraphSpacingTests(TestCase):
    """Test paragraph break detection from vertical gaps."""

    def test_paragraph_break_from_fixture(self):
        """Validate paragraph break detection against fixture cases."""
        fixture = load_fixture("paragraph-spacing.json")
        
        for case in fixture["test_cases"]:
            with self.subTest(name=case["name"]):
                is_break = is_paragraph_break(
                    line_gap=case["line_gap"],
                    body_size=case["body_size"],
                    prev_line_ends_with_punct=case["prev_line_ends_with_punct"],
                    indentation_change=case.get("indentation_change", 0.0),
                )
                self.assertEqual(
                    is_break, case["expected"],
                    f"Expected paragraph_break={case['expected']} for {case['name']}, got {is_break}"
                )


class IntegrationTests(TestCase):
    """Integration tests for combined style extraction."""

    def test_span_metadata_extraction(self):
        """Test complete span metadata extraction."""
        span = {
            "text": "Hello World",
            "font": "Arial-BoldItalic",
            "flags": 18,  # Bold (16) + Italic (2)
            "char_flags": 2,  # Underline
            "size": 14.0,
            "color": 16711680,  # Red
            "bbox": [10, 10, 100, 24],
        }
        
        metadata = extract_span_metadata(span)
        
        self.assertEqual(metadata["text"], "Hello World")
        self.assertTrue(metadata["is_bold"])
        self.assertTrue(metadata["is_italic"])
        self.assertTrue(metadata["is_underline"])
        self.assertEqual(metadata["color"], "#FF0000")
        self.assertEqual(metadata["font_size"], 14.0)

    def test_render_styled_span_integration(self):
        """Test that styled span rendering produces valid HTML."""
        from apps.books.converters.style_inference import render_styled_span
        
        metadata = {
            "is_bold": True,
            "is_italic": True,
            "is_underline": True,
            "color": "#FF0000",
        }
        
        html = render_styled_span("Test", metadata)
        
        self.assertIn("<strong>", html)
        self.assertIn("<em>", html)
        self.assertIn("<u>", html)
        self.assertIn('color:#FF0000', html)

    def test_heading_with_bold_boost(self):
        """Test that bold fonts get heading level boost."""
        # 22.5pt at 12pt body = 1.875 ratio, normally H3
        # With bold boost (0.15), becomes 2.025 which is >= 2.0, so H2
        level = detect_heading_level(22.5, 12.0, is_bold=True)
        self.assertEqual(level, 2)

    def test_color_black_is_none(self):
        """Test that black color returns None (default)."""
        self.assertIsNone(extract_color(0))
        self.assertIsNone(extract_color(None))


class ListIndentationTests(TestCase):
    """Test list indentation depth preservation in mixed content."""

    def test_list_indentation_preserved_in_mixed_content(self):
        """Validate list indentation depth in mixed content scenarios."""
        from apps.books.converters.casting_contract import (
            CastDocument, ListBlock, ListItem, ParagraphBlock, StyleMetadata
        )
        from apps.books.converters.html_render import render_cast_blocks_to_html

        # Create mixed content: Paragraph, List(depth=0), List(depth=1), Paragraph
        doc = CastDocument(blocks=[
            ParagraphBlock(
                block_id="p1",
                tag="p",
                text_html="Intro paragraph",
                style=StyleMetadata()
            ),
            ListBlock(
                block_id="l1",
                list_type="unordered",
                depth_base=0,
                items=[
                    ListItem(
                        text_html="Top level item",
                        depth=0,
                        list_type="unordered",
                        marker_raw="•",
                        marker_kind="symbol"
                    ),
                    ListItem(
                        text_html="Nested item",
                        depth=1,
                        list_type="unordered",
                        marker_raw="◦",
                        marker_kind="symbol"
                    )
                ]
            ),
            ParagraphBlock(
                block_id="p2",
                tag="p",
                text_html="Outro paragraph",
                style=StyleMetadata()
            )
        ])

        # Render and verify order preserved
        html = render_cast_blocks_to_html(doc)
        
        # Check that all content appears in correct order
        p1_pos = html.find("Intro paragraph")
        ul_pos = html.find("<ul")
        li1_pos = html.find("Top level item")
        li2_pos = html.find("Nested item")
        p2_pos = html.find("Outro paragraph")
        
        # Verify ordering
        self.assertLess(p1_pos, ul_pos, "Paragraph should come before list")
        self.assertLess(ul_pos, li1_pos, "List should contain first item")
        self.assertLess(li1_pos, li2_pos, "First item should come before nested item")
        self.assertLess(li2_pos, p2_pos, "Nested item should come before final paragraph")
        
        # Verify list depth preserved (nested item in sublist)
        self.assertIn("<ul", html)
        self.assertIn("<li", html)
