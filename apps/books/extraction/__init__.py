"""PDF text extraction pipeline with PyMuPDF.

This package provides structured text extraction from PDFs with:
- Document structure preservation (paragraphs, headings, lists)
- Multi-column layout detection and reading order correction
- Formatting metadata extraction (bold, italic, colors, fonts)
"""

from .engine import ExtractionEngine, ExtractionResult
from .text_extractor import TextExtractor
from .layout_analyzer import LayoutAnalyzer
from .formatter import FormattingPreserver
from .image_extractor import ImageExtractor, ExtractedImage

__all__ = [
    'ExtractionEngine',
    'ExtractionResult',
    'TextExtractor',
    'LayoutAnalyzer',
    'FormattingPreserver',
    'ImageExtractor',
    'ExtractedImage',
]
