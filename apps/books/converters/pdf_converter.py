"""PDF to text and HTML content converter using PyMuPDF."""

import html
import logging
from collections import Counter
from statistics import median
from typing import List, Optional

import pymupdf

from apps.books.models import Book
from .base import BaseConverter, ConversionError
from .casting_contract import UnsupportedStyle
from .list_inference import infer_list_blocks
from .html_render import render_cast_blocks_to_html
from .style_inference import extract_span_metadata, render_styled_span, normalize_spans_to_paragraphs
from .text_extractor import extract_text_from_pdf

logger = logging.getLogger(__name__)


class PDFConverter(BaseConverter):
    """Convert PDF files to text and HTML content extraction."""

    DPI = 150  # Higher DPI for better quality
    FORMAT = "jpeg"
    JPEG_QUALITY = 85  # Higher quality
    
    # Line height multipliers to match PDF visual appearance
    LINE_HEIGHT_MULTIPLIER = 1.35  # Base line height for paragraphs
    HEADING_LINE_HEIGHT = 1.15  # Tighter line height for headings

    def __init__(self):
        """Initialize PDF converter with unsupported styles tracking."""
        super().__init__()
        self._current_page = 0
        self._max_expensive_diagnostic_pages = 80
        self._table_warning_emitted = False
        self._border_warning_emitted = False

    def supports(self, mime_type: str) -> bool:
        """Check if this converter supports the MIME type."""
        return mime_type in ['application/pdf', 'application/x-pdf']
    
    def convert(self, file_obj, book: Book) -> List[dict]:
        """
        Convert PDF to content data for BookContent creation.

        Returns list of dicts with page content data:
        {
            'page_number': int,
            'html_content': str,
            'text_content': str,
            'image_data': bytes (optional),
        }
        
        Note: This converter extracts content but does NOT create BookContent
        instances. The caller (e.g., ExtractionToContentService) is responsible
        for creating BookContent from the extracted data.
        """
        # Reset unsupported styles tracking for this conversion
        self.unsupported_styles = []
        self._table_warning_emitted = False
        self._border_warning_emitted = False

        try:
            if hasattr(file_obj, 'read'):
                content = file_obj.read()
            else:
                content = file_obj

            try:
                doc = pymupdf.open(stream=content, filetype="pdf")
            except Exception as e:
                logger.error(f"Failed to open PDF: {e}")
                raise ConversionError(f"Invalid or corrupted PDF file: {e}")

            pages = []

            try:
                total_pages = len(doc)
                self._max_expensive_diagnostic_pages = 80 if total_pages <= 120 else 30
                logger.info(f"Converting PDF with {total_pages} pages for book {book.id}")

                # Use simple text extractor for better reliability
                try:
                    text_contents = extract_text_from_pdf(content)
                    logger.info(f"Extracted text from {len(text_contents)} pages using pdfplumber")
                except Exception as e:
                    logger.warning(f"Simple text extraction failed, falling back: {e}")
                    text_contents = []

                for page_num in range(total_pages):
                    self._current_page = page_num + 1
                    page = doc.load_page(page_num)
                    page_text_dict = page.get_text("dict")
                    page_rect = getattr(page, "rect", None)
                    page_width = float(getattr(page_rect, "width", 0) or page_text_dict.get("width") or 595.0)
                    page_height = float(getattr(page_rect, "height", 0) or page_text_dict.get("height") or 842.0)

                    # Detect unsupported features on this page
                    self._detect_unsupported_features(page, self._current_page, text_dict=page_text_dict)

                    # Render page image (for preview/thumbnail)
                    pix = page.get_pixmap(dpi=self.DPI)
                    try:
                        img_data = pix.tobytes(self.FORMAT, jpg_quality=self.JPEG_QUALITY)
                    except TypeError:
                        img_data = pix.tobytes(self.FORMAT)

                    # Use extracted text if available, otherwise fall back to complex extraction
                    if page_num < len(text_contents) and text_contents[page_num]:
                        html_content = text_contents[page_num]
                    else:
                        html_content = self._extract_page_html(page, text_dict=page_text_dict)

                    # Extract plain text for search/indexing
                    text_content = page.get_text("text") if page else ""

                    # Create content data dict (no BookPage creation)
                    page_data = {
                        'page_number': page_num + 1,
                        'html_content': html_content,
                        'text_content': text_content,
                        'image_data': img_data,
                        'page_width': page_width,
                        'page_height': page_height,
                    }
                    pages.append(page_data)

                    pix = None
                    page = None

                logger.info(f"Successfully converted {len(pages)} pages for book {book.id}")
                if self.unsupported_styles:
                    logger.info(f"Detected {len(self.unsupported_styles)} unsupported style features")

            finally:
                doc.close()

        except ConversionError:
            raise
        except Exception as e:
            logger.error(f"Unexpected error during PDF conversion: {e}")
            raise ConversionError(f"PDF conversion failed: {e}")

        return pages

    def _detect_unsupported_features(self, page, page_num: int, text_dict: Optional[dict] = None) -> None:
        """Detect unsupported features on a PDF page and add to unsupported_styles.

        Detection points:
        1. Image blocks (type != 0)
        2. Tables (detected via complex grid layouts)
        3. Hyperlinks (uri annotations)
        4. Border decorations (vector graphics/drawings)
        """
        try:
            # Check for image blocks and table-like structures
            resolved_text_dict = text_dict if text_dict is not None else page.get_text("dict")
            blocks = resolved_text_dict.get("blocks", [])
            for block in blocks:
                block_type = block.get("type", 0)

                if block_type == 1:
                    # Image block
                    self.unsupported_styles.append(UnsupportedStyle(
                        style_type="image",
                        page=page_num,
                        description=f"Image detected on page {page_num} - will not be extracted",
                        severity="critical",
                        location_hint=f"Image block at coordinates {block.get('bbox', [])}"
                    ))

            # Check for hyperlinks
            try:
                links = page.get_links()
                if links:
                    for link in links:
                        if link.get("uri"):
                            self.unsupported_styles.append(UnsupportedStyle(
                                style_type="hyperlink",
                                page=page_num,
                                description=f"Hyperlink detected on page {page_num} - will not be preserved",
                                severity="warning",
                                location_hint=f"Link to: {link.get('uri', 'unknown')[:50]}"
                            ))
                            # Only report first hyperlink per page to avoid spam
                            break
            except Exception:
                pass

            # Check for vector graphics (potential borders/decoration)
            # This can be expensive on long PDFs, so cap deep scans.
            if (not self._border_warning_emitted) and page_num <= self._max_expensive_diagnostic_pages:
                try:
                    drawings = page.get_drawings()
                    if drawings:
                        # Check if drawings look like borders (lines/boxes)
                        border_like = 0
                        for drawing in drawings:
                            items = drawing.get("items", [])
                            for item in items:
                                if item[0] in ("l", "re"):  # line or rectangle
                                    border_like += 1

                        if border_like > 3:  # Multiple lines suggest borders
                            self.unsupported_styles.append(UnsupportedStyle(
                                style_type="border",
                                page=page_num,
                                description=f"Borders/decorative lines detected on page {page_num} - will not be preserved",
                                severity="warning",
                                location_hint=f"{len(drawings)} drawing elements detected"
                            ))
                            self._border_warning_emitted = True
                except Exception:
                    pass

            # Check for table-like structures
            # find_tables() is one of the hottest paths on large PDFs.
            # We limit scans to early pages and stop after first detection.
            if (not self._table_warning_emitted) and page_num <= self._max_expensive_diagnostic_pages:
                try:
                    tables = page.find_tables()
                    if tables and len(tables.tables) > 0:
                        self.unsupported_styles.append(UnsupportedStyle(
                            style_type="table",
                            page=page_num,
                            description=f"Table detected on page {page_num} - will be converted to plain text",
                            severity="critical",
                            location_hint=f"{len(tables.tables)} table(s) detected"
                        ))
                        self._table_warning_emitted = True
                except Exception:
                    # Table detection may not be available in all PyMuPDF versions
                    pass

        except Exception as e:
            logger.debug(f"Error detecting unsupported features on page {page_num}: {e}")
    
    def _extract_page_html(self, page, text_dict: Optional[dict] = None) -> str:
        """Extract text and convert to styled HTML that keeps PDF structure."""
        try:
            resolved_text_dict = text_dict if text_dict is not None else page.get_text("dict")
            lines = self._collect_text_lines(resolved_text_dict)

            if not lines:
                return "<p>Start writing here...</p>"

            body_size = self._body_font_size([line["size"] for line in lines])
            page_width = self._resolve_page_width(page, resolved_text_dict)

            # Try list inference first to detect list structures
            cast_document = infer_list_blocks(lines)

            # If we have list blocks, render them via the contract pipeline
            if cast_document.blocks:
                # Check if all content is in lists or if we need mixed rendering
                list_lines_count = sum(len(block.items) for block in cast_document.blocks)

                if list_lines_count >= len(lines) * 0.5:
                    # Majority list content - use contract rendering
                    list_html = render_cast_blocks_to_html(cast_document, include_metadata=True)
                    if list_html:
                        return list_html

            # Fall back to paragraph/heading rendering for non-list content
            # Use paragraph normalization for better structure detection

            # Estimate body margins from line positions
            if lines:
                x0_values = [line["x0"] for line in lines]
                body_left_margin = min(x0_values) if x0_values else 0.0
                # Estimate right margin from lines that span full width
                full_width_lines = [line for line in lines
                                   if (line["x1"] - line["x0"]) >= page_width * 0.7]
                if full_width_lines:
                    body_right_margin = page_width - max(line["x1"] for line in full_width_lines)
                else:
                    body_right_margin = body_left_margin
            else:
                body_left_margin = 0.0
                body_right_margin = 0.0

            # Normalize lines into paragraph blocks
            paragraph_blocks = normalize_spans_to_paragraphs(
                lines, body_size, page_width, body_left_margin, body_right_margin
            )

            # Set margin_bottom based on gaps between paragraphs
            for i, block in enumerate(paragraph_blocks):
                if i + 1 < len(paragraph_blocks):
                    next_block = paragraph_blocks[i + 1]
                    gap = next_block.source_y0 - (block.source_y0 + body_size * 1.2)
                    block.margin_bottom = max(4, min(24, int(gap * 0.6)))
                else:
                    block.margin_bottom = max(4, int(body_size * 0.35))

            # Render paragraph blocks to HTML
            html_parts = []
            for block in paragraph_blocks:
                block_html = self._render_paragraph_block_to_html(block)
                if block_html:
                    html_parts.append(block_html)

            return "\n".join(html_parts) if html_parts else "<p>Start writing here...</p>"

        except Exception as e:
            logger.warning(f"Text extraction failed for page: {e}")
            return "<p>Start writing here...</p>"

    def _collect_text_lines(self, text_dict: dict) -> List[dict]:
        """Flatten PyMuPDF text blocks into ordered styled lines with metadata."""

        lines: List[dict] = []

        for block in text_dict.get("blocks", []):
            if block.get("type") != 0:
                continue

            for line in block.get("lines", []):
                spans = [span for span in line.get("spans", []) if span.get("text", "").strip()]
                if not spans:
                    continue

                span_html = [self._render_span(span) for span in spans]
                span_sizes = [float(span.get("size") or 0) for span in spans if span.get("size")]
                bboxes = [span.get("bbox", [0, 0, 0, 0]) for span in spans]
                y0 = min(bbox[1] for bbox in bboxes)
                y1 = max(bbox[3] for bbox in bboxes)

                raw_text = "".join(span.get("text", "") for span in spans).strip()
                if not raw_text:
                    continue

                # Extract metadata from first span for style inference
                # (In multi-span lines, we use the dominant style)
                first_span_meta = extract_span_metadata(spans[0]) if spans else {}

                lines.append(
                    {
                        "text": raw_text,
                        "html": "".join(span_html),
                        "size": median(span_sizes) if span_sizes else 12.0,
                        "x0": float(min(bbox[0] for bbox in bboxes)),
                        "x1": float(max(bbox[2] for bbox in bboxes)),
                        "y0": float(y0),
                        "y1": float(y1),
                        # Additional metadata for paragraph normalization
                        "is_bold": first_span_meta.get("is_bold", False),
                        "is_italic": first_span_meta.get("is_italic", False),
                        "color": first_span_meta.get("color"),
                        "font_name": first_span_meta.get("font_name"),
                    }
                )

        return lines

    def _render_span(self, span: dict) -> str:
        """Render a span to HTML while preserving emphasis, color, and decorations."""
        metadata = extract_span_metadata(span)
        return render_styled_span(metadata["text"], metadata)

    def _line_tag(self, font_size: float, body_size: float) -> str:
        """Map relative font size to semantic HTML tags."""
        if body_size <= 0:
            return "p"

        ratio = font_size / body_size
        if ratio >= 1.7:
            return "h1"
        if ratio >= 1.45:
            return "h2"
        if ratio >= 1.18:
            return "h3"
        return "p"

    def _line_margin(self, line: dict, next_line: Optional[dict], body_size: float) -> int:
        """Derive margin from vertical distance between text lines."""
        default_margin = max(4, int(body_size * 0.35))
        if not next_line:
            return default_margin

        gap = max(0.0, float(next_line["y0"]) - float(line["y1"]))
        scaled_gap = gap * 0.6
        return max(2, min(24, int(round(scaled_gap))))

    def _body_font_size(self, sizes: List[float]) -> float:
        """Infer body font size by selecting most frequent rounded size."""
        if not sizes:
            return 12.0

        rounded_sizes = [round(float(size), 1) for size in sizes if size > 0]
        if not rounded_sizes:
            return 12.0

        counts = Counter(rounded_sizes)
        return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]

    def _resolve_page_width(self, page, text_dict: dict) -> float:
        """Resolve page width for alignment detection."""
        width = text_dict.get("width")
        if width:
            return float(width)

        rect = getattr(page, "rect", None)
        if rect is not None and getattr(rect, "width", None):
            return float(rect.width)

        return 595.0

    def _line_alignment(self, line: dict, page_width: float) -> str:
        """Estimate alignment from line horizontal position."""
        if page_width <= 0:
            return "left"

        line_width = max(0.0, line["x1"] - line["x0"])
        if line_width <= 0:
            return "left"

        page_center = page_width / 2.0
        line_center = (line["x0"] + line["x1"]) / 2.0
        center_tolerance = max(24.0, page_width * 0.04)

        if abs(line_center - page_center) <= center_tolerance and line_width <= page_width * 0.8:
            return "center"

        return "left"

    def _render_paragraph_block_to_html(self, block) -> str:
        """Render a ParagraphBlock to styled HTML with precise PDF spacing.

        Args:
            block: ParagraphBlock instance from style_inference

        Returns:
            HTML string with appropriate tag and style attributes.
        """
        from .casting_contract import ParagraphBlock

        if not isinstance(block, ParagraphBlock):
            return ""

        tag = block.tag
        style = block.style

        # Build inline style attribute
        styles = []

        # Alignment
        if style.align != "left":
            styles.append(f"text-align:{style.align}")

        # Color
        if style.color:
            styles.append(f"color:{style.color}")

        # Font size - use actual PDF font size for better fidelity
        if style.font_size and style.font_size > 0:
            # Convert PDF points to CSS px (1pt ≈ 1.333px, but use direct mapping for fidelity)
            font_size_px = style.font_size * 1.0  # Keep close to PDF point size
            styles.append(f"font-size:{font_size_px:.1f}px")

        # Margin bottom for paragraph spacing - preserve PDF vertical gaps
        if block.margin_bottom > 0:
            # Scale margin to match visual appearance
            scaled_margin = block.margin_bottom * 1.0
            styles.append(f"margin-bottom:{scaled_margin:.1f}px")
        else:
            # Default small margin for paragraph separation
            styles.append("margin-bottom:0.5em")

        # Line height based on tag type
        if tag.startswith("h"):
            # Headings: tighter line height
            styles.append(f"line-height:{self.HEADING_LINE_HEIGHT}")
            styles.append("font-weight:700")
            styles.append("margin-top:0.3em")
        else:
            # Paragraphs: use PDF-like line height
            styles.append(f"line-height:{self.LINE_HEIGHT_MULTIPLIER}")

        style_attr = ";".join(styles)
        style_str = f' style="{style_attr}"' if styles else ""

        # Add class for heading levels and semantic markup
        class_str = f' class="{tag}"' if tag.startswith("h") else ""

        return f"<{tag}{class_str}{style_str}>{block.text_html}</{tag}>"
