"""Deterministic contract-to-HTML renderer for list blocks.

This module provides a stable HTML adapter that receives canonical cast blocks
and emits semantic, deterministic HTML for lists. It preserves ordered/unordered
semantics, nesting depth, and marker metadata via data attributes.

Key features:
- Nested <ol>/<ul>/<li> structure based on list type and depth
- Deterministic output (same input always produces byte-equivalent HTML)
- Metadata preservation via data-cast-* attributes
- Support for ordered list start values and marker kind tracking
"""

from __future__ import annotations

import html
from typing import List, Optional

from .casting_contract import (
    CAST_DOC_SCHEMA_VERSION,
    CAST_LIST_SCHEMA_VERSION,
    CastDocument,
    ListBlock,
    ListItem,
    ListType,
    ParagraphBlock,
)


def _escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return html.escape(text)


def render_paragraph_block_to_html(
    block: ParagraphBlock,
    include_metadata: bool = True
) -> str:
    """Render a ParagraphBlock to styled HTML.

    Args:
        block: The ParagraphBlock to render
        include_metadata: Whether to include data-cast-* attributes

    Returns:
        HTML string with appropriate tag and inline styles
    """
    tag = block.tag
    style = block.style

    # Build attribute lists
    attrs = []
    styles = []

    if include_metadata:
        attrs.append(f'data-cast-version="{CAST_DOC_SCHEMA_VERSION}"')
        attrs.append(f'data-cast-block-id="{block.block_id}"')
        attrs.append(f'data-cast-tag="{tag}"')

    # Style attributes
    if style.align != "left":
        styles.append(f"text-align:{style.align}")
    if style.color:
        styles.append(f"color:{style.color}")
    if style.font_size:
        styles.append(f"font-size:{style.font_size:.1f}px")
    if block.margin_bottom > 0:
        styles.append(f"margin-bottom:{block.margin_bottom}px")

    # Heading-specific styles
    if tag.startswith("h"):
        styles.append("line-height:1.25")
        if style.is_bold:
            styles.append("font-weight:700")
    else:
        styles.append("line-height:1.4")

    # Build final attribute strings
    attr_str = " " + " ".join(attrs) if attrs else ""
    style_str = f' style="{";".join(styles)}"' if styles else ""

    return f"<{tag}{attr_str}{style_str}>{block.text_html}</{tag}>"


def _render_list_item(
    item: ListItem,
    indent: str = "",
    include_metadata: bool = True
) -> str:
    """Render a single list item as HTML <li>.
    
    Args:
        item: The ListItem to render
        indent: Indentation string for formatting
        include_metadata: Whether to include data-cast-* attributes
    
    Returns:
        HTML string for the list item
    """
    attrs = []
    
    if include_metadata:
        # Core metadata attributes
        attrs.append(f'data-cast-depth="{item.depth}"')
        attrs.append(f'data-cast-marker-kind="{item.marker_kind}"')
        attrs.append(f'data-cast-marker-raw="{_escape_html(item.marker_raw)}"')
        
        # Optional symbol metadata for unordered lists
        if item.symbol:
            attrs.append(f'data-cast-symbol="{item.symbol}"')
        
        # Optional value metadata for ordered lists
        if item.marker_value is not None:
            attrs.append(f'data-cast-value="{item.marker_value}"')
    
    attr_str = " " + " ".join(attrs) if attrs else ""
    
    # Use the pre-rendered HTML content
    content = item.text_html
    
    return f"{indent}<li{attr_str}>{content}</li>"


def _render_list_container(
    list_type: ListType,
    items_html: List[str],
    block: ListBlock,
    indent: str = "",
    include_metadata: bool = True
) -> str:
    """Render a list container (<ol> or <ul>) with items.
    
    Args:
        list_type: ordered or unordered
        items_html: List of rendered <li> strings
        block: The ListBlock for metadata
        indent: Indentation string for formatting
        include_metadata: Whether to include data-cast-* attributes
    
    Returns:
        HTML string for the list container
    """
    tag = "ol" if list_type == "ordered" else "ul"
    attrs = []
    
    if include_metadata:
        # Core metadata
        attrs.append(f'data-cast-version="{CAST_LIST_SCHEMA_VERSION}"')
        attrs.append(f'data-cast-marker-kind="{block.items[0].marker_kind if block.items else "unknown"}"')
        
        # Start value for ordered lists (if not 1)
        if list_type == "ordered" and block.start_value != 1:
            attrs.append(f'start="{block.start_value}"')
    
    attr_str = " " + " ".join(attrs) if attrs else ""
    
    # Build container with nested items
    lines = [f"{indent}<{tag}{attr_str}>"]
    for item_html in items_html:
        lines.append(item_html)
    lines.append(f"{indent}</{tag}>")
    
    return "\n".join(lines)


def _group_items_by_depth(block: ListBlock) -> List[List[ListItem]]:
    """Group items by their nesting depth for hierarchical rendering.
    
    Returns a list of depth groups, where each group contains items
    at that depth level that should be rendered together.
    
    Args:
        block: The ListBlock to group
    
    Returns:
        List of item groups by depth
    """
    if not block.items:
        return []
    
    # Group consecutive items at the same depth
    groups = []
    current_group = [block.items[0]]
    current_depth = block.items[0].depth
    
    for item in block.items[1:]:
        if item.depth == current_depth:
            current_group.append(item)
        else:
            groups.append(current_group)
            current_group = [item]
            current_depth = item.depth
    
    if current_group:
        groups.append(current_group)
    
    return groups


