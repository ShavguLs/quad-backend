"""Deterministic list inference state machine for PDF casting.

This module implements the line-to-contract inference logic that processes
extracted PDF lines and emits explicit list blocks with stable semantics.

Key behaviors:
1. Classifies lines into ordered/unordered/continuation/paragraph
2. Computes nesting depth via x-coordinate bucketization
3. Splits list blocks on same-depth style changes
4. Applies deterministic fallback for ambiguous markers
"""

from __future__ import annotations

import statistics
from typing import List, Optional, Tuple

from .casting_contract import (
    BULLET_SYMBOLS,
    CastDocument,
    LineKind,
    ListBlock,
    ListItem,
    ListType,
    classify_marker_kind,
    extract_marker,
    get_symbol_name,
    is_list_marker,
    normalize_text,
    parse_marker_value,
)

# Tolerance for x-coordinate jitter (as fraction of indent unit)
INDENT_TOLERANCE = 0.2

# Minimum confidence threshold for marker classification
MIN_MARKER_CONFIDENCE = 0.5


def classify_line_kind(text: str, active_list_type: Optional[ListType] = None) -> LineKind:
    """Classify a line into its semantic kind.
    
    Uses fixed precedence rules:
    1. Check for explicit ordered/unordered markers
    2. If inside active list, check for continuation patterns
    3. Default to paragraph
    
    Args:
        text: The line text to classify
        active_list_type: Type of currently active list (if any)
    
    Returns:
        One of: ordered, unordered, continuation, paragraph
    """
    normalized = normalize_text(text).strip()
    
    if not normalized:
        return "paragraph"
    
    # Extract potential marker
    marker, remaining = extract_marker(normalized)
    
    if marker:
        kind = classify_marker_kind(marker)
        
        if is_list_marker(marker, kind):
            # Explicit list marker found
            if kind == "symbol":
                return "unordered"
            else:
                return "ordered"
    
    # Check for continuation indicators if inside a list
    if active_list_type:
        # Lines that look like continuations (indented, no marker)
        # This is a heuristic - actual continuation detection happens
        # at the block level with indentation analysis
        stripped = normalized.lstrip()
        if stripped and not marker:
            # Could be continuation - mark as such for further processing
            return "continuation"
    
    return "paragraph"


def compute_indent_unit(x_positions: List[float]) -> float:
    """Compute the base indentation unit from observed x-coordinates.
    
    Uses median of non-zero deltas between sorted x positions.
    Returns a default value if insufficient data.
    
    Args:
        x_positions: List of x0 coordinates from lines
    
    Returns:
        Estimated indentation unit in points
    """
    if len(x_positions) < 2:
        return 24.0  # Default ~1/3 inch at 72 DPI
    
    # Sort and compute deltas
    sorted_x = sorted(set(x_positions))
    if len(sorted_x) < 2:
        return 24.0
    
    deltas = [sorted_x[i+1] - sorted_x[i] for i in range(len(sorted_x)-1)]
    
    # Filter out very small deltas (likely same column, not indentation)
    significant_deltas = [d for d in deltas if d > 5.0]
    
    if not significant_deltas:
        return 24.0
    
    # Use median for robustness against outliers
    return statistics.median(significant_deltas)


def infer_depth(x0: float, base_x0: float, indent_unit: float) -> int:
    """Infer nesting depth from x-coordinate.
    
    Computes depth as quantized offset from base position,
    with tolerance for minor x-coordinate jitter.
    
    Args:
        x0: The line's x-coordinate
        base_x0: The base x-coordinate (left margin)
        indent_unit: Estimated indentation unit
    
    Returns:
        Nesting depth (0 = top level)
    """
    if indent_unit <= 0:
        return 0
    
    # Compute raw offset from base
    offset = x0 - base_x0
    
    if offset <= 0:
        return 0
    
    # Apply tolerance band to prevent oscillation
    tolerance = indent_unit * INDENT_TOLERANCE
    
    # Quantize to nearest indent level with tolerance
    raw_depth = offset / indent_unit
    
    # Round to nearest integer, but require crossing tolerance boundary
    if raw_depth < 0.5 - INDENT_TOLERANCE:
        return 0
    
    # Round to nearest depth level
    depth = max(0, round(raw_depth))
    
    # Clamp to reasonable maximum
    return min(depth, 10)


