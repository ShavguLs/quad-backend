"""Diagnostic dataclasses for PDF import reporting.

Provides structured diagnostics for unsupported style fragments
captured during PDF-to-draft conversion.
"""

from dataclasses import dataclass, field
from typing import Literal, Optional


@dataclass
class Diagnostic:
    """A single diagnostic issue for an unsupported style fragment.
    
    Captures actionable information about style preservation issues
    detected during PDF import, enabling users to understand what
    was affected and what actions they can take.
    
    Attributes:
        severity: "warning" (cosmetic) or "critical" (structural)
        type: Category matching UnsupportedStyle.style_type
        section_id: Identifier for the section (e.g., "page-1", "list-block-3")
        message: Human-readable description of the issue
        action: What user can do: "verify", "reformat", "ignore"
        page: Page number where issue occurs (if applicable)
        location_hint: Optional text snippet or coordinates for finding the issue
    """
    severity: Literal["warning", "critical"]
    type: str
    section_id: Optional[str]
    message: str
    action: Literal["verify", "reformat", "ignore"]
    page: Optional[int] = None
    location_hint: Optional[str] = None


@dataclass
class DiagnosticsReport:
    """Complete diagnostic report for a PDF import operation.
    
    Aggregates all diagnostics from a conversion and provides
    summary statistics organized by severity and type.
    
    Attributes:
        items: List of all diagnostic items
        summary: Computed statistics (total, by_severity, by_type)
        by_section: Diagnostics grouped by section_id for quick lookup
    """
    items: list[Diagnostic] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    by_section: dict[str, list[Diagnostic]] = field(default_factory=dict)
    
    def __post_init__(self):
        """Compute summary statistics after initialization."""
        self._compute_summary()
        self._group_by_section()
    
    def _compute_summary(self) -> None:
        """Calculate summary statistics from items."""
        total = len(self.items)
        by_severity = {"warning": 0, "critical": 0}
        by_type: dict[str, int] = {}
        
        for item in self.items:
            # Count by severity
            if item.severity in by_severity:
                by_severity[item.severity] += 1
            
            # Count by type
            by_type[item.type] = by_type.get(item.type, 0) + 1
        
        self.summary = {
            "total": total,
            "by_severity": by_severity,
            "by_type": by_type,
        }
    
    def _group_by_section(self) -> None:
        """Group diagnostics by section_id for quick lookup."""
        grouped: dict[str, list[Diagnostic]] = {}
        
        for item in self.items:
            section_id = item.section_id or "unknown"
            if section_id not in grouped:
                grouped[section_id] = []
            grouped[section_id].append(item)
        
        self.by_section = grouped
    
    def add_item(self, diagnostic: Diagnostic) -> None:
        """Add a diagnostic and update computed fields."""
        self.items.append(diagnostic)
        self._compute_summary()
        self._group_by_section()
    
    def has_critical(self) -> bool:
        """Check if report contains any critical diagnostics."""
        return self.summary.get("by_severity", {}).get("critical", 0) > 0
    
    def to_dict(self) -> dict:
        """Convert report to dictionary for serialization."""
        return {
            "items": [
                {
                    "severity": item.severity,
                    "type": item.type,
                    "section_id": item.section_id,
                    "message": item.message,
                    "action": item.action,
                    "page": item.page,
                    "location_hint": item.location_hint,
                }
                for item in self.items
            ],
            "summary": self.summary,
            "by_section": {
                section: [
                    {
                        "severity": item.severity,
                        "type": item.type,
                        "section_id": item.section_id,
                        "message": item.message,
                        "action": item.action,
                        "page": item.page,
                        "location_hint": item.location_hint,
                    }
                    for item in items
                ]
                for section, items in self.by_section.items()
            },
        }
