"""Canonical list contract for PDF casting pipeline.

This module defines the stable, versioned schema for list structures
used by the PDF-to-draft casting pipeline. It provides:
- Versioned schema constants for contract evolution tracking
- Dataclass primitives for list blocks and items
- Normalization helpers for marker token handling
- Deterministic classification utilities

The contract is intentionally decoupled from HTML rendering concerns
to ensure stable semantics across parser and renderer evolution.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Literal, Optional


@dataclass
class StyleMetadata:
    """Optional style metadata for any block or item.
    
    Captures formatting properties extracted from PDF spans for
    faithful reproduction in rendered HTML.
    
    Attributes:
        is_bold: Text has bold weight
        is_italic: Text has italic/oblique style
        is_underline: Text has underline decoration
        is_strikeout: Text has strikethrough decoration
        color: CSS hex color (e.g., "#FF0000") or None for default
        align: Text alignment relative to container
        font_name: Original font name for diagnostics
        font_size: Original font size in points for diagnostics
    """
    is_bold: bool = False
    is_italic: bool = False
    is_underline: bool = False
    is_strikeout: bool = False
    color: Optional[str] = None
    align: Literal["left", "center", "right", "justify"] = "left"
    font_name: Optional[str] = None
    font_size: Optional[float] = None

# Schema versioning for contract evolution tracking
CAST_LIST_SCHEMA_VERSION = "cast-list-v1"
CAST_DOC_SCHEMA_VERSION = "cast-doc-v1"  # Extended schema with paragraph blocks

# Type literals for list classification
ListType = Literal["ordered", "unordered"]
LineKind = Literal["ordered", "unordered", "continuation", "paragraph"]
MarkerKind = Literal[
    "decimal",
    "alpha-lower",
    "alpha-upper",
    "roman-lower",
    "roman-upper",
    "symbol",
    "unknown",
]

# Unicode bullet symbol normalization table
# Maps common bullet variants to canonical symbols
BULLET_SYMBOLS = {
    # Standard bullets
    "\u2022": "bullet",  # •
    "\u2023": "bullet",  # ‣
    "\u2043": "bullet",  # ⁃
    "\u2219": "bullet",  # ∙
    # Hyphens and dashes
    "\u002d": "dash",  # -
    "\u2010": "dash",  # ‐
    "\u2011": "dash",  # ‑
    "\u2012": "dash",  # ‒
    "\u2013": "dash",  # –
    "\u2014": "dash",  # —
    "\u002a": "bullet",  # * (asterisk treated as bullet)
    # Hollow bullets
    "\u25e6": "hollow",  # ◦
    "\u25cb": "hollow",  # ○
    "\u25cf": "bullet",  # ●
    # Arrows
    "\u2192": "arrow",  # →
    "\u21d2": "arrow",  # ⇒
    # Checkmarks
    "\u2713": "check",  # ✓
    "\u2714": "check",  # ✔
    # Squares
    "\u25a0": "square",  # ■
    "\u25a1": "square",  # □
}

# Roman numeral patterns (limited to reasonable ranges)
ROMAN_PATTERN = re.compile(
    r"^[IVXLCDMivxlcdm]{1,10}$", re.IGNORECASE
)

# Alpha pattern (single letter)
ALPHA_PATTERN = re.compile(r"^[a-zA-Z]$")

# Decimal pattern (digits)
DECIMAL_PATTERN = re.compile(r"^(\d+)$")


@dataclass
class ListItem:
    """A single item within a list block.
    
    Attributes:
        text_html: The item content as sanitized HTML
        depth: Nesting depth (0 = top level)
        list_type: Whether this belongs to an ordered or unordered list
        marker_raw: The raw marker text as extracted from PDF (e.g., "3.", "•")
        marker_kind: Classification of the marker type
        marker_value: Parsed numeric value for ordered lists (e.g., 3 for "3.")
        symbol: Canonical symbol name for unordered lists (e.g., "bullet", "dash")
        source_x0: Original x-coordinate from PDF extraction
        source_y0: Original y-coordinate from PDF extraction
    """
    text_html: str
    depth: int
    list_type: ListType
    marker_raw: str
    marker_kind: MarkerKind
    marker_value: Optional[int] = None
    symbol: Optional[str] = None
    source_x0: float = 0.0
    source_y0: float = 0.0


@dataclass
class ListBlock:
    """A contiguous block of list items with consistent type and depth.
    
    List blocks are separated when:
    - List type changes (ordered -> unordered or vice versa)
    - Depth changes significantly (new nesting level)
    - Non-list content intervenes
    
    Attributes:
        block_id: Unique identifier for this block
        list_type: ordered or unordered
        depth_base: Base nesting depth for this block
        items: Ordered list of items in this block
        start_value: Starting value for ordered lists (default 1)
    """
    block_id: str
    list_type: ListType
    depth_base: int
    items: list[ListItem] = field(default_factory=list)
    start_value: int = 1

    def add_item(self, item: ListItem) -> None:
        """Add an item to this block, updating start_value if needed."""
        self.items.append(item)
        # Update start_value based on first ordered item
        if self.list_type == "ordered" and item.marker_value is not None:
            if len(self.items) == 1:
                self.start_value = item.marker_value


@dataclass
class ParagraphBlock:
    """Non-list paragraph content with optional heading semantics.
    
    Represents paragraphs, headings, and other block-level content
    that doesn't fit list structure. Carries style metadata for
    faithful reproduction of source formatting.
    
    Attributes:
        block_id: Unique identifier for this block
        tag: HTML tag semantic (p, h1-h6)
        text_html: Content as sanitized HTML with inline emphasis
        style: Style metadata for this block
        source_x0: Original x-coordinate from PDF extraction
        source_y0: Original y-coordinate from PDF extraction
        margin_bottom: Bottom margin in pixels for paragraph spacing
    """
    block_id: str
    tag: Literal["p", "h1", "h2", "h3", "h4", "h5", "h6"]
    text_html: str
    style: StyleMetadata = field(default_factory=StyleMetadata)
    source_x0: float = 0.0
    source_y0: float = 0.0
    margin_bottom: int = 0


@dataclass
class UnsupportedStyle:
    """Tracks style features that couldn't be fully preserved.
    
    Used for diagnostic reporting in preview mode to alert users
    about formatting loss during PDF conversion.
    
    Attributes:
        style_type: Category of unsupported style
        page: Page number where issue occurs (if applicable)
        description: Human-readable explanation
        severity: warning (cosmetic) or critical (structural)
        location_hint: Optional text snippet or coordinates
    """
    style_type: Literal[
        'heading',      # Heading level ambiguity
        'list',         # List type or nesting issue
        'table',        # Tables not supported
        'image',        # Images not extracted
        'font',         # Font not available
        'color',        # Color fidelity loss
        'alignment',    # Alignment ambiguity
        'spacing',      # Spacing approximation
        'border',       # Borders not supported
        'hyperlink',    # Links not extracted
    ]
    page: Optional[int] = None
    description: str = ""
    severity: Literal['warning', 'critical'] = 'warning'
    location_hint: Optional[str] = None


@dataclass
class CastDocument:
    """Top-level container for cast output.
    
    This represents the canonical intermediate representation between
    PDF extraction and HTML rendering. Supports mixed list and paragraph
    content with schema versioning for compatibility checking.
    
    Attributes:
        schema_version: Contract version for compatibility checking
        blocks: Mixed list of ListBlock and ParagraphBlock instances
        unsupported_styles: List of style features that couldn't be preserved
        processing_warnings: General processing warnings
    """
    schema_version: str = CAST_DOC_SCHEMA_VERSION
    blocks: list = field(default_factory=list)
    unsupported_styles: list = field(default_factory=list)  # List[UnsupportedStyle]
    processing_warnings: list = field(default_factory=list)  # List[str]


def normalize_text(text: str) -> str:
    """Normalize text for consistent marker parsing.
    
    Applies NFKC normalization to handle compatibility characters
    and full-width variants commonly found in PDFs.
    """
    return unicodedata.normalize("NFKC", text)


def extract_marker(text: str) -> tuple[str, str]:
    """Extract potential list marker from line start.
    
    Returns:
        Tuple of (marker_text, remaining_text)
    """
    normalized = normalize_text(text)
    
    # Pattern: marker followed by delimiter (., ), :, or space)
    # Examples: "1.", "a)", "I.", "• ", "- "
    marker_pattern = re.compile(r"^\s*([^\s.):]+)[.):]?\s+(.*)$", re.DOTALL)
    match = marker_pattern.match(normalized)
    
    if match:
        return match.group(1), match.group(2)
    
    # Check for bullet symbols without delimiter
    stripped = normalized.lstrip()
    if stripped:
        first_char = stripped[0]
        if first_char in BULLET_SYMBOLS:
            return first_char, stripped[1:].lstrip()
    
    return "", normalized.strip()


def classify_marker_kind(marker: str) -> MarkerKind:
    """Classify a marker string into its kind.
    
    Uses fixed precedence: decimal -> roman -> alpha -> symbol -> unknown
    """
    if not marker:
        return "unknown"
    
    # Check for symbol first (fast path for bullets)
    if marker in BULLET_SYMBOLS:
        return "symbol"
    
    # Check for decimal (digits only)
    if DECIMAL_PATTERN.match(marker):
        return "decimal"
    
    # Check for roman numerals (case insensitive)
    if ROMAN_PATTERN.match(marker) and len(marker) <= 10:
        # Additional validation: must contain at least one roman letter
        roman_letters = set("ivxlcdmIVXLCDM")
        if any(c in roman_letters for c in marker):
            if marker.isupper():
                return "roman-upper"
            return "roman-lower"
    
    # Check for alpha (single letter)
    if ALPHA_PATTERN.match(marker) and len(marker) == 1:
        if marker.isupper():
            return "alpha-upper"
        return "alpha-lower"
    
    return "unknown"


def parse_marker_value(marker: str, kind: MarkerKind) -> Optional[int]:
    """Parse numeric value from ordered list marker.
    
    Returns None for unordered or unparseable markers.
    """
    if kind == "decimal":
        try:
            return int(marker)
        except ValueError:
            return None
    
    if kind in ("alpha-lower", "alpha-upper"):
        # Convert letter to position (a=1, b=2, etc.)
        letter = marker.lower()
        if len(letter) == 1 and letter.isalpha():
            return ord(letter) - ord("a") + 1
        return None
    
    if kind in ("roman-lower", "roman-upper"):
        return _roman_to_int(marker)
    
    return None


def _roman_to_int(roman: str) -> Optional[int]:
    """Convert roman numeral to integer.
    
    Returns None if conversion fails.
    """
    roman = roman.upper()
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    
    try:
        total = 0
        prev_value = 0
        for char in reversed(roman):
            value = values.get(char, 0)
            if value < prev_value:
                total -= value
            else:
                total += value
            prev_value = value
        return total if total > 0 else None
    except Exception:
        return None


def get_symbol_name(marker: str) -> Optional[str]:
    """Get canonical symbol name for bullet marker."""
    return BULLET_SYMBOLS.get(marker)


def is_list_marker(marker: str, kind: MarkerKind) -> bool:
    """Determine if a marker indicates a list item.
    
    Returns True for known ordered/unordered markers, False for unknown.
    """
    return kind != "unknown"
