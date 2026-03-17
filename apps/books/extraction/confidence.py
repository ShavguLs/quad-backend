"""Confidence scoring for PDF text extraction quality.

Provides metrics to assess extraction reliability:
- Text coverage: Ratio of text area to page area
- Font consistency: Dominant font stability
- Structure detection: Paragraph/heading identification
- Reading order: Y-position monotonicity
- Image detection: Extraction success rate

Each metric contributes to an overall confidence score (0.0-1.0).
Low confidence triggers diagnostics warnings.
"""

import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .text_extractor import ExtractedPage
    from .image_extractor import ExtractedImage

logger = logging.getLogger(__name__)


@dataclass
class ExtractionConfidence:
    """Confidence scores for a single page extraction.
    
    Attributes:
        overall: Weighted average confidence (0.0-1.0)
        text_coverage: Text area ratio (0.0-1.0)
        font_consistency: Dominant font ratio (0.0-1.0)
        structure_detection: Structured block ratio (0.0-1.0)
        reading_order: Y-position monotonicity (0.0-1.0)
        image_success: Image extraction ratio (0.0-1.0)
        warnings: List of human-readable warnings
        page_number: Page number (1-based)
    """
    overall: float = 0.0
    text_coverage: float = 0.0
    font_consistency: float = 0.0
    structure_detection: float = 0.0
    reading_order: float = 0.0
    image_success: float = 1.0  # Default to 1.0 if no images expected
    warnings: List[str] = field(default_factory=list)
    page_number: int = 0
    
    # Metric weights for overall score calculation
    WEIGHTS = {
        'text_coverage': 0.20,
        'font_consistency': 0.15,
        'structure_detection': 0.25,
        'reading_order': 0.25,
        'image_success': 0.15
    }
    
    # Thresholds for warnings
    THRESHOLDS = {
        'text_coverage': 0.1,
        'font_consistency': 0.5,
        'structure_detection': 0.7,
        'reading_order': 0.9,
        'image_success': 0.9
    }
    
    def is_acceptable(self) -> bool:
        """Check if confidence meets minimum acceptable levels."""
        return (
            self.overall >= 0.5 and
            self.text_coverage >= self.THRESHOLDS['text_coverage'] and
            self.reading_order >= self.THRESHOLDS['reading_order']
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'overall': round(self.overall, 2),
            'text_coverage': round(self.text_coverage, 2),
            'font_consistency': round(self.font_consistency, 2),
            'structure_detection': round(self.structure_detection, 2),
            'reading_order': round(self.reading_order, 2),
            'image_success': round(self.image_success, 2),
            'warnings': self.warnings,
            'page_number': self.page_number,
            'acceptable': self.is_acceptable()
        }


