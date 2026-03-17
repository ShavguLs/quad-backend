"""Style inference and normalization for PDF casting pipeline.

This module provides utilities for extracting style metadata from PDF spans
and normalizing them into the casting contract. Handles:
- Heading level detection from font size ratios
- Paragraph break detection from vertical gaps
- Text alignment detection from geometry
- Color extraction and normalization
- Emphasis detection (bold, italic, underline, strikeout)
"""

from __future__ import annotations

import html
import re
from typing import List, Optional, Tuple

from .casting_contract import ParagraphBlock, StyleMetadata

# PyMuPDF font flag constants
TEXT_FONT_BOLD = 16  # bit 4
TEXT_FONT_ITALIC = 2  # bit 1

# Character flag constants (from PyMuPDF docs)
CHAR_FLAG_UNDERLINE = 2  # bit 1
CHAR_FLAG_STRIKEOUT = 1  # bit 0

# Alignment detection tolerance (4% of page width or 24pt minimum)
ALIGN_TOLERANCE_RATIO = 0.04
ALIGN_TOLERANCE_MIN = 24.0

# Paragraph break detection thresholds
# More sensitive to capture subtle spacing changes in PDFs
PARA_BREAK_LINE_HEIGHT_MULT = 1.3  # Was 1.5 - more sensitive
PARA_BREAK_PUNCT_MULT = 0.6  # Was 0.8 - detect smaller gaps after punctuation

# Heading detection thresholds (font size ratios relative to body)
# More aggressive thresholds to catch subtle headings
HEADING_RATIOS = [
    (2.2, 1),  # ratio >= 2.2 -> H1 (was 2.5)
    (1.75, 2),  # ratio >= 1.75 -> H2 (was 2.0)
    (1.45, 3),  # ratio >= 1.45 -> H3 (was 1.6)
    (1.25, 4),  # ratio >= 1.25 -> H4 (was 1.4)
    (1.12, 5), # ratio >= 1.12 -> H5 (was 1.25)
    (1.05, 6),  # ratio >= 1.05 -> H6 (was 1.1)
]

# Sentence-ending punctuation for paragraph break detection
SENTENCE_END_PUNCT = {'.', '!', '?', '。', '！', '？', '"', "'", '」', '】', ')'}


def extract_span_metadata(span: dict) -> dict:
    """Extract all fidelity-related metadata from a PyMuPDF span.
    
    Args:
        span: PyMuPDF span dictionary with text, font, flags, etc.
    
    Returns:
        Normalized metadata dict with emphasis, color, and font info.
    """
    font_name = (span.get("font") or "").lower()
    flags = int(span.get("flags") or 0)
    char_flags = int(span.get("char_flags") or 0)
    
    # Emphasis detection via flags and font name heuristics
    is_bold = (
        "bold" in font_name
        or "black" in font_name
        or "heavy" in font_name
        or "semibold" in font_name
        or "demibold" in font_name
        or bool(flags & TEXT_FONT_BOLD)
    )
    
    is_italic = (
        "italic" in font_name
        or "oblique" in font_name
        or bool(flags & TEXT_FONT_ITALIC)
    )
    
    is_underline = bool(char_flags & CHAR_FLAG_UNDERLINE)
    is_strikeout = bool(char_flags & CHAR_FLAG_STRIKEOUT)
    
    # Color extraction (sRGB int to CSS hex)
    color_hex = extract_color(span.get("color"))
    
    return {
        "text": span.get("text", ""),
        "font_name": span.get("font"),
        "font_size": float(span.get("size") or 0),
        "is_bold": is_bold,
        "is_italic": is_italic,
        "is_underline": is_underline,
        "is_strikeout": is_strikeout,
        "color": color_hex,
        "bbox": span.get("bbox"),
        "flags": flags,
        "char_flags": char_flags,
    }


def extract_color(color_int: Optional[int]) -> Optional[str]:
    """Extract color from span and return as CSS hex string.
    
    PyMuPDF color is sRGB integer: 0xRRGGBB
    Returns: "#RRGGBB" or None if black (default) or missing.
    
    Args:
        color_int: sRGB color integer from PyMuPDF span
    
    Returns:
        CSS hex color string or None for default/black.
    """
    if color_int is None:
        return None
    
    # Skip black (default text color)
    if color_int == 0:
        return None
    
    # Convert to CSS hex
    return f"#{color_int:06X}"


def detect_heading_level(
    font_size: float,
    body_size: float,
    is_bold: bool = False,
    font_name: str = ""
) -> int:
    """Map font size to heading level H1-H6 (0 = not a heading).
    
    Uses logarithmic scale for better distribution across H1-H6.
    Bold/heavy fonts get priority for higher levels.
    
    Args:
        font_size: The font size to classify
        body_size: Reference body font size for the document
        is_bold: Whether the text has bold weight
        font_name: Original font name for additional heuristics
    
    Returns:
        Heading level 1-6, or 0 for body text.
    """
    if body_size <= 0 or font_size <= body_size * 1.05:
        return 0  # Not a heading (body text or smaller)
    
    ratio = font_size / body_size
    
    # Weight boost for bold/heavy fonts
    weight_boost = 0.15 if is_bold else 0.0
    if "heavy" in font_name.lower() or "black" in font_name.lower():
        weight_boost = 0.2
    
    adjusted_ratio = ratio + weight_boost
    
    # Find matching heading level
    for threshold, level in HEADING_RATIOS:
        if adjusted_ratio >= threshold:
            return level
    
    return 0


