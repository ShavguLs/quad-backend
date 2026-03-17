"""Content block type definitions for structured JSONB storage.

Provides typed dataclass definitions for content blocks stored in BookContent.
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Literal
from enum import Enum


class BlockType(Enum):
    """Types of content blocks."""
    PARAGRAPH = "paragraph"
    HEADING = "heading"
    LIST_ITEM = "list_item"
    IMAGE = "image"
    PAGE_BREAK = "page_break"


@dataclass
class BlockPosition:
    """Position information for a block."""
    start: int = 0  # Character offset in page content
    end: int = 0
    page_x: Optional[float] = None  # Original PDF coordinates
    page_y: Optional[float] = None


@dataclass
class BlockFormatting:
    """Formatting metadata for text blocks."""
    bold: bool = False
    italic: bool = False
    font_size: Optional[float] = None
    font_family: Optional[str] = None
    alignment: Literal["left", "center", "right", "justify"] = "left"
    line_height: Optional[float] = None
    color: Optional[str] = None  # CSS color


@dataclass
class BlockMetadata:
    """Metadata about block origin and quality.

    The `source` field determines how the block is processed:
    - 'extraction': Auto-extracted from PDF, may use heading heuristics for display
    - 'manual': Created/edited by user in draft editor, preserves exact user intent
    - 'import': Imported from external source, may use heuristics
    """
    source: Literal["extraction", "manual", "import"] = "manual"
    confidence: float = 1.0  # Extraction confidence (0-1)
    created_at: Optional[str] = None  # ISO timestamp
    modified_at: Optional[str] = None


@dataclass
class ContentBlock:
    """Base content block structure."""
    id: str  # Unique block identifier
    type: BlockType
    position: BlockPosition = field(default_factory=BlockPosition)
    metadata: BlockMetadata = field(default_factory=BlockMetadata)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "id": self.id,
            "type": self.type.value,
            "position": {
                "start": self.position.start,
                "end": self.position.end,
                "page_x": self.position.page_x,
                "page_y": self.position.page_y,
            },
            "metadata": {
                "source": self.metadata.source,
                "confidence": self.metadata.confidence,
                "created_at": self.metadata.created_at,
                "modified_at": self.metadata.modified_at,
            }
        }


@dataclass
class ParagraphBlock(ContentBlock):
    """Paragraph text block."""
    text: str = ""
    formatting: BlockFormatting = field(default_factory=BlockFormatting)
    
    def __post_init__(self):
        if not self.type:
            self.type = BlockType.PARAGRAPH
    
    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        data.update({
            "text": self.text,
            "formatting": {
                "bold": self.formatting.bold,
                "italic": self.formatting.italic,
                "font_size": self.formatting.font_size,
                "font_family": self.formatting.font_family,
                "alignment": self.formatting.alignment,
                "line_height": self.formatting.line_height,
                "color": self.formatting.color,
            }
        })
        return data


@dataclass
class HeadingBlock(ContentBlock):
    """Heading block with level."""
    text: str = ""
    level: int = 1  # 1-6
    formatting: BlockFormatting = field(default_factory=BlockFormatting)
    
    def __post_init__(self):
        if not self.type:
            self.type = BlockType.HEADING
        self.formatting.bold = True
    
    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        data.update({
            "text": self.text,
            "level": self.level,
            "formatting": {
                "bold": self.formatting.bold,
                "italic": self.formatting.italic,
                "font_size": self.formatting.font_size,
                "font_family": self.formatting.font_family,
                "alignment": self.formatting.alignment,
                "line_height": self.formatting.line_height,
                "color": self.formatting.color,
            }
        })
        return data


@dataclass
class ImageBlock(ContentBlock):
    """Image reference block."""
    image_id: str = ""  # Reference to ExtractedImage or DraftImageAsset
    xref: Optional[int] = None  # Original PDF xref
    caption: str = ""
    width: Optional[int] = None
    height: Optional[int] = None
    
    def __post_init__(self):
        if not self.type:
            self.type = BlockType.IMAGE
    
    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        data.update({
            "image_id": self.image_id,
            "xref": self.xref,
            "caption": self.caption,
            "metadata": {
                **data.get("metadata", {}),
                "width": self.width,
                "height": self.height,
            }
        })
        return data


@dataclass
class ListItemBlock(ContentBlock):
    """List item block."""
    text: str = ""
    list_type: Literal["ordered", "unordered"] = "unordered"
    list_index: int = 0
    formatting: BlockFormatting = field(default_factory=BlockFormatting)
    
    def __post_init__(self):
        if not self.type:
            self.type = BlockType.LIST_ITEM
    
    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        data.update({
            "text": self.text,
            "list_type": self.list_type,
            "list_index": self.list_index,
            "formatting": {
                "bold": self.formatting.bold,
                "italic": self.formatting.italic,
            }
        })
        return data


@dataclass
class PageBreakBlock(ContentBlock):
    """Page break marker."""
    
    def __post_init__(self):
        if not self.type:
            self.type = BlockType.PAGE_BREAK
    
    def to_dict(self) -> Dict[str, Any]:
        return super().to_dict()


def block_from_extraction(extracted_block) -> ContentBlock:
    """Create ContentBlock from Phase 35 extraction result.
    
    This is a placeholder factory function that will be fully implemented
    when integration with extraction results is needed.
    """
    # Generate unique ID based on position
    block_id = f"blk_{extracted_block.x0:.0f}_{extracted_block.y0:.0f}"
    
    position = BlockPosition(
        start=0,  # Will be calculated based on page context
        end=0,
        page_x=extracted_block.x0,
        page_y=extracted_block.y0
    )
    
    metadata = BlockMetadata(
        source="extraction",
        confidence=0.9
    )
    
    # Determine block type from extracted block
    if hasattr(extracted_block, 'block_type') and extracted_block.block_type == "heading":
        text = " ".join(line.text for line in extracted_block.lines) if hasattr(extracted_block, 'lines') else ""
        formatting = BlockFormatting(
            bold=any(line.is_bold for line in extracted_block.lines) if hasattr(extracted_block, 'lines') else False,
            italic=any(line.is_italic for line in extracted_block.lines) if hasattr(extracted_block, 'lines') else False,
            font_size=max((line.size for line in extracted_block.lines), default=12.0) if hasattr(extracted_block, 'lines') else 12.0
        )
        return HeadingBlock(
            id=block_id,
            type=BlockType.HEADING,
            level=getattr(extracted_block, 'heading_level', 1),
            text=text,
            position=position,
            formatting=formatting,
            metadata=metadata
        )
    else:
        text = " ".join(line.text for line in extracted_block.lines) if hasattr(extracted_block, 'lines') else ""
        sizes = [line.size for line in extracted_block.lines] if hasattr(extracted_block, 'lines') else []
        formatting = BlockFormatting(
            bold=any(line.is_bold for line in extracted_block.lines) if hasattr(extracted_block, 'lines') else False,
            italic=any(line.is_italic for line in extracted_block.lines) if hasattr(extracted_block, 'lines') else False,
            font_size=sorted(sizes)[len(sizes)//2] if sizes else 12.0  # median
        )
        return ParagraphBlock(
            id=block_id,
            type=BlockType.PARAGRAPH,
            text=text,
            position=position,
            formatting=formatting,
            metadata=metadata
        )
