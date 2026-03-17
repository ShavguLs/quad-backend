"""Text extraction with structure preservation using PyMuPDF.

Extracts text maintaining hierarchy:
document -> pages -> blocks -> lines -> spans

Integrates with layout analyzer for multi-column support
and formatter for styling preservation.
"""

import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from statistics import median

import pymupdf

from .layout_analyzer import LayoutAnalyzer, LayoutInfo
from .formatter import FormattingPreserver, FormattingMetadata

logger = logging.getLogger(__name__)


@dataclass
class ExtractedLine:
    """A line of text with formatting and position."""
    text: str
    html: str
    size: float
    x0: float
    y0: float
    x1: float
    y1: float
    is_bold: bool = False
    is_italic: bool = False
    color: Optional[str] = None
    font_name: Optional[str] = None
    spans: List[FormattingMetadata] = field(default_factory=list)


@dataclass
class ExtractedBlock:
    """A block of text (paragraph or heading)."""
    block_type: str  # 'paragraph', 'heading', 'list_item'
    lines: List[ExtractedLine] = field(default_factory=list)
    x0: float = 0.0
    y0: float = 0.0
    x1: float = 0.0
    y1: float = 0.0
    heading_level: int = 0  # 1-6 for headings, 0 for paragraphs
    alignment: str = "left"  # left | center | right


@dataclass
class ExtractedPage:
    """Extracted content from a single page."""
    page_number: int
    blocks: List[ExtractedBlock] = field(default_factory=list)
    layout: Optional[LayoutInfo] = None
    width: float = 0.0
    height: float = 0.0