class ConfidenceCalculator:
    """Calculate confidence scores for extraction results."""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def calculate(self,
                  page: 'ExtractedPage',
                  images_extracted: List['ExtractedImage'] = None,
                  images_expected: int = 0) -> ExtractionConfidence:
        """
        Calculate confidence scores for a single page.
        
        Args:
            page: Extracted page with blocks and layout info
            images_extracted: List of images actually extracted
            images_expected: Number of images expected (from detection)
            
        Returns:
            ExtractionConfidence with all metrics
        """
        warnings = []
        
        # Calculate individual metrics
        text_coverage = self._calc_text_coverage(page)
        font_consistency = self._calc_font_consistency(page)
        structure_detection = self._calc_structure_detection(page)
        reading_order = self._calc_reading_order(page)
        image_success = self._calc_image_success(
            images_extracted, images_expected
        )
        
        # Check thresholds and generate warnings
        if text_coverage < ExtractionConfidence.THRESHOLDS['text_coverage']:
            warnings.append(
                f"Low text coverage ({text_coverage:.1%}) - possible image-only page "
                f"or extraction failure"
            )
        
        if font_consistency < ExtractionConfidence.THRESHOLDS['font_consistency']:
            warnings.append(
                f"Inconsistent fonts ({font_consistency:.1%}) - may indicate "
                f"complex layout or mixed content"
            )
        
        if structure_detection < ExtractionConfidence.THRESHOLDS['structure_detection']:
            warnings.append(
                f"Poor structure detection ({structure_detection:.1%}) - "
                f"paragraphs/headings may be misidentified"
            )
        
        if reading_order < ExtractionConfidence.THRESHOLDS['reading_order']:
            warnings.append(
                f"Questionable reading order ({reading_order:.1%}) - "
                f"possible multi-column layout issue"
            )
        
        if image_success < ExtractionConfidence.THRESHOLDS['image_success']:
            warnings.append(
                f"Image extraction incomplete ({image_success:.1%} of "
                f"{images_expected} expected images)"
            )
        
        # Calculate weighted overall score
        weights = ExtractionConfidence.WEIGHTS
        overall = (
            text_coverage * weights['text_coverage'] +
            font_consistency * weights['font_consistency'] +
            structure_detection * weights['structure_detection'] +
            reading_order * weights['reading_order'] +
            image_success * weights['image_success']
        )
        
        return ExtractionConfidence(
            overall=round(overall, 2),
            text_coverage=round(text_coverage, 2),
            font_consistency=round(font_consistency, 2),
            structure_detection=round(structure_detection, 2),
            reading_order=round(reading_order, 2),
            image_success=round(image_success, 2),
            warnings=warnings,
            page_number=page.page_number
        )
    
    def _calc_text_coverage(self, page: 'ExtractedPage') -> float:
        """
        Calculate text coverage ratio.
        
        Compares total text block area to page area.
        Good coverage: > 10% of page has text.
        """
        if not page.blocks or page.width == 0 or page.height == 0:
            return 0.0
        
        # Calculate total text area
        text_area = 0.0
        for block in page.blocks:
            block_width = block.x1 - block.x0
            block_height = block.y1 - block.y0
            text_area += block_width * block_height
        
        page_area = page.width * page.height
        if page_area == 0:
            return 0.0
        
        # Normalize: 30% coverage is considered "good" (1.0)
        coverage = min(1.0, text_area / (page_area * 0.3))
        return coverage
    
    def _calc_font_consistency(self, page: 'ExtractedPage') -> float:
        """
        Calculate font consistency ratio.
        
        Measures dominance of a single font.
        Consistency: > 50% of spans use the same font.
        """
        fonts = []
        
        for block in page.blocks:
            for line in block.lines:
                for span in line.spans:
                    if span.font_name:
                        fonts.append(span.font_name)
        
        if not fonts:
            return 0.0
        
        # Count font occurrences
        font_counts = Counter(fonts)
        most_common_count = font_counts.most_common(1)[0][1]
        
        return most_common_count / len(fonts)
    
    def _calc_structure_detection(self, page: 'ExtractedPage') -> float:
        """
        Calculate structure detection ratio.
        
        Measures how many blocks are classified as
        paragraphs or headings vs. unclassified blocks.
        """
        if not page.blocks:
            return 0.0
        
        structured_count = sum(
            1 for b in page.blocks
            if b.block_type in ['paragraph', 'heading']
        )
        
        return structured_count / len(page.blocks)
    
    def _calc_reading_order(self, page: 'ExtractedPage') -> float:
        """
        Calculate reading order confidence.
        
        Measures y-position monotonicity (top-to-bottom order).
        Fewer inversions = higher confidence.
        """
        if not page.blocks or len(page.blocks) < 2:
            return 1.0  # Single block is always in order
        
        # Get y-positions
        y_positions = [b.y0 for b in page.blocks]
        
        # Count inversions (when y decreases)
        inversions = sum(
            1 for i in range(1, len(y_positions))
            if y_positions[i] < y_positions[i - 1]
        )
        
        # Calculate confidence: 1.0 - inversion ratio
        inversion_ratio = inversions / (len(y_positions) - 1)
        confidence = max(0.0, 1.0 - inversion_ratio)
        
        # Adjust for multi-column layouts (from layout analyzer)
        if page.layout and page.layout.is_multi_column:
            # Multi-column has expected inversions at column boundaries
            # Apply a small boost since some inversions are expected
            confidence = min(1.0, confidence + 0.1)
        
        return confidence
    
    def _calc_image_success(self,
                           images_extracted: List['ExtractedImage'] = None,
                           images_expected: int = 0) -> float:
        """
        Calculate image extraction success ratio.
        
        If no images expected, returns 1.0 (no issue).
        """
        if images_expected == 0:
            return 1.0  # No images expected = success
        
        extracted_count = len(images_extracted) if images_extracted else 0
        return min(1.0, extracted_count / images_expected)
    
    def aggregate_pages(self,
                       page_confidences: List[ExtractionConfidence]) -> Dict[str, Any]:
        """
        Aggregate confidence scores across multiple pages.
        
        Args:
            page_confidences: List of per-page confidence scores
            
        Returns:
            Dict with aggregated metrics and summary
        """
        if not page_confidences:
            return {
                'overall_average': 0.0,
                'total_pages': 0,
                'pages_with_warnings': 0,
                'pages_unacceptable': 0,
                'all_warnings': []
            }
        
        # Calculate averages
        metrics = ['overall', 'text_coverage', 'font_consistency',
                  'structure_detection', 'reading_order', 'image_success']
        
        averages = {}
        for metric in metrics:
            values = [getattr(c, metric) for c in page_confidences]
            averages[f'{metric}_average'] = round(sum(values) / len(values), 2)
        
        # Collect all warnings
        all_warnings = []
        for conf in page_confidences:
            for warning in conf.warnings:
                all_warnings.append({
                    'page': conf.page_number,
                    'warning': warning
                })
        
        # Count issues
        pages_with_warnings = sum(1 for c in page_confidences if c.warnings)
        pages_unacceptable = sum(1 for c in page_confidences if not c.is_acceptable())
        
        return {
            **averages,
            'total_pages': len(page_confidences),
            'pages_with_warnings': pages_with_warnings,
            'pages_unacceptable': pages_unacceptable,
            'all_warnings': all_warnings,
            'lowest_confidence_page': min(
                page_confidences,
                key=lambda c: c.overall
            ).page_number if page_confidences else None
        }


def calculate_confidence(page: 'ExtractedPage',
                        images_extracted: List['ExtractedImage'] = None,
                        images_expected: int = 0) -> ExtractionConfidence:
    """
    Convenience function to calculate confidence for a page.
    
    Args:
        page: Extracted page
        images_extracted: Extracted images from page
        images_expected: Expected image count
        
    Returns:
        ExtractionConfidence with all metrics
    """
    calculator = ConfidenceCalculator()
    return calculator.calculate(page, images_extracted, images_expected)


def get_confidence_level(confidence: float) -> str:
    """
    Get human-readable confidence level.
    
    Args:
        confidence: Overall confidence score (0.0-1.0)
        
    Returns:
        'high' (≥0.8), 'medium' (0.5-0.8), or 'low' (<0.5)
    """
    if confidence >= 0.8:
        return 'high'
    elif confidence >= 0.5:
        return 'medium'
    else:
        return 'low'
