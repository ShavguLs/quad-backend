"""Enhanced diagnostics service for extraction pipeline.

Maps UnsupportedStyle dataclasses to Diagnostic instances with
actionable guidance for users. Extends existing diagnostics with
extraction-specific reporting.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from apps.books.converters.casting_contract import UnsupportedStyle
from apps.books.diagnostics.models import Diagnostic, DiagnosticsReport


@dataclass
class ExtractionDiagnosticsReport:
    """Complete diagnostics report for extraction."""
    
    book_id: int
    status: str  # 'completed', 'partial', 'failed'
    total_pages: int
    pages_processed: int
    average_confidence: float
    confidence_level: str  # 'high', 'medium', 'low'
    
    # Metrics
    text_coverage: float = 0.0
    font_consistency: float = 0.0
    structure_detection: float = 0.0
    reading_order: float = 0.0
    
    # Issues
    pages_with_warnings: int = 0
    pages_unacceptable: int = 0
    warnings: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    
    # Layout
    multi_column_pages: int = 0
    total_images_extracted: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert report to dictionary."""
        return {
            'book_id': self.book_id,
            'status': self.status,
            'summary': {
                'total_pages': self.total_pages,
                'pages_processed': self.pages_processed,
                'average_confidence': self.average_confidence,
                'confidence_level': self.confidence_level,
            },
            'metrics': {
                'text_coverage': self.text_coverage,
                'font_consistency': self.font_consistency,
                'structure_detection': self.structure_detection,
                'reading_order': self.reading_order,
            },
            'issues': {
                'pages_with_warnings': self.pages_with_warnings,
                'pages_unacceptable': self.pages_unacceptable,
                'warning_count': len(self.warnings),
                'error_count': len(self.errors),
            },
            'layout': {
                'multi_column_pages': self.multi_column_pages,
                'total_images_extracted': self.total_images_extracted,
            },
            'warnings': self.warnings[:50],  # Limit output
            'errors': self.errors[:20],  # Limit output
            'acceptable': self.average_confidence >= 0.5
        }
    
    def to_html_summary(self) -> str:
        """Generate HTML summary for admin/debug display."""
        level_class = {
            'high': 'success',
            'medium': 'warning',
            'low': 'danger'
        }.get(self.confidence_level, 'info')
        
        html = f"""
        <div class="extraction-report">
            <h3>Extraction Report for Book {self.book_id}</h3>
            
            <div class="summary alert alert-{level_class}">
                <strong>Status:</strong> {self.status.upper()} <br/>
                <strong>Confidence:</strong> {self.average_confidence:.1%} ({self.confidence_level.upper()})<br/>
                <strong>Pages:</strong> {self.pages_processed}/{self.total_pages} processed
            </div>
            
            <h4>Metrics</h4>
            <ul>
                <li>Text Coverage: {self.text_coverage:.1%}</li>
                <li>Font Consistency: {self.font_consistency:.1%}</li>
                <li>Structure Detection: {self.structure_detection:.1%}</li>
                <li>Reading Order: {self.reading_order:.1%}</li>
            </ul>
            
            <h4>Issues</h4>
            <ul>
                <li>Pages with warnings: {self.pages_with_warnings}</li>
                <li>Pages below threshold: {self.pages_unacceptable}</li>
                <li>Total warnings: {len(self.warnings)}</li>
                <li>Total errors: {len(self.errors)}</li>
            </ul>
        </div>
        """
        return html


def build_extraction_diagnostics_report(
    book_id: int,
    extraction_result: Any,  # ExtractionResult
    status: str
) -> ExtractionDiagnosticsReport:
    """
    Build comprehensive diagnostics report from extraction result.
    
    Args:
        book_id: Book ID
        extraction_result: ExtractionResult from engine
        status: Final extraction status
        
    Returns:
        ExtractionDiagnosticsReport with full analysis
    """
    confidence_scores = extraction_result.confidence_scores
    calculator = None
    
    if confidence_scores:
        from apps.books.extraction.confidence import ConfidenceCalculator
        calculator = ConfidenceCalculator()
        summary = calculator.aggregate_pages(confidence_scores)
    else:
        summary = {
            'overall_average': 0.0,
            'text_coverage_average': 0.0,
            'font_consistency_average': 0.0,
            'structure_detection_average': 0.0,
            'reading_order_average': 0.0,
            'pages_with_warnings': 0,
            'pages_unacceptable': 0,
        }
    
    # Count multi-column pages
    multi_column_pages = sum(
        1 for info in extraction_result.layout_info.values()
        if info.get('is_multi_column')
    )
    
    # Format warnings
    formatted_warnings = []
    seen_warnings = set()
    
    for warning in extraction_result.warnings:
        # Deduplicate similar warnings
        key = warning[:50]  # Use first 50 chars as key
        if key not in seen_warnings:
            seen_warnings.add(key)
            formatted_warnings.append({
                'message': warning,
                'type': 'warning'
            })
    
    # Determine confidence level
    avg_confidence = summary.get('overall_average', 0.0)
    confidence_level = (
        'high' if avg_confidence >= 0.8
        else 'medium' if avg_confidence >= 0.5
        else 'low'
    )
    
    return ExtractionDiagnosticsReport(
        book_id=book_id,
        status=status,
        total_pages=extraction_result.total_pages,
        pages_processed=len(extraction_result.pages),
        average_confidence=avg_confidence,
        confidence_level=confidence_level,
        text_coverage=summary.get('text_coverage_average', 0.0),
        font_consistency=summary.get('font_consistency_average', 0.0),
        structure_detection=summary.get('structure_detection_average', 0.0),
        reading_order=summary.get('reading_order_average', 0.0),
        pages_with_warnings=summary.get('pages_with_warnings', 0),
        pages_unacceptable=summary.get('pages_unacceptable', 0),
        warnings=formatted_warnings,
        errors=extraction_result.errors,
        multi_column_pages=multi_column_pages,
        total_images_extracted=0  # Would need to count from result
    )