def _render_nested_list(
    block: ListBlock,
    base_indent: str = "",
    include_metadata: bool = True
) -> str:
    """Render a list block with proper nesting.
    
    Handles nested structures by tracking depth changes and creating
    appropriate nested <ol>/<ul> containers.
    
    Args:
        block: The ListBlock to render
        base_indent: Base indentation string
        include_metadata: Whether to include data-cast-* attributes
    
    Returns:
        HTML string for the nested list structure
    """
    if not block.items:
        return ""
    
    list_type = block.list_type
    tag = "ol" if list_type == "ordered" else "ul"
    
    # Build nested structure
    lines = []
    current_depth = block.depth_base
    
    # Container attributes (only on root container)
    attrs = []
    if include_metadata:
        attrs.append(f'data-cast-version="{CAST_LIST_SCHEMA_VERSION}"')
        attrs.append(f'data-cast-marker-kind="{block.items[0].marker_kind}"')
        if list_type == "ordered" and block.start_value != 1:
            attrs.append(f'start="{block.start_value}"')
    
    attr_str = " " + " ".join(attrs) if attrs else ""
    
    # Track open containers
    open_containers = 0
    
    for i, item in enumerate(block.items):
        item_depth = item.depth
        
        # Handle depth changes
        if item_depth > current_depth:
            # Opening nested containers
            depth_diff = item_depth - current_depth
            for j in range(depth_diff):
                # First container gets attributes
                container_attrs = attr_str if (open_containers == 0 and j == 0) else ""
                lines.append(f"{base_indent}{'  ' * open_containers}<{tag}{container_attrs}>")
                open_containers += 1
        elif item_depth < current_depth:
            # Closing containers
            for _ in range(current_depth - item_depth):
                if open_containers > 0:
                    open_containers -= 1
                    lines.append(f"{base_indent}{'  ' * open_containers}</{tag}>")
                    if open_containers > 0:
                        lines.append(f"{base_indent}{'  ' * open_containers}</li>")
        elif i == 0:
            # First item at base depth - open root container
            lines.append(f"{base_indent}<{tag}{attr_str}>")
            open_containers = 1
        
        current_depth = item_depth
        indent = base_indent + "  " * (open_containers - 1) if open_containers > 0 else base_indent
        
        # Render item attributes
        item_attrs = []
        if include_metadata:
            item_attrs.append(f'data-cast-depth="{item.depth}"')
            item_attrs.append(f'data-cast-marker-kind="{item.marker_kind}"')
            item_attrs.append(f'data-cast-marker-raw="{_escape_html(item.marker_raw)}"')
            if item.symbol:
                item_attrs.append(f'data-cast-symbol="{item.symbol}"')
            if item.marker_value is not None:
                item_attrs.append(f'data-cast-value="{item.marker_value}"')
        
        item_attr_str = " " + " ".join(item_attrs) if item_attrs else ""
        
        # Check if next item is at deeper depth (has children)
        has_children = (i + 1 < len(block.items) and block.items[i + 1].depth > item_depth)
        
        if has_children:
            # Item with nested content - don't close li yet
            lines.append(f"{indent}<li{item_attr_str}>{item.text_html}")
        else:
            # Simple item - close immediately
            lines.append(f"{indent}<li{item_attr_str}>{item.text_html}</li>")
    
    # Close remaining containers
    while open_containers > 0:
        open_containers -= 1
        indent = base_indent + "  " * open_containers if open_containers > 0 else base_indent
        lines.append(f"{indent}</{tag}>")
        if open_containers > 0:
            lines.append(f"{indent}</li>")
    
    return "\n".join(lines)


def render_cast_blocks_to_html(
    document: CastDocument,
    include_metadata: bool = True
) -> str:
    """Render a CastDocument to semantic HTML.

    This is the main entry point for converting canonical cast blocks
    to stable, deterministic HTML output. Supports mixed list and
    paragraph content.

    Args:
        document: The CastDocument to render
        include_metadata: Whether to include data-cast-* attributes

    Returns:
        HTML string with semantic markup
    """
    if not document.blocks:
        return ""

    html_parts = []

    for block in document.blocks:
        if isinstance(block, ListBlock):
            if not block.items:
                continue
            block_html = _render_nested_list(block, include_metadata=include_metadata)
            if block_html:
                html_parts.append(block_html)
        elif isinstance(block, ParagraphBlock):
            block_html = render_paragraph_block_to_html(block, include_metadata=include_metadata)
            if block_html:
                html_parts.append(block_html)
        # Future: handle other block types here

    return "\n\n".join(html_parts)


def render_list_block_to_html(
    block: ListBlock,
    include_metadata: bool = True
) -> str:
    """Render a single ListBlock to HTML.
    
    Convenience function for rendering individual blocks.
    
    Args:
        block: The ListBlock to render
        include_metadata: Whether to include data-cast-* attributes
    
    Returns:
        HTML string for the list block
    """
    return _render_nested_list(block, include_metadata=include_metadata)


def render_simple_list(
    items: List[str],
    list_type: ListType = "unordered",
    start: int = 1
) -> str:
    """Render a simple list from text items (convenience function).
    
    This is a simplified interface for cases where full contract
    metadata is not needed.
    
    Args:
        items: List of text items
        list_type: ordered or unordered
        start: Starting number for ordered lists
    
    Returns:
        HTML string for the simple list
    """
    tag = "ol" if list_type == "ordered" else "ul"
    attrs = []
    
    if list_type == "ordered" and start != 1:
        attrs.append(f'start="{start}"')
    
    attr_str = " " + " ".join(attrs) if attrs else ""
    
    lines = [f"<{tag}{attr_str}>"]
    for item in items:
        escaped = _escape_html(item)
        lines.append(f"  <li>{escaped}</li>")
    lines.append(f"</{tag}>")
    
    return "\n".join(lines)