def is_paragraph_break(
    line_gap: float,
    body_size: float,
    prev_line_ends_with_punct: bool = False,
    indentation_change: float = 0.0
) -> bool:
    """Determine if vertical gap indicates paragraph break vs soft line break.
    
    A paragraph break occurs when:
    - Gap is > 1.5x line height (body_size * 1.5)
    - Previous line ends with sentence-ending punctuation and gap is significant
    - Significant indentation change combined with vertical gap
    
    Args:
        line_gap: Vertical distance between lines in points
        body_size: Reference body font size
        prev_line_ends_with_punct: Whether previous line ends with .!? etc.
        indentation_change: Change in x0 position from previous line
    
    Returns:
        True if this gap indicates a paragraph break.
    """
    if body_size <= 0:
        return False
    
    line_height = body_size * 1.2  # Approximate line height
    
    # Significant gap threshold
    if line_gap > line_height * PARA_BREAK_LINE_HEIGHT_MULT:
        return True
    
    # Punctuation-based heuristic with moderate gap
    if prev_line_ends_with_punct and line_gap > line_height * PARA_BREAK_PUNCT_MULT:
        return True
    
    # Indentation change combined with gap (indicates new paragraph)
    if abs(indentation_change) > body_size and line_gap > line_height * 0.5:
        return True
    
    return False


def detect_alignment(
    line_x0: float,
    line_x1: float,
    page_width: float,
    body_left_margin: float = 0.0,
    body_right_margin: float = 0.0
) -> str:
    """Detect text alignment from line geometry.
    
    Args:
        line_x0: Left edge of line bbox
        line_x1: Right edge of line bbox
        page_width: Total page width
        body_left_margin: Typical left margin for body text
        body_right_margin: Typical right margin for body text
    
    Returns:
        One of: "left", "center", "right", "justify"
    """
    if page_width <= 0:
        return "left"
    
    line_width = max(0.0, line_x1 - line_x0)
    if line_width <= 0:
        return "left"
    
    # Normalize content area bounds.
    content_left = max(0.0, float(body_left_margin or 0.0))
    content_right = page_width - max(0.0, float(body_right_margin or 0.0))
    if content_right <= content_left:
        content_left = 0.0
        content_right = page_width

    expected_width = content_right - content_left
    if expected_width <= 0:
        expected_width = page_width

    # Distances from the inferred body text box.
    left_distance = max(0.0, line_x0 - content_left)
    right_distance = max(0.0, content_right - line_x1)

    center_tolerance = max(ALIGN_TOLERANCE_MIN, page_width * ALIGN_TOLERANCE_RATIO)

    # Justify: very wide line anchored on both body margins.
    if (
        expected_width > 0
        and line_width >= expected_width * 0.92
        and left_distance <= center_tolerance
        and right_distance <= center_tolerance
    ):
        return "justify"

    # Right: near right body edge with visible left indentation.
    if right_distance <= center_tolerance and left_distance > max(20.0, expected_width * 0.1):
        return "right"

    # Center: both sides similarly indented from body margins.
    # This avoids classifying normal left-aligned text in centered columns as centered.
    center_margin_min = max(8.0, expected_width * 0.04)
    if (
        line_width <= expected_width * 0.85
        and left_distance >= center_margin_min
        and right_distance >= center_margin_min
        and abs(left_distance - right_distance) <= center_tolerance
    ):
        return "center"

    return "left"


def line_ends_with_sentence_punct(text: str) -> bool:
    """Check if text ends with sentence-ending punctuation.
    
    Args:
        text: The text to check
    
    Returns:
        True if text ends with sentence-ending punctuation.
    """
    stripped = text.rstrip()
    if not stripped:
        return False
    return stripped[-1] in SENTENCE_END_PUNCT


def render_styled_span(text: str, metadata: dict) -> str:
    """Render text with inline emphasis tags based on metadata.
    
    Args:
        text: The text content
        metadata: Dict with is_bold, is_italic, is_underline, is_strikeout, color
    
    Returns:
        HTML string with appropriate emphasis tags.
    """
    escaped = html.escape(text)
    
    # Apply emphasis tags (innermost first)
    result = escaped
    
    if metadata.get("is_strikeout"):
        result = f"<s>{result}</s>"
    if metadata.get("is_underline"):
        result = f"<u>{result}</u>"
    if metadata.get("is_italic"):
        result = f"<em>{result}</em>"
    if metadata.get("is_bold"):
        result = f"<strong>{result}</strong>"
    
    # Wrap with color span if needed
    color = metadata.get("color")
    if color:
        result = f'<span style="color:{color}">{result}</span>'
    
    return result


