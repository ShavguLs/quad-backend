"""Main extraction engine orchestrator for PDF text extraction.

Coordinates:
- Text extraction with structure preservation
- Layout analysis for multi-column detection
- Image extraction coordination (placeholder for Plan 35-02)
- Confidence scoring (placeholder for Plan 35-03)
"""

import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable
from pathlib import Path

import pymupdf

from .text_extractor import TextExtractor, ExtractedPage
from .layout_analyzer import LayoutAnalyzer
from .formatter import FormattingPreserver
from .confidence import ConfidenceCalculator, ExtractionConfidence

logger = logging.getLogger(__name__)


@dataclass
class ExtractionResult:
    """Complete extraction result for a PDF.
    
    Attributes:
        book_id: Optional book ID for tracking
        pages: List of extracted pages
        total_pages: Total number of pages processed
        layout_info: Per-page layout analysis results
        confidence_scores: Per-page confidence scores
        warnings: List of extraction warnings
        errors: List of extraction errors
    """
    book_id: Optional[int] = None
    pages: List[ExtractedPage] = field(default_factory=list)
    total_pages: int = 0
    layout_info: Dict[int, Dict] = field(default_factory=dict)
    confidence_scores: List[ExtractionConfidence] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    
    @property
    def average_confidence(self) -> float:
        """Calculate average overall confidence across all pages."""
        if not self.confidence_scores:
            return 0.0
        return round(
            sum(c.overall for c in self.confidence_scores) / len(self.confidence_scores),
            2
        )
    
    @property
    def confidence_level(self) -> str:
        """Get human-readable confidence level."""
        from .confidence import get_confidence_level
        return get_confidence_level(self.average_confidence)
    
    def to_html(self) -> List[str]:
        """
        Convert extracted pages to HTML strings.
        
        Returns:
            List of HTML strings, one per page
        """
        html_pages = []
        
        for page in self.pages:
            html_parts = []
            
            for block in page.blocks:
                if block.block_type == "heading" and block.heading_level > 0:
                    # Build heading HTML
                    lines_html = " ".join(line.html for line in block.lines)
                    html_parts.append(
                        f'<h{block.heading_level}>{lines_html}</h{block.heading_level}>'
                    )
                else:
                    # Build paragraph HTML
                    lines_html = " ".join(line.html for line in block.lines)
                    html_parts.append(f'<p>{lines_html}</p>')
            
            html_pages.append("\n".join(html_parts))
        
        return html_pages


