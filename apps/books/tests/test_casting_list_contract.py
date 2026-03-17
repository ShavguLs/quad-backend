"""Fixture-driven contract tests for CAST-05 list semantics.

These tests validate the canonical list contract behavior independent
of rendering, ensuring deterministic list classification and depth handling.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List
from unittest import TestCase

from apps.books.converters.casting_contract import (
    CAST_DOC_SCHEMA_VERSION,
    CAST_LIST_SCHEMA_VERSION,
    ListBlock,
    ListItem,
)
from apps.books.converters.list_inference import (
    classify_line_kind,
    compute_indent_unit,
    infer_depth,
    infer_list_blocks,
)

# Fixture directory path
FIXTURES_DIR = Path(__file__).parent / "fixtures" / "casting" / "lists"


def load_fixture(name: str) -> Dict[str, Any]:
    """Load a JSON fixture file."""
    fixture_path = FIXTURES_DIR / f"{name}.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        return json.load(f)


class CastingContractBasicTests(TestCase):
    """Basic unit tests for contract primitives."""

    def test_schema_version_constant(self):
        """Schema version should be a stable string."""
        self.assertEqual(CAST_LIST_SCHEMA_VERSION, "cast-list-v1")
        self.assertIsInstance(CAST_LIST_SCHEMA_VERSION, str)

    def test_classify_line_kind_ordered(self):
        """Should classify decimal markers as ordered."""
        self.assertEqual(classify_line_kind("1. First item"), "ordered")
        self.assertEqual(classify_line_kind("10. Tenth item"), "ordered")
        self.assertEqual(classify_line_kind("a. Alpha item"), "ordered")
        self.assertEqual(classify_line_kind("I. Roman item"), "ordered")

    def test_classify_line_kind_unordered(self):
        """Should classify bullet symbols as unordered."""
        self.assertEqual(classify_line_kind("• Bullet item"), "unordered")
        self.assertEqual(classify_line_kind("- Dash item"), "unordered")

    def test_classify_line_kind_paragraph(self):
        """Should classify plain text as paragraph."""
        self.assertEqual(classify_line_kind("Plain text"), "paragraph")
        self.assertEqual(classify_line_kind("No marker here"), "paragraph")

    def test_compute_indent_unit_basic(self):
        """Should compute median delta from x positions."""
        # Regular 24pt indentation
        x_positions = [50, 50, 74, 74, 98, 98]
        unit = compute_indent_unit(x_positions)
        self.assertAlmostEqual(unit, 24.0, places=1)

    def test_compute_indent_unit_with_jitter(self):
        """Should handle x-coordinate jitter gracefully."""
        # Positions with minor jitter
        x_positions = [50, 50.5, 74.2, 73.8, 98.1, 97.9]
        unit = compute_indent_unit(x_positions)
        # Should still identify ~24pt unit
        self.assertGreater(unit, 20.0)
        self.assertLess(unit, 30.0)

    def test_infer_depth_basic(self):
        """Should compute depth from offset and unit."""
        base_x0 = 50.0
        indent_unit = 24.0

        self.assertEqual(infer_depth(50, base_x0, indent_unit), 0)
        self.assertEqual(infer_depth(74, base_x0, indent_unit), 1)
        self.assertEqual(infer_depth(98, base_x0, indent_unit), 2)

    def test_infer_depth_with_tolerance(self):
        """Should tolerate minor x-coordinate variations."""
        base_x0 = 50.0
        indent_unit = 24.0

        # Within tolerance of depth 1
        self.assertEqual(infer_depth(74.5, base_x0, indent_unit), 1)
        self.assertEqual(infer_depth(73.5, base_x0, indent_unit), 1)

    def test_list_block_add_item_updates_start_value(self):
        """Adding items should update block start_value for ordered lists."""
        block = ListBlock(block_id="test", list_type="ordered", depth_base=0)

        from apps.books.converters.casting_contract import ListItem

        item1 = ListItem(
            text_html="Item 3",
            depth=0,
            list_type="ordered",
            marker_raw="3",
            marker_kind="decimal",
            marker_value=3,
        )
        block.add_item(item1)

        self.assertEqual(block.start_value, 3)
        self.assertEqual(len(block.items), 1)


class CastingContractFixtureTests(TestCase):
    """Fixture-driven tests for CAST-05 list semantics."""

    def test_ordered_decimal_start(self):
        """Ordered list with non-1 start value should preserve start."""
        fixture = load_fixture("ordered-decimal-start")
        lines = fixture["lines"]
        expected = fixture["expected"]

        doc = infer_list_blocks(lines)

        # Should produce exactly one block
        self.assertEqual(len(doc.blocks), expected["block_count"])

        block = doc.blocks[0]
        self.assertEqual(block.list_type, "ordered")
        self.assertEqual(block.start_value, 3)
        self.assertEqual(len(block.items), 3)

        # Verify marker values
        for i, item in enumerate(block.items):
            expected_item = expected["blocks"][0]["items"][i]
            self.assertEqual(item.marker_raw, expected_item["marker_raw"])
            self.assertEqual(item.marker_kind, expected_item["marker_kind"])
            self.assertEqual(item.marker_value, expected_item["marker_value"])

    def test_unordered_symbol_variants(self):
        """Various bullet symbols should normalize to unordered with symbol metadata."""
        fixture = load_fixture("unordered-symbol-variants")
        lines = fixture["lines"]
        expected = expected = fixture["expected"]

        doc = infer_list_blocks(lines)

        # Should produce one unordered block
        self.assertEqual(len(doc.blocks), expected["block_count"])

        block = doc.blocks[0]
        self.assertEqual(block.list_type, "unordered")
        self.assertEqual(len(block.items), 5)

        # Verify each item has correct symbol
        for i, item in enumerate(block.items):
            expected_item = expected["blocks"][0]["items"][i]
            self.assertEqual(item.marker_raw, expected_item["marker_raw"])
            self.assertEqual(item.symbol, expected_item["symbol"])

    def test_mixed_style_creates_separate_blocks(self):
        """Same-depth mixed ordered/unordered should split into separate blocks."""
        fixture = load_fixture("mixed-style-split")
        lines = fixture["lines"]
        expected = fixture["expected"]

        doc = infer_list_blocks(lines)

        # Should produce three blocks
        self.assertEqual(len(doc.blocks), expected["block_count"])

        # First block: ordered (items 1-2)
        self.assertEqual(doc.blocks[0].list_type, "ordered")
        self.assertEqual(len(doc.blocks[0].items), 2)
        self.assertEqual(doc.blocks[0].start_value, 1)

        # Second block: unordered (items 3-4)
        self.assertEqual(doc.blocks[1].list_type, "unordered")
        self.assertEqual(len(doc.blocks[1].items), 2)

        # Third block: ordered (item 5)
        self.assertEqual(doc.blocks[2].list_type, "ordered")
        self.assertEqual(len(doc.blocks[2].items), 1)
        self.assertEqual(doc.blocks[2].start_value, 3)

    def test_indent_bucketization_is_stable(self):
        """Nesting depth should stay stable under minor x-coordinate jitter."""
        fixture = load_fixture("nested-indent-jitter")
        lines = fixture["lines"]
        expected = fixture["expected"]

        doc = infer_list_blocks(lines)

        # Should produce four blocks with stable depths
        self.assertEqual(len(doc.blocks), expected["block_count"])

        # Verify block depths are stable despite jitter
        for i, block in enumerate(doc.blocks):
            expected_block = expected["blocks"][i]
            self.assertEqual(
                block.depth_base,
                expected_block["depth_base"],
                f"Block {i} depth mismatch"
            )

        # Verify individual item depths
        item_idx = 0
        for block_idx, block in enumerate(doc.blocks):
            expected_block = expected["blocks"][block_idx]
            for item_idx_in_block, item in enumerate(block.items):
                expected_item = expected_block["items"][item_idx_in_block]
                self.assertEqual(
                    item.depth,
                    expected_item["depth"],
                    f"Block {block_idx} item {item_idx_in_block} depth mismatch"
                )
                item_idx += 1


class CastingContractDeterminismTests(TestCase):
    """Tests ensuring deterministic behavior across repeated runs."""

    def test_repeated_inference_produces_identical_output(self):
        """Same input should produce identical output every time."""
        lines = [
            {"text": "1. First", "x0": 50, "y0": 100, "html": "First"},
            {"text": "2. Second", "x0": 50, "y0": 120, "html": "Second"},
            {"text": "• Bullet", "x0": 50, "y0": 140, "html": "Bullet"},
        ]

        # Run inference multiple times
        results = [infer_list_blocks(lines) for _ in range(5)]

        # All results should have same structure
        for doc in results:
            self.assertEqual(len(doc.blocks), 2)
            self.assertEqual(doc.blocks[0].list_type, "ordered")
            self.assertEqual(doc.blocks[1].list_type, "unordered")

    def test_empty_lines_produce_empty_document(self):
        """Empty input should produce empty document."""
        doc = infer_list_blocks([])
        self.assertEqual(len(doc.blocks), 0)
        self.assertEqual(doc.schema_version, CAST_DOC_SCHEMA_VERSION)

    def test_paragraph_only_lines_produce_no_blocks(self):
        """Lines without list markers should produce no list blocks."""
        lines = [
            {"text": "Just a paragraph", "x0": 50, "y0": 100, "html": "Just a paragraph"},
            {"text": "Another paragraph", "x0": 50, "y0": 120, "html": "Another paragraph"},
        ]

        doc = infer_list_blocks(lines)
        self.assertEqual(len(doc.blocks), 0)
