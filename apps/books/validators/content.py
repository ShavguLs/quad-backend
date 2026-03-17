"""JSON schema validation for content blocks.

Validates content block structures before storage to ensure data integrity.
"""

from typing import List, Dict, Any, Optional
from django.core.exceptions import ValidationError

# JSON Schema for content blocks
BLOCK_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "array",
    "items": {
        "type": "object",
        "required": ["id", "type"],
        "properties": {
            "id": {
                "type": "string",
                "description": "Unique block identifier"
            },
            "type": {
                "type": "string",
                "enum": ["paragraph", "heading", "list_item", "image", "page_break"],
                "description": "Block type classification"
            },
            "text": {
                "type": "string",
                "description": "Text content for text-based blocks"
            },
            "level": {
                "type": "integer",
                "minimum": 1,
                "maximum": 6,
                "description": "Heading level (1-6) for heading blocks"
            },
            "position": {
                "type": "object",
                "properties": {
                    "start": {"type": "integer"},
                    "end": {"type": "integer"},
                    "page_x": {"type": ["number", "null"]},
                    "page_y": {"type": ["number", "null"]}
                }
            },
            "formatting": {
                "type": "object",
                "properties": {
                    "bold": {"type": "boolean"},
                    "italic": {"type": "boolean"},
                    "font_size": {"type": ["number", "null"]},
                    "font_family": {"type": ["string", "null"]},
                    "alignment": {
                        "type": "string",
                        "enum": ["left", "center", "right", "justify"]
                    },
                    "line_height": {"type": ["number", "null"]},
                    "color": {"type": ["string", "null"]}
                }
            },
            "metadata": {
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "enum": ["extraction", "manual", "import"]
                    },
                    "confidence": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1
                    },
                    "created_at": {"type": ["string", "null"]},
                    "modified_at": {"type": ["string", "null"]}
                }
            },
            # Image block specific fields
            "image_id": {
                "type": "string",
                "description": "Reference to ExtractedImage or DraftImageAsset"
            },
            "xref": {
                "type": ["integer", "null"],
                "description": "Original PDF xref identifier"
            },
            "caption": {
                "type": "string",
                "description": "Image caption text"
            },
            # List item specific fields
            "list_type": {
                "type": "string",
                "enum": ["ordered", "unordered"],
                "description": "List type for list_item blocks"
            },
            "list_index": {
                "type": "integer",
                "description": "Index within the list"
            }
        },
        "additionalProperties": True
    }
}

# Type-specific validation rules
TYPE_VALIDATION_RULES = {
    "paragraph": {
        "recommended_fields": ["text"],
        "text_required": True
    },
    "heading": {
        "required_fields": ["text", "level"],
        "text_required": True
    },
    "list_item": {
        "recommended_fields": ["text", "list_type"],
        "text_required": True
    },
    "image": {
        "recommended_fields": ["image_id"],
        "text_required": False
    },
    "page_break": {
        "recommended_fields": [],
        "text_required": False
    }
}


def validate_blocks(blocks: List[Dict[str, Any]], strict: bool = False) -> bool:
    """
    Validate content blocks against JSON schema.
    
    Args:
        blocks: List of block dictionaries to validate
        strict: If True, enforces type-specific recommended fields
        
    Returns:
        True if validation passes
        
    Raises:
        ValidationError: If blocks fail schema validation
    """
    try:
        import jsonschema
    except ImportError:
        raise ValidationError(
            "jsonschema package is required for block validation. "
            "Install with: pip install jsonschema"
        )
    
    if not isinstance(blocks, list):
        raise ValidationError(f"Blocks must be a list, got {type(blocks).__name__}")
    
    # Validate against schema
    try:
        jsonschema.validate(blocks, BLOCK_SCHEMA)
    except jsonschema.ValidationError as e:
        # Build a clear error message
        path = "/".join(str(p) for p in e.path) if e.path else "root"
        message = f"Block validation failed at '{path}': {e.message}"
        raise ValidationError(message)
    
    # Type-specific validation
    if strict:
        for i, block in enumerate(blocks):
            block_type = block.get("type")
            rules = TYPE_VALIDATION_RULES.get(block_type, {})
            
            # Check required fields for type
            for field in rules.get("required_fields", []):
                if field not in block:
                    raise ValidationError(
                        f"Block {i} (type={block_type}) missing required field: {field}"
                    )
            
            # Check text requirement
            if rules.get("text_required") and not block.get("text"):
                raise ValidationError(
                    f"Block {i} (type={block_type}) must have non-empty text"
                )
    
    return True