def normalize_spans_to_paragraphs(
    lines: List[dict],
    body_size: float,
    page_width: float,
    body_left_margin: float = 0.0,
    body_right_margin: float = 0.0,
) -> List[ParagraphBlock]:
    """Normalize extracted lines into paragraph blocks with style metadata.
    
    Groups consecutive lines into paragraphs based on paragraph break detection,
    assigns heading levels, detects alignment, and preserves emphasis.
    
    Args:
        lines: List of line dicts from _collect_text_lines (each with text, html, size, x0, x1, y0, y1)
        body_size: Reference body font size
        page_width: Total page width for alignment detection
        body_left_margin: Typical left margin for body text
        body_right_margin: Typical right margin for body text
    
    Returns:
        List of ParagraphBlock instances representing the normalized content.
    """
    if not lines:
        return []
    
    paragraphs = []
    current_lines = []
    current_metadata = []
    prev_line = None
    
    for i, line in enumerate(lines):
        # Determine if this is a paragraph break from previous line
        is_new_para = False
        if prev_line is not None:
            gap = max(0.0, line["y0"] - prev_line["y1"])
            prev_text = prev_line.get("text", "")
            ends_with_punct = line_ends_with_sentence_punct(prev_text)
            indent_change = line["x0"] - prev_line["x0"]
            
            is_new_para = is_paragraph_break(gap, body_size, ends_with_punct, indent_change)
        
        if is_new_para and current_lines:
            # Flush current paragraph
            para = _create_paragraph_block(
                current_lines, current_metadata, body_size, page_width,
                body_left_margin, body_right_margin, len(paragraphs)
            )
            paragraphs.append(para)
            current_lines = []
            current_metadata = []
        
        current_lines.append(line)
        prev_line = line
    
    # Flush final paragraph
    if current_lines:
        para = _create_paragraph_block(
            current_lines, current_metadata, body_size, page_width,
            body_left_margin, body_right_margin, len(paragraphs)
        )
        paragraphs.append(para)
    
    return paragraphs


def _create_paragraph_block(
    lines: List[dict],
    metadata: List[dict],
    body_size: float,
    page_width: float,
    body_left_margin: float,
    body_right_margin: float,
    block_index: int,
) -> ParagraphBlock:
    """Create a ParagraphBlock from grouped lines.
    
    Args:
        lines: List of line dicts in this paragraph
        metadata: List of metadata dicts (currently unused, for future span-level metadata)
        body_size: Reference body font size
        page_width: Total page width
        body_left_margin: Left margin for body text
        body_right_margin: Right margin for body text
        block_index: Index for generating block_id
    
    Returns:
        Populated ParagraphBlock instance.
    """
    if not lines:
        return ParagraphBlock(
            block_id=f"para-{block_index}",
            tag="p",
            text_html="",
        )
    
    # Combine line HTML with soft breaks (space) or hard breaks (br)
    html_parts = []
    for i, line in enumerate(lines):
        if i > 0:
            # Check if previous line ends with hyphen (indicates word break)
            prev_text = lines[i-1].get("text", "")
            if prev_text.rstrip().endswith("-"):
                html_parts.append("")  # Hyphenated word continuation
            else:
                html_parts.append(" ")  # Normal word break
        html_parts.append(line.get("html", html.escape(line.get("text", ""))))
    
    combined_html = "".join(html_parts)
    
    # Determine heading level from first line's font size
    first_line = lines[0]
    font_size = first_line.get("size", body_size)
    
    # Check if any line has bold/heavy characteristics
    is_bold = "strong" in combined_html or "b>" in combined_html
    font_name = ""  # We don't have per-line font names in current structure
    
    heading_level = detect_heading_level(font_size, body_size, is_bold, font_name)
    tag = f"h{heading_level}" if heading_level > 0 else "p"
    
    # Detect alignment from majority of lines
    alignments = []
    for line in lines:
        align = detect_alignment(
            line["x0"], line["x1"], page_width,
            body_left_margin, body_right_margin
        )
        alignments.append(align)
    
    # Majority vote for alignment
    alignment = max(set(alignments), key=alignments.count) if alignments else "left"
    
    # Extract color from first span with non-default color (if any)
    # Note: This is a heuristic - color extraction happens at span level in pdf_converter
    color = None  # Will be populated by caller if span-level color exists
    
    # Calculate margin bottom from gap to next content (if known)
    # This will be set by the caller based on following content
    margin_bottom = 0
    
    # Create style metadata
    style = StyleMetadata(
        is_bold=is_bold,
        align=alignment,  # type: ignore
        color=color,
        font_size=font_size if font_size != body_size else None,
    )
    
    return ParagraphBlock(
        block_id=f"para-{block_index}",
        tag=tag,  # type: ignore
        text_html=combined_html,
        style=style,
        source_x0=first_line.get("x0", 0.0),
        source_y0=first_line.get("y0", 0.0),
        margin_bottom=margin_bottom,
    )