def should_split_block(
    current_type: ListType,
    current_depth: int,
    new_type: LineKind,
    new_depth: int
) -> bool:
    """Determine if a new block should be started.
    
    Block splits occur when:
    - List type changes at the same depth (ordered <-> unordered)
    - Depth changes significantly (new nesting level)
    - Non-list content interrupts
    
    Args:
        current_type: Type of current list block
        current_depth: Depth of current list block
        new_type: Type of incoming line
        new_depth: Depth of incoming line
    
    Returns:
        True if a new block should be started
    """
    if new_type == "paragraph":
        return True
    
    if new_type == "continuation":
        # Continuation doesn't split - it's part of current item
        return False
    
    # new_type is ordered or unordered
    new_list_type = new_type  # type: ignore
    
    # Same depth, different type = split
    if new_depth == current_depth and new_list_type != current_type:
        return True
    
    # Depth decreases to base level with same type = continue (same list continuing)
    # Depth decreases to different level or different type = split
    if new_depth < current_depth:
        if new_depth == current_depth - 1 and new_list_type == current_type:
            # Continuing parent list at previous nesting level
            return False
        return True
    
    # Depth increases by more than 1 = split (new nesting context)
    if new_depth - current_depth > 1:
        return True
    
    # Depth increases by 1 with different type = split (nested list of different type)
    if new_depth - current_depth == 1 and new_list_type != current_type:
        return True
    
    return False


def infer_list_blocks(lines: List[dict]) -> CastDocument:
    """Process extracted lines and emit explicit list blocks.
    
    This is the main entry point for list inference. It processes
    normalized lines in order and produces a CastDocument with
    stable list blocks.
    
    Args:
        lines: List of line dicts with keys:
            - text: raw text content
            - x0: x-coordinate
            - y0: y-coordinate (for ordering)
            - html: pre-rendered HTML content
    
    Returns:
        CastDocument with inferred list blocks
    """
    if not lines:
        return CastDocument()
    
    # Sort lines by vertical position, then horizontal
    sorted_lines = sorted(lines, key=lambda x: (round(x.get("y0", 0), 2), x.get("x0", 0)))
    
    # Compute indentation parameters
    x_positions = [line.get("x0", 0) for line in sorted_lines]
    indent_unit = compute_indent_unit(x_positions)
    base_x0 = min(x_positions) if x_positions else 0.0
    
    document = CastDocument()
    current_block: Optional[ListBlock] = None
    block_counter = 0
    
    for line in sorted_lines:
        text = line.get("text", "")
        x0 = line.get("x0", 0.0)
        html_content = line.get("html", "")
        
        # Determine active list type for context
        active_type: Optional[ListType] = None
        if current_block:
            active_type = current_block.list_type
        
        # Classify the line
        kind = classify_line_kind(text, active_type)
        depth = infer_depth(x0, base_x0, indent_unit)
        
        if kind == "paragraph":
            # End current list block if any
            if current_block:
                document.blocks.append(current_block)
                current_block = None
            continue
        
        if kind == "continuation":
            # Append to current item if inside a list
            if current_block and current_block.items:
                # Append text to last item
                last_item = current_block.items[-1]
                last_item.text_html += " " + html_content
            continue
        
        # kind is ordered or unordered
        list_type: ListType = kind  # type: ignore
        
        # Check if we need to start a new block
        if current_block is None or should_split_block(
            current_block.list_type,
            current_block.depth_base,
            kind,
            depth
        ):
            # Save current block if exists
            if current_block:
                document.blocks.append(current_block)
            
            # Start new block
            block_counter += 1
            current_block = ListBlock(
                block_id=f"list-{block_counter}",
                list_type=list_type,
                depth_base=depth
            )
        
        # Extract marker details
        normalized_text = normalize_text(text)
        marker, _ = extract_marker(normalized_text)
        marker_kind = classify_marker_kind(marker)
        marker_value = parse_marker_value(marker, marker_kind)
        symbol = get_symbol_name(marker) if list_type == "unordered" else None
        
        # Create list item
        item = ListItem(
            text_html=html_content,
            depth=depth,
            list_type=list_type,
            marker_raw=marker,
            marker_kind=marker_kind,
            marker_value=marker_value,
            symbol=symbol,
            source_x0=x0,
            source_y0=line.get("y0", 0.0)
        )
        
        current_block.add_item(item)
    
    # Don't forget the last block
    if current_block:
        document.blocks.append(current_block)
    
    return document


def infer_list_blocks_from_spans(spans: List[dict]) -> CastDocument:
    """Alternative entry point working with raw PyMuPDF spans.
    
    Converts span-level data to line format before processing.
    
    Args:
        spans: List of span dicts from PyMuPDF extraction
    
    Returns:
        CastDocument with inferred list blocks
    """
    lines = []
    for span in spans:
        bbox = span.get("bbox", [0, 0, 0, 0])
        lines.append({
            "text": span.get("text", ""),
            "html": span.get("text", ""),  # Simple fallback
            "x0": bbox[0],
            "y0": bbox[1],
        })
    
    return infer_list_blocks(lines)
