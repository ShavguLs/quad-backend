"""Diagnostics module for PDF casting pipeline.

Provides diagnostic reporting for unsupported style fragments
detected during PDF import, enabling users to see actionable
information about style preservation issues.
"""

from apps.books.diagnostics.models import Diagnostic, DiagnosticsReport
from apps.books.diagnostics.service import build_diagnostics_report

__version__ = "diagnostics-v1"

__all__ = ["Diagnostic", "DiagnosticsReport", "build_diagnostics_report"]