def validate_block_types(blocks: List[Dict[str, Any]]) -> List[str]:
    """
    Check for unknown block types.
    
    Args:
        blocks: List of block dictionaries
        
    Returns:
        List of unknown block type values found
    """
    valid_types = {"paragraph", "heading", "list_item", "image", "page_break"}
    unknown_types = set()
    
    for block in blocks:
        block_type = block.get("type")
        if block_type and block_type not in valid_types:
            unknown_types.add(block_type)
    
    return list(unknown_types)


def sanitize_blocks(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Sanitize blocks by removing invalid fields and ensuring required structure.
    
    Args:
        blocks: Raw block data
        
    Returns:
        Sanitized blocks
    """
    sanitized = []
    
    for block in blocks:
        if not isinstance(block, dict):
            continue
            
        # Ensure required fields
        block_id = block.get("id") or f"blk_{len(sanitized)}"
        block_type = block.get("type") or "paragraph"
        
        # Only allow valid types
        if block_type not in {"paragraph", "heading", "list_item", "image", "page_break"}:
            block_type = "paragraph"
        
        clean_block = {
            "id": str(block_id),
            "type": block_type,
        }
        
        # Copy optional fields if present and valid
        if "text" in block and isinstance(block["text"], str):
            clean_block["text"] = block["text"]
        
        if "level" in block and isinstance(block["level"], int) and 1 <= block["level"] <= 6:
            clean_block["level"] = block["level"]
        
        if "position" in block and isinstance(block["position"], dict):
            clean_block["position"] = block["position"]
        
        if "formatting" in block and isinstance(block["formatting"], dict):
            clean_block["formatting"] = block["formatting"]
        
        if "metadata" in block and isinstance(block["metadata"], dict):
            clean_block["metadata"] = block["metadata"]
        
        # Image-specific fields
        if block_type == "image":
            if "image_id" in block:
                clean_block["image_id"] = str(block["image_id"])
            if "xref" in block:
                clean_block["xref"] = int(block["xref"]) if block["xref"] else None
            if "caption" in block:
                clean_block["caption"] = str(block["caption"])
        
        # List item specific fields
        if block_type == "list_item":
            if "list_type" in block and block["list_type"] in {"ordered", "unordered"}:
                clean_block["list_type"] = block["list_type"]
            if "list_index" in block and isinstance(block["list_index"], int):
                clean_block["list_index"] = block["list_index"]
        
        sanitized.append(clean_block)
    
    return sanitized


def get_block_statistics(blocks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Get statistics about blocks.
    
    Args:
        blocks: List of block dictionaries
        
    Returns:
        Dictionary with block statistics
    """
    stats = {
        "total_blocks": len(blocks),
        "by_type": {},
        "has_images": False,
        "has_headings": False,
        "word_count": 0
    }
    
    for block in blocks:
        block_type = block.get("type", "unknown")
        stats["by_type"][block_type] = stats["by_type"].get(block_type, 0) + 1
        
        if block_type == "image":
            stats["has_images"] = True
        elif block_type == "heading":
            stats["has_headings"] = True
        
        # Count words in text blocks
        if block_type in ("paragraph", "heading", "list_item"):
            text = block.get("text", "")
            if text:
                stats["word_count"] += len(text.split())
    
    return stats
