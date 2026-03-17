"""Formatting preservation for PDF text spans.

Extracts and preserves:
- Font flags (bold, italic, superscript, monospace, serif)
- Colors (converted to CSS hex)
- Font sizes and names
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any


@dataclass
class FormattingMetadata:
    """Extracted formatting metadata for a text span."""
    text: str = ""
    is_bold: bool = False
    is_italic: bool = False
    is_superscript: bool = False
    is_monospace: bool = False
    is_serif: bool = False
    color: Optional[str] = None  # CSS hex color
    font_size: Optional[float] = None
    font_name: Optional[str] = None


def flags_decomposer(flags: int) -> Dict[str, bool]:
    """
    Decompose PyMuPDF font flags into human-readable attributes.
    
    PyMuPDF flags (from PDF spec):
    - bit 0: superscript (2^0 = 1)
    - bit 1: italic (2^1 = 2)
    - bit 2: serif (2^2 = 4)
    - bit 3: monospace (2^3 = 8)
    - bit 4: bold (2^4 = 16)
    
    Args:
        flags: Integer flags from PyMuPDF span
        
    Returns:
        Dict with boolean flags
    """
    return {
        "superscript": bool(flags & 2 ** 0),
        "italic": bool(flags & 2 ** 1),
        "serif": bool(flags & 2 ** 2),
        "monospace": bool(flags & 2 ** 3),
        "bold": bool(flags & 2 ** 4),
    }


def color_to_hex(color_int: Optional[int]) -> Optional[str]:
    """
    Convert PyMuPDF color integer to CSS hex string.
    
    PyMuPDF stores colors as integers (0xRRGGBB format).
    
    Args:
        color_int: Color as integer from PyMuPDF
        
    Returns:
        CSS hex string (e.g., "#FF0000") or None
    """
    if color_int is None or color_int < 0:
        return None
    
    # Handle grayscale (0-255 mapped to RGB)
    if color_int <= 255:
        gray = color_int
        return f"#{gray:02x}{gray:02x}{gray:02x}"
    
    # Full RGB color
    return f"#{color_int:06x}"


def is_default_color(color_hex: Optional[str]) -> bool:
    """Check if color is default (black or near-black)."""
    if not color_hex:
        return True
    
    # Normalize to hex without #
    color = color_hex.lstrip("#")
    
    # Check for black or very dark gray
    if color == "000000":
        return True
    
    # Check if all channels are nearly black (< 0x33 = 51)
    try:
        r = int(color[0:2], 16)
        g = int(color[2:4], 16)
        b = int(color[4:6], 16)
        return r < 30 and g < 30 and b < 30
    except (ValueError, IndexError):
        return False


class FormattingPreserver:
    """Preserve text formatting from PDF spans to HTML."""
    
    def extract_metadata(self, span: Dict[str, Any]) -> FormattingMetadata:
        """
        Extract formatting metadata from a PyMuPDF span.
        
        Args:
            span: Span dict from PyMuPDF get_text("dict")
            
        Returns:
            FormattingMetadata with extracted properties
        """
        flags = flags_decomposer(span.get("flags", 0))
        color = color_to_hex(span.get("color"))
        
        # Skip default black color
        if is_default_color(color):
            color = None
        
        return FormattingMetadata(
            text=span.get("text", ""),
            is_bold=flags["bold"],
            is_italic=flags["italic"],
            is_superscript=flags["superscript"],
            is_monospace=flags["monospace"],
            is_serif=flags["serif"],
            color=color,
            font_size=span.get("size"),
            font_name=span.get("font")
        )
    
    def render_to_html(self, metadata: FormattingMetadata) -> str:
        """
        Render formatting metadata to HTML with inline styles.
        
        Args:
            metadata: FormattingMetadata to render
            
        Returns:
            HTML string with formatting applied
        """
        text = metadata.text
        if not text:
            return ""
        
        # Escape HTML special characters
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        
        # Apply inline styles
        styles = []
        
        if metadata.color:
            styles.append(f"color: {metadata.color}")
        
        if metadata.font_size and metadata.font_size > 0:
            # Convert PDF points to CSS px (approximate)
            styles.append(f"font-size: {metadata.font_size:.1f}px")
        
        # Build style attribute
        style_attr = "; ".join(styles) if styles else ""
        
        # Apply semantic tags
        if metadata.is_superscript:
            text = f"<sup>{text}</sup>"
        
        if metadata.is_bold:
            text = f"<strong>{text}</strong>"
        
        if metadata.is_italic:
            text = f"<em>{text}</em>"
        
        if metadata.is_monospace:
            text = f"<code>{text}</code>"
        
        # Wrap in span if we have styles but no other tags
        if style_attr and not (metadata.is_bold or metadata.is_italic or 
                               metadata.is_superscript or metadata.is_monospace):
            text = f'<span style="{style_attr}">{text}</span>'
        elif style_attr:
            # Wrap entire thing in styled span
            text = f'<span style="{style_attr}">{text}</span>'
        
        return text
    
    def render_span(self, span: Dict[str, Any]) -> str:
        """
        Convenience method to extract and render a PyMuPDF span in one call.
        
        Args:
            span: Span dict from PyMuPDF
            
        Returns:
            HTML string
        """
        metadata = self.extract_metadata(span)
        return self.render_to_html(metadata)