class TextExtractor:
    """Extract structured text from PDF pages."""
    
    def __init__(self, layout_analyzer: Optional[LayoutAnalyzer] = None,
                 formatter: Optional[FormattingPreserver] = None):
        """
        Initialize text extractor.
        
        Args:
            layout_analyzer: Optional custom layout analyzer
            formatter: Optional custom formatting preserver
        """
        self.layout_analyzer = layout_analyzer or LayoutAnalyzer()
        self.formatter = formatter or FormattingPreserver()
    
    def extract_page(self, page: pymupdf.Page, 
                     page_number: int) -> ExtractedPage:
        """
        Extract structured text from a single page.
        
        Args:
            page: PyMuPDF page object
            page_number: 1-based page number
            
        Returns:
            ExtractedPage with blocks, lines, and formatting
        """
        # Get text with full structure
        text_dict = page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)
        
        # Analyze layout for multi-column detection
        layout = self.layout_analyzer.analyze(page)
        
        # Extract blocks with layout consideration
        blocks = self._extract_blocks(
            text_dict, layout, page_number
        )
        
        # Classify blocks as paragraphs or headings
        classified_blocks = self._classify_blocks(blocks, text_dict)
        
        return ExtractedPage(
            page_number=page_number,
            blocks=classified_blocks,
            layout=layout,
            width=text_dict.get("width", 0),
            height=text_dict.get("height", 0)
        )
    
    def _extract_blocks(self, text_dict: Dict[str, Any],
                       layout: LayoutInfo,
                       page_number: int) -> List[ExtractedBlock]:
        """Extract blocks from text dict, respecting reading order."""
        raw_blocks = [b for b in text_dict.get("blocks", []) 
                     if b.get("type") == 0]
        
        if not raw_blocks:
            return []
        
        # Sort by reading order if multi-column detected
        if layout.is_multi_column and layout.reading_order:
            raw_blocks = [raw_blocks[i] for i in layout.reading_order 
                         if i < len(raw_blocks)]
        else:
            # Default: sort top-to-bottom
            raw_blocks.sort(key=lambda b: b["bbox"][1])
        
        extracted_blocks = []
        
        for block in raw_blocks:
            lines = self._extract_lines(block)
            if not lines:
                continue

            bbox = block["bbox"]
            page_width = float(text_dict.get("width", 0) or 0)
            block_center_x = (bbox[0] + bbox[2]) / 2
            block_width = max(0.0, bbox[2] - bbox[0])
            page_center_x = page_width / 2 if page_width > 0 else block_center_x
            center_distance_ratio = abs(block_center_x - page_center_x) / page_width if page_width > 0 else 0
            width_ratio = (block_width / page_width) if page_width > 0 else 1.0

            if center_distance_ratio <= 0.08 and width_ratio <= 0.7:
                alignment = "center"
            elif block_center_x > page_center_x and center_distance_ratio > 0.2:
                alignment = "right"
            else:
                alignment = "left"

            extracted_blocks.append(ExtractedBlock(
                block_type="paragraph",  # Will be reclassified
                lines=lines,
                x0=bbox[0],
                y0=bbox[1],
                x1=bbox[2],
                y1=bbox[3],
                alignment=alignment,
            ))
        
        return extracted_blocks
    
    def _extract_lines(self, block: Dict[str, Any]) -> List[ExtractedLine]:
        """Extract lines from a block with span formatting."""
        lines = []
        
        for line in block.get("lines", []):
            spans = [s for s in line.get("spans", []) 
                    if s.get("text", "").strip()]
            
            if not spans:
                continue
            
            # Collect text and metadata from spans
            span_texts = []
            span_htmls = []
            span_sizes = []
            span_metadatas = []
            
            for span in spans:
                metadata = self.formatter.extract_metadata(span)
                span_metadatas.append(metadata)
                
                if metadata.text.strip():
                    span_texts.append(metadata.text)
                    span_htmls.append(self.formatter.render_to_html(metadata))
                    span_sizes.append(metadata.font_size or 12.0)
            
            if not span_texts:
                continue
            
            # Calculate bounding box from all spans
            bboxes = [s.get("bbox", [0, 0, 0, 0]) for s in spans]
            y0 = min(bbox[1] for bbox in bboxes)
            y1 = max(bbox[3] for bbox in bboxes)
            x0 = min(bbox[0] for bbox in bboxes)
            x1 = max(bbox[2] for bbox in bboxes)
            
            # Use first span's style as line style
            first_meta = span_metadatas[0] if span_metadatas else FormattingMetadata()
            if span_metadatas:
                total_chars = sum(len((meta.text or '').strip()) for meta in span_metadatas) or 1
                bold_chars = sum(
                    len((meta.text or '').strip())
                    for meta in span_metadatas
                    if meta.is_bold
                )
                italic_chars = sum(
                    len((meta.text or '').strip())
                    for meta in span_metadatas
                    if meta.is_italic
                )
                is_bold = (bold_chars / total_chars) >= 0.5
                is_italic = (italic_chars / total_chars) >= 0.5
            else:
                is_bold = first_meta.is_bold
                is_italic = first_meta.is_italic

            lines.append(ExtractedLine(
                text="".join(span_texts),
                html="".join(span_htmls),
                size=median(span_sizes) if span_sizes else 12.0,
                x0=x0,
                y0=y0,
                x1=x1,
                y1=y1,
                is_bold=is_bold,
                is_italic=is_italic,
                color=first_meta.color,
                font_name=first_meta.font_name,
                spans=span_metadatas
            ))
        
        return lines
    
    def _classify_blocks(self, blocks: List[ExtractedBlock],
                        text_dict: Dict[str, Any]) -> List[ExtractedBlock]:
        """
        Classify blocks as paragraphs or headings based on font size.
        
        Uses body font size as baseline; larger sizes are headings.
        """
        if not blocks:
            return blocks
        
        # Calculate body font size from most common size
        all_sizes = []
        for block in blocks:
            for line in block.lines:
                all_sizes.append(line.size)
        
        if not all_sizes:
            return blocks
        
        # Find most common size (rounded to 1 decimal)
        size_counts = {}
        for size in all_sizes:
            rounded = round(size, 1)
            size_counts[rounded] = size_counts.get(rounded, 0) + 1
        
        body_size = max(size_counts.items(), key=lambda x: x[1])[0]
        
        # Classify blocks
        for block in blocks:
            if not block.lines:
                continue

            # Use largest font size in block
            max_size = max(line.size for line in block.lines)
            ratio = max_size / body_size if body_size > 0 else 1.0
            text = " ".join(line.text.strip() for line in block.lines).strip()
            line_count = len(block.lines)
            char_count = len(text)
            alpha_chars = [ch for ch in text if ch.isalpha()]
            upper_ratio = (
                sum(1 for ch in alpha_chars if ch.isupper()) / len(alpha_chars)
                if alpha_chars else 0.0
            )
            mostly_bold = (
                sum(1 for line in block.lines if line.is_bold) / line_count >= 0.6
                if line_count else False
            )
            likely_heading_text = (
                char_count > 0
                and char_count <= 100
                and line_count <= 3
                and not text.endswith('.')
            )

            if ratio >= 1.7:
                block.block_type = "heading"
                block.heading_level = 1
            elif ratio >= 1.45:
                block.block_type = "heading"
                block.heading_level = 2
            elif ratio >= 1.18:
                block.block_type = "heading"
                block.heading_level = 3
            elif (
                likely_heading_text
                and (
                    (block.alignment == "center" and ratio >= 1.12)
                    or (mostly_bold and ratio >= 1.15)
                    or (upper_ratio >= 0.8 and ratio >= 1.12)
                )
            ):
                block.block_type = "heading"
                block.heading_level = 3
            else:
                block.block_type = "paragraph"
                block.heading_level = 0
        
        return blocks
    
    def extract(self, file_path: str) -> List[ExtractedPage]:
        """
        Extract structured text from entire PDF file.
        
        Args:
            file_path: Path to PDF file
            
        Returns:
            List of ExtractedPage, one per page
        """
        doc = pymupdf.open(file_path)
        pages = []
        
        try:
            for page_num in range(len(doc)):
                page = doc[page_num]
                extracted = self.extract_page(page, page_num + 1)
                pages.append(extracted)
        finally:
            doc.close()
        
        return pages


def extract_text_with_structure(file_path: str) -> List[ExtractedPage]:
    """
    Convenience function to extract text with default settings.
    
    Args:
        file_path: Path to PDF file
        
    Returns:
        List of ExtractedPage
    """
    extractor = TextExtractor()
    return extractor.extract(file_path)
