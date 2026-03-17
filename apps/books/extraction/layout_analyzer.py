"""Layout analysis for multi-column detection and reading order sorting."""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class LayoutInfo:
    """Layout analysis results for a page."""
    detected_columns: int = 1
    column_boundaries: List[tuple] = field(default_factory=list)
    reading_order: List[int] = field(default_factory=list)
    is_multi_column: bool = False
    warnings: List[str] = field(default_factory=list)


class LayoutAnalyzer:
    """Detect multi-column layouts and sort blocks by reading order."""
    
    def __init__(self, column_threshold: float = 50.0, min_column_gap: float = 30.0):
        """
        Initialize layout analyzer.
        
        Args:
            column_threshold: X-coordinate clustering threshold in points
            min_column_gap: Minimum gap between columns to detect multi-column
        """
        self.column_threshold = column_threshold
        self.min_column_gap = min_column_gap
    
    def analyze(self, page) -> LayoutInfo:
        """
        Analyze page layout and detect columns.
        
        Args:
            page: PyMuPDF page object
            
        Returns:
            LayoutInfo with column detection and reading order
        """
        text_dict = page.get_text("dict", flags=0)
        blocks = [b for b in text_dict.get("blocks", []) if b.get("type") == 0]
        
        if not blocks:
            return LayoutInfo()
        
        # Detect columns via x-coordinate clustering
        columns = self._detect_columns(blocks)
        
        # Sort blocks by reading order
        sorted_indices = self._sort_reading_order(blocks, columns)
        
        return LayoutInfo(
            detected_columns=len(columns),
            column_boundaries=columns,
            reading_order=sorted_indices,
            is_multi_column=len(columns) > 1,
            warnings=self._generate_warnings(blocks, columns)
        )
    
    def _detect_columns(self, blocks: List[dict]) -> List[tuple]:
        """
        Detect column boundaries via x-coordinate clustering.
        
        Algorithm:
        1. Extract x-coordinates (left edge) of all blocks
        2. Cluster by rounding to column_threshold
        3. Sort clusters left-to-right
        4. Return column boundary tuples (x0, x1)
        """
        if not blocks:
            return []
        
        # Extract x0 coordinates
        x_coords = [b["bbox"][0] for b in blocks]
        
        # Cluster by rounding to threshold
        clusters = defaultdict(list)
        for block, x in zip(blocks, x_coords):
            cluster_key = round(x / self.column_threshold) * self.column_threshold
            clusters[cluster_key].append(block)
        
        if not clusters:
            return []
        
        # Build column boundaries
        columns = []
        for cluster_key in sorted(clusters.keys()):
            cluster_blocks = clusters[cluster_key]
            x0 = min(b["bbox"][0] for b in cluster_blocks)
            x1 = max(b["bbox"][2] for b in cluster_blocks)
            columns.append((x0, x1))
        
        # Merge columns that are too close
        return self._merge_close_columns(columns)
    
    def _merge_close_columns(self, columns: List[tuple]) -> List[tuple]:
        """Merge columns that are closer than min_column_gap."""
        if len(columns) <= 1:
            return columns
        
        merged = [columns[0]]
        
        for x0, x1 in columns[1:]:
            last_x0, last_x1 = merged[-1]
            gap = x0 - last_x1
            
            if gap < self.min_column_gap:
                # Merge with previous column
                merged[-1] = (last_x0, max(last_x1, x1))
            else:
                merged.append((x0, x1))
        
        return merged
    
    def _sort_reading_order(self, blocks: List[dict], 
                           columns: List[tuple]) -> List[int]:
        """
        Sort block indices by reading order (top-to-bottom, left-to-right).
        
        For multi-column: sort by column first, then by y-position within column.
        """
        if not blocks:
            return []
        
        if len(columns) <= 1:
            # Single column: simple top-to-bottom sort
            return sorted(
                range(len(blocks)),
                key=lambda i: blocks[i]["bbox"][1]  # Sort by y0
            )
        
        # Multi-column: group by column, then sort within each column
        column_groups = [[] for _ in columns]
        
        for i, block in enumerate(blocks):
            x_center = (block["bbox"][0] + block["bbox"][2]) / 2
            
            # Find which column this block belongs to
            col_idx = 0
            for j, (col_x0, col_x1) in enumerate(columns):
                if col_x0 <= x_center <= col_x1:
                    col_idx = j
                    break
            
            column_groups[col_idx].append((i, block["bbox"][1]))  # (index, y0)
        
        # Sort within each column by y-position
        sorted_indices = []
        for group in column_groups:
            group.sort(key=lambda x: x[1])  # Sort by y0
            sorted_indices.extend(idx for idx, _ in group)
        
        return sorted_indices
    
    def _generate_warnings(self, blocks: List[dict], 
                          columns: List[tuple]) -> List[str]:
        """Generate warnings about potential layout issues."""
        warnings = []
        
        if len(columns) > 1:
            warnings.append(f"Detected {len(columns)}-column layout")
        
        # Check for potential interleaved columns (reading order issues)
        if blocks and len(columns) > 1:
            y_coords = [b["bbox"][1] for b in blocks]
            inversions = sum(1 for i in range(1, len(y_coords)) 
                           if y_coords[i] < y_coords[i-1])
            if inversions > len(blocks) * 0.1:
                warnings.append(
                    f"High y-position inversion rate ({inversions}/{len(blocks)}) - "
                    "reading order may be incorrect"
                )
        
        return warnings


def detect_potential_columns(blocks: List[dict], 
                             threshold: float = 30.0) -> bool:
    """
    Quick check if page likely has multi-column layout.
    
    Args:
        blocks: List of text blocks from PyMuPDF
        threshold: X-coordinate grouping threshold
        
    Returns:
        True if multi-column layout likely detected
    """
    if len(blocks) < 4:
        return False
    
    x_coords = [b["bbox"][0] for b in blocks]
    unique_x = len(set(round(x / threshold) * threshold for x in x_coords))
    
    return unique_x >= 2