class ExtractionEngine:
    """Main orchestrator for PDF text extraction.
    
    Coordinates text extraction, layout analysis, and result aggregation.
    Provides both batch and streaming extraction interfaces.
    """
    
    def __init__(self,
                 text_extractor: Optional[TextExtractor] = None,
                 layout_analyzer: Optional[LayoutAnalyzer] = None,
                 confidence_calculator: Optional[ConfidenceCalculator] = None):
        """
        Initialize extraction engine.
        
        Args:
            text_extractor: Optional custom text extractor
            layout_analyzer: Optional custom layout analyzer
            confidence_calculator: Optional custom confidence calculator
        """
        self.text_extractor = text_extractor or TextExtractor()
        self.layout_analyzer = layout_analyzer or LayoutAnalyzer()
        self.confidence_calculator = confidence_calculator or ConfidenceCalculator()
        self.logger = logging.getLogger(__name__)
    
    def extract(self,
                file_path: str,
                book_id: Optional[int] = None,
                progress_callback: Optional[Callable[[int, int, str], None]] = None
               ) -> ExtractionResult:
        """
        Extract content from PDF file.
        
        Args:
            file_path: Path to PDF file
            book_id: Optional book ID for logging
            progress_callback: Optional callback(current, total, stage)
            
        Returns:
            ExtractionResult with pages, layout info, and diagnostics
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF file not found: {file_path}")
        
        self.logger.info(f"Starting extraction for {file_path} (book_id={book_id})")
        
        # Open document
        try:
            doc = pymupdf.open(file_path)
        except Exception as e:
            self.logger.error(f"Failed to open PDF: {e}")
            raise ValueError(f"Invalid PDF file: {e}")
        
        total_pages = len(doc)
        pages = []
        layout_info = {}
        confidence_scores = []
        warnings = []
        errors = []
        
        try:
            for page_num in range(total_pages):
                # Report progress
                if progress_callback:
                    progress_callback(
                        page_num + 1,
                        total_pages,
                        f"Extracting page {page_num + 1}/{total_pages}"
                    )
                
                try:
                    page = doc[page_num]
                    
                    # Extract page content
                    extracted_page = self.text_extractor.extract_page(
                        page, page_num + 1
                    )
                    pages.append(extracted_page)
                    
                    # Store layout info
                    if extracted_page.layout:
                        layout_info[page_num + 1] = {
                            "columns": extracted_page.layout.detected_columns,
                            "is_multi_column": extracted_page.layout.is_multi_column,
                            "warnings": extracted_page.layout.warnings
                        }
                        warnings.extend(extracted_page.layout.warnings)
                    
                    # Calculate confidence for this page
                    confidence = self.confidence_calculator.calculate(
                        page=extracted_page,
                        images_extracted=[],  # Placeholder - could be improved
                        images_expected=0
                    )
                    confidence_scores.append(confidence)
                    
                    # Add confidence warnings to overall warnings
                    warnings.extend(confidence.warnings)
                    
                except Exception as e:
                    error_msg = f"Error extracting page {page_num + 1}: {e}"
                    self.logger.error(error_msg)
                    errors.append(error_msg)
                    
                    # Continue with next page
                    continue
                    
        finally:
            doc.close()
        
        # Aggregate confidence and generate summary
        confidence_summary = self.confidence_calculator.aggregate_pages(
            confidence_scores
        )
        
        self.logger.info(
            f"Extraction complete: {len(pages)}/{total_pages} pages, "
            f"avg_confidence={confidence_summary.get('overall_average', 0):.2f}, "
            f"{len(warnings)} warnings, {len(errors)} errors"
        )
        
        return ExtractionResult(
            book_id=book_id,
            pages=pages,
            total_pages=total_pages,
            layout_info=layout_info,
            confidence_scores=confidence_scores,
            warnings=list(set(warnings)),  # Deduplicate
            errors=errors
        )
    
    def extract_iter(self, file_path: str):
        """
        Extract PDF page by page for memory efficiency.
        
        Yields ExtractedPage one at a time to handle large PDFs.
        
        Args:
            file_path: Path to PDF file
            
        Yields:
            ExtractedPage for each page
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF file not found: {file_path}")
        
        doc = pymupdf.open(file_path)
        
        try:
            for page_num in range(len(doc)):
                page = doc[page_num]
                extracted = self.text_extractor.extract_page(page, page_num + 1)
                yield extracted
        finally:
            doc.close()
    
    def validate_pdf(self, file_path: str) -> Dict[str, Any]:
        """
        Validate PDF file before extraction.
        
        Args:
            file_path: Path to PDF file
            
        Returns:
            Dict with validation results:
            - valid: bool
            - page_count: int
            - encrypted: bool
            - warnings: List[str]
        """
        result = {
            "valid": False,
            "page_count": 0,
            "encrypted": False,
            "warnings": []
        }
        
        try:
            doc = pymupdf.open(file_path)
            
            try:
                result["page_count"] = len(doc)
                result["encrypted"] = doc.is_encrypted
                result["valid"] = True
                
                # Check for potential issues
                if result["page_count"] == 0:
                    result["warnings"].append("PDF has no pages")
                    result["valid"] = False
                
                if result["page_count"] > 1000:
                    result["warnings"].append(
                        f"Large PDF detected ({result['page_count']} pages) - "
                        "extraction may take significant time"
                    )
                
                if result["encrypted"]:
                    result["warnings"].append("PDF is encrypted - may need password")
                    
            finally:
                doc.close()
                
        except Exception as e:
            result["warnings"].append(f"Failed to validate PDF: {e}")
        
        return result
