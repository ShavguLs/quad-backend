"""Regression tests for PDF casting fidelity.

Uses pytest-regressions for golden file testing.
Run with: pytest -m regression
Update golden files: pytest -m regression --force-regen
"""
import pytest
from pathlib import Path
from io import BytesIO

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "regression"


@pytest.mark.regression
class TestCastingFidelityRegression:
    """Regression tests validating PDF casting preserves structure and style."""

    def test_list_simple_structure(self, data_regression):
        """Verify simple lists are preserved with correct types and markers."""
        from apps.books.tests.fixtures.regression.metadata import load_metadata
        metadata = load_metadata("list-simple")
        source_path = FIXTURES_DIR / "source" / metadata["source_pdf"]
        
        # Skip if source PDF doesn't exist yet (fixture not generated)
        if not source_path.exists():
            pytest.skip(f"Source PDF not found: {source_path}")
        
        from apps.books.converters import PDFConverter
        from apps.books.models import Book
        
        converter = PDFConverter()
        book = Book(title="Test", author="Test")
        book.save()
        
        try:
            with open(source_path, 'rb') as f:
                pages = converter.convert(f, book)
            
            # Get CastDocument from converter (if available) or reconstruct
            # For now, extract structure from pages content
            result = {
                "page_count": len(pages),
                "first_page_content": pages[0].content if pages else "",
                "unsupported_styles": [
                    {"type": s.style_type, "severity": s.severity}
                    for s in converter.unsupported_styles
                ] if hasattr(converter, 'unsupported_styles') else [],
            }
            
            # Golden file comparison
            data_regression.check(result)
            
        finally:
            book.delete()

    def test_style_preservation(self, data_regression):
        """Verify inline styles (bold, italic, color) are preserved."""
        from apps.books.tests.fixtures.regression.metadata import load_metadata
        metadata = load_metadata("style-preservation")
        source_path = FIXTURES_DIR / "source" / metadata["source_pdf"]
        
        if not source_path.exists():
            pytest.skip(f"Source PDF not found: {source_path}")
        
        from apps.books.converters import PDFConverter
        from apps.books.models import Book
        
        converter = PDFConverter()
        book = Book(title="Test", author="Test")
        book.save()
        
        try:
            with open(source_path, 'rb') as f:
                pages = converter.convert(f, book)
            
            # Extract style tags from HTML content
            content = pages[0].content if pages else ""
            result = {
                "has_bold": "<strong>" in content or "<b>" in content,
                "has_italic": "<em>" in content or "<i>" in content,
                "has_underline": "<u>" in content,
                "has_color": 'color:' in content,
                "content_sample": content[:500] if content else "",
            }
            
            data_regression.check(result)
            
        finally:
            book.delete()

    def test_all_fixtures_have_metadata(self):
        """Verify every fixture has corresponding metadata."""
        from apps.books.tests.fixtures.regression.metadata import list_fixtures, load_metadata
        
        for fixture_id in list_fixtures():
            metadata = load_metadata(fixture_id)
            assert metadata.get("id") == fixture_id
            assert "expected_styles" in metadata or "expected_structure" in metadata
