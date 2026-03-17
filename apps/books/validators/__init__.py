"""Books validators package.

Exports all validators for the books app.
"""

# Main validators (from old validators.py)
from apps.books.validators.main import (
    ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE,
    ALLOWED_IMAGE_EXTENSIONS,
    MAX_IMAGE_SIZE,
    MAX_IMAGE_WIDTH,
    MAX_IMAGE_HEIGHT,
    validate_file_extension,
    validate_file_size,
    validate_file_type,
    validate_image_type,
    validate_image_size,
    validate_image_dimensions,
    validate_image,
)

# Content validators (from 36-01)
from apps.books.validators.content import (
    validate_blocks,
    BLOCK_SCHEMA,
    validate_block_types,
    sanitize_blocks,
    get_block_statistics,
)

__all__ = [
    # Main
    'ALLOWED_EXTENSIONS',
    'MAX_FILE_SIZE',
    'ALLOWED_IMAGE_EXTENSIONS',
    'MAX_IMAGE_SIZE',
    'MAX_IMAGE_WIDTH',
    'MAX_IMAGE_HEIGHT',
    'validate_file_extension',
    'validate_file_size',
    'validate_file_type',
    'validate_image_type',
    'validate_image_size',
    'validate_image_dimensions',
    'validate_image',
    # Content
    'validate_blocks',
    'BLOCK_SCHEMA',
    'validate_block_types',
    'sanitize_blocks',
    'get_block_statistics',
]