def get_extraction_health_status(confidence: float,
                                 has_errors: bool = False,
                                 warnings_count: int = 0) -> Dict[str, Any]:
    """
    Get health status for extraction.
    
    Args:
        confidence: Average confidence score
        has_errors: Whether extraction had errors
        warnings_count: Number of warnings
        
    Returns:
        Dict with health status and recommendations
    """
    status = 'healthy'
    recommendations = []
    
    if has_errors:
        status = 'unhealthy'
        recommendations.append("Review error log for extraction failures")
    
    if confidence < 0.3:
        status = 'critical'
        recommendations.append(
            "Extraction quality is very low - consider using image-based fallback"
        )
    elif confidence < 0.5:
        if status == 'healthy':
            status = 'degraded'
        recommendations.append(
            "Review extracted content for formatting issues"
        )
    
    if warnings_count > 10:
        recommendations.append(
            f"High warning count ({warnings_count}) - check PDF complexity"
        )
    
    return {
        'status': status,
        'confidence': confidence,
        'recommendations': recommendations,
        'requires_attention': status != 'healthy'
    }


def _determine_action(style: UnsupportedStyle) -> str:
    """Determine the appropriate action based on style type and severity.
    
    Action mapping:
    - severity=critical: action="verify" (user must check)
    - type=table: action="reformat" (manual reformat needed)
    - type=image: action="reformat" (manual reformat needed)
    - type=border: action="ignore" (cosmetic only)
    - type=hyperlink: action="reformat" (links not preserved)
    - default: action="verify"
    """
    # Critical severity always requires verification
    if style.severity == "critical":
        return "verify"
    
    # Type-based actions
    if style.style_type == "table":
        return "reformat"
    elif style.style_type == "image":
        return "reformat"
    elif style.style_type == "border":
        return "ignore"
    elif style.style_type == "hyperlink":
        return "reformat"
    elif style.style_type == "font":
        return "verify"
    elif style.style_type == "color":
        return "verify"
    elif style.style_type == "alignment":
        return "verify"
    elif style.style_type == "spacing":
        return "ignore"
    elif style.style_type == "heading":
        return "verify"
    elif style.style_type == "list":
        return "verify"
    
    # Default for unknown types
    return "verify"


def _generate_section_id(style: UnsupportedStyle, index: int) -> str:
    """Generate a unique section_id for the diagnostic.
    
    Format: "page-{N}-{type}" or "{type}-{index}" if no page
    """
    if style.page is not None:
        return f"page-{style.page}-{style.style_type}"
    else:
        return f"{style.style_type}-{index}"


def _build_message(style: UnsupportedStyle) -> str:
    """Build a human-readable message from UnsupportedStyle.
    
    Uses the description if available, otherwise generates
    a default message based on type.
    """
    if style.description:
        return style.description
    
    # Default messages by type
    messages = {
        "heading": "Heading structure may not be fully preserved",
        "list": "List formatting may have been simplified",
        "table": "Table detected - will be converted to plain text",
        "image": "Image found - will not be extracted",
        "font": "Custom font may not be preserved",
        "color": "Text color may not be preserved",
        "alignment": "Text alignment may have changed",
        "spacing": "Spacing may have been adjusted",
        "border": "Borders are not supported",
        "hyperlink": "Links will not be preserved",
    }
    
    return messages.get(style.style_type, f"{style.style_type} style may not be fully preserved")


def build_diagnostics_report(
    unsupported_styles: list[UnsupportedStyle],
) -> DiagnosticsReport:
    """Build a DiagnosticsReport from a list of UnsupportedStyle.
    
    Maps each UnsupportedStyle to a Diagnostic with:
    - severity: Preserved from UnsupportedStyle
    - type: Mapped from style_type
    - section_id: Generated from page + type
    - message: Built from description or type
    - action: Determined by type and severity
    - page: Preserved from UnsupportedStyle
    - location_hint: Preserved from UnsupportedStyle
    
    Args:
        unsupported_styles: List of UnsupportedStyle from conversion
        
    Returns:
        Populated DiagnosticsReport with computed summaries
    """
    diagnostics: list[Diagnostic] = []
    
    for index, style in enumerate(unsupported_styles):
        diagnostic = Diagnostic(
            severity=style.severity,
            type=style.style_type,
            section_id=_generate_section_id(style, index),
            message=_build_message(style),
            action=_determine_action(style),
            page=style.page,
            location_hint=style.location_hint,
        )
        diagnostics.append(diagnostic)
    
    return DiagnosticsReport(items=diagnostics)
