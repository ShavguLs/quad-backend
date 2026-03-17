"""
Simple and robust PDF text extractor.

This module provides reliable PDF text extraction using pdfplumber,
which handles most PDF layouts better than complex custom logic.
"""

import html
import logging
import re
from typing import List

import pdfplumber

logger = logging.getLogger(__name__)


def extract_text_from_pdf(file_content: bytes) -> List[str]:
    """
    Extract text from PDF file content.
    
    Args:
        file_content: Raw PDF file bytes
        
    Returns:
        List of HTML strings, one per page
        
    Raises:
        ValueError: If PDF cannot be parsed
    """
    pages_html = []
    
    try:
        with pdfplumber.open(stream=file_content) as pdf:
            logger.info(f"Extracting text from {len(pdf.pages)} PDF pages")
            
            for page_num, page in enumerate(pdf.pages, 1):
                try:
                    # Extract text with layout preservation
                    text = page.extract_text(
                        layout=True,  # Preserve layout
                        x_tolerance=3,  # Group nearby text horizontally
                        y_tolerance=3,  # Group nearby text vertically
                    )
                    
                    if not text or not text.strip():
                        # Try without layout if empty
                        text = page.extract_text() or ""
                    
                    # Convert to clean HTML
                    html_content = _text_to_html(text.strip() if text else "")
                    pages_html.append(html_content)
                    
                except Exception as e:
                    logger.warning(f"Error extracting page {page_num}: {e}")
                    pages_html.append("<p></p>")
                    
    except Exception as e:
        logger.error(f"Failed to open PDF: {e}")
        raise ValueError(f"Invalid PDF file: {e}")
    
    return pages_html


def _text_to_html(text: str) -> str:
    """
    Convert plain text to simple, clean HTML.
    
    Detects basic structure like headings and paragraphs.
    """
    if not text.strip():
        return "<p></p>"
    
    lines = text.split('\n')
    html_parts = []
    current_paragraph = []
    
    for line in lines:
        line = line.rstrip()
        if not line:
            # Empty line - end current paragraph
            if current_paragraph:
                html_parts.append(_render_paragraph(current_paragraph))
                current_paragraph = []
            continue
        
        # Check if line looks like a heading
        if _is_heading(line):
            # End current paragraph first
            if current_paragraph:
                html_parts.append(_render_paragraph(current_paragraph))
                current_paragraph = []
            html_parts.append(_render_heading(line))
        else:
            current_paragraph.append(line)
    
    # Don't forget the last paragraph
    if current_paragraph:
        html_parts.append(_render_paragraph(current_paragraph))
    
    return '\n'.join(html_parts) if html_parts else "<p></p>"


def _is_heading(line: str) -> bool:
    """Detect if a line is likely a heading."""
    # Strip leading numbers/bullets
    clean = re.sub(r'^[\s\d\.\)]+', '', line).strip()
    
    # Short lines are likely headings
    if len(clean) < 60 and len(clean) > 0:
        # Check if it's ALL CAPS or Title Case
        if clean.isupper():
            return True
        if clean.istitle() and len(clean.split()) <= 6:
            return True
    
    return False


def _render_heading(line: str) -> str:
    """Convert a line to a heading HTML element."""
    clean = re.sub(r'^[\s\d\.\)]+', '', line).strip()
    escaped = html.escape(clean)
    
    # Determine heading level by length
    if len(clean) < 30:
        return f"<h2>{escaped}</h2>"
    else:
        return f"<h3>{escaped}</h3>"


def _render_paragraph(lines: List[str]) -> str:
    """Convert lines to a paragraph HTML element."""
    # Join lines and normalize whitespace
    text = ' '.join(lines)
    text = re.sub(r'\s+', ' ', text).strip()
    
    if not text:
        return ""
    
    escaped = html.escape(text)
    return f"<p>{escaped}</p>"
