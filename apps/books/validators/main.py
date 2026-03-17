"""
File validators for the books app.
"""

import zipfile

from PIL import Image
from django.core.exceptions import ValidationError


# Allowed file extensions (case-insensitive)
ALLOWED_EXTENSIONS = {'.pdf', '.epub'}

# Maximum file size: 100MB
MAX_FILE_SIZE = 100 * 1024 * 1024

# Allowed image extensions
ALLOWED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}

# Maximum image size: 5MB
MAX_IMAGE_SIZE = 5 * 1024 * 1024

# Maximum image dimensions
MAX_IMAGE_WIDTH = 2000
MAX_IMAGE_HEIGHT = 2000


def validate_file_extension(file):
    """
    Validate that the file has an allowed extension.
    
    Args:
        file: Django UploadedFile object
        
    Raises:
        ValidationError: If file extension is not .pdf or .epub
    """
    name = file.name.lower()
    if not any(name.endswith(ext) for ext in ALLOWED_EXTENSIONS):
        raise ValidationError("Only PDF and EPUB files are allowed.")


def validate_file_size(file):
    """
    Validate that the file size does not exceed the maximum limit.
    
    Args:
        file: Django UploadedFile object
        
    Raises:
        ValidationError: If file size exceeds 100MB
    """
    if file.size > MAX_FILE_SIZE:
        raise ValidationError("File size exceeds 100MB limit.")


def validate_file_type(file):
    """
    Comprehensive file validation including extension, size, and magic bytes.
    
    Checks:
    1. File extension is .pdf or .epub (case-insensitive)
    2. File size is 100MB or less
    3. File content matches extension (magic bytes check)
    
    Args:
        file: Django UploadedFile object
        
    Raises:
        ValidationError: If any validation fails
    """
    # First validate extension
    validate_file_extension(file)
    
    # Then validate size
    validate_file_size(file)
    
    # Finally validate magic bytes
    _validate_magic_bytes(file)


def _validate_magic_bytes(file):
    """
    Validate file content matches extension using magic bytes.
    
    PDF: Starts with %PDF
    EPUB: ZIP file (PK\x03\x04) with .epub extension
    
    Args:
        file: Django UploadedFile object
        
    Raises:
        ValidationError: If magic bytes don't match expected format
    """
    # Read first few bytes to check magic numbers
    file.seek(0)
    magic_bytes = file.read(8)
    file.seek(0)  # Reset file pointer
    
    # Check if it's a PDF (starts with %PDF)
    if magic_bytes.startswith(b'%PDF'):
        if not file.name.lower().endswith('.pdf'):
            raise ValidationError("File content does not match extension.")
        return
    
    # Check if it's a ZIP file (EPUB is a ZIP archive)
    # ZIP magic bytes: PK\x03\x04 or PK\x05\x06
    if magic_bytes.startswith(b'PK\x03\x04') or magic_bytes.startswith(b'PK\x05\x06'):
        if not file.name.lower().endswith('.epub'):
            raise ValidationError("File content does not match extension.")
        # Verify the EPUB-specific mimetype entry so that arbitrary ZIPs
        # (e.g. .docx, .jar) renamed to .epub are rejected early with a clean
        # 400 rather than a cryptic extraction failure downstream.
        try:
            with zipfile.ZipFile(file, 'r') as zf:
                try:
                    mimetype_value = zf.read('mimetype').strip()
                except KeyError:
                    raise ValidationError(
                        "File does not appear to be a valid EPUB: missing 'mimetype' entry."
                    )
                if mimetype_value != b'application/epub+zip':
                    raise ValidationError(
                        "File does not appear to be a valid EPUB: incorrect mimetype value."
                    )
        except ValidationError:
            raise
        except Exception:
            raise ValidationError("File does not appear to be a valid EPUB archive.")
        finally:
            file.seek(0)
        return
    
    # If we get here, the file type is not recognized
    raise ValidationError("File content does not match extension.")


def validate_image_type(file):
    """
    Validate that the file is an allowed image type.
    
    Checks:
    1. File extension is in allowed list (.jpg, .jpeg, .png, .gif, .webp)
    2. File content is a valid image (using Pillow)
    
    Args:
        file: Django UploadedFile object
        
    Raises:
        ValidationError: If file is not a valid image type
    """
    # Check file extension
    name = file.name.lower()
    if not any(name.endswith(ext) for ext in ALLOWED_IMAGE_EXTENSIONS):
        raise ValidationError(
            "Only JPG, JPEG, PNG, GIF, and WEBP images are allowed."
        )
    
    # Verify it's a valid image using Pillow
    try:
        file.seek(0)
        with Image.open(file) as img:
            img.verify()  # Verify it's a valid image
        file.seek(0)  # Reset file pointer
    except Exception:
        raise ValidationError("Invalid image file.")


def validate_image_size(file, max_size=MAX_IMAGE_SIZE):
    """
    Validate that the image file size does not exceed the maximum limit.
    
    Args:
        file: Django UploadedFile object
        max_size: Maximum allowed size in bytes (default: 5MB)
        
    Raises:
        ValidationError: If file size exceeds the limit
    """
    if file.size > max_size:
        raise ValidationError("Image size must not exceed 5MB.")


def validate_image_dimensions(file, max_width=MAX_IMAGE_WIDTH, max_height=MAX_IMAGE_HEIGHT):
    """
    Validate that image dimensions do not exceed maximum limits.
    
    Args:
        file: Django UploadedFile object
        max_width: Maximum allowed width in pixels (default: 2000)
        max_height: Maximum allowed height in pixels (default: 2000)
        
    Raises:
        ValidationError: If image dimensions exceed limits
    """
    try:
        file.seek(0)
        with Image.open(file) as img:
            width, height = img.size
            if width > max_width or height > max_height:
                raise ValidationError(
                    f"Image dimensions must not exceed {max_width}x{max_height} pixels."
                )
        file.seek(0)  # Reset file pointer
    except ValidationError:
        raise
    except Exception:
        # If we can't open the image, let validate_image_type catch it
        pass


def validate_image(file):
    """
    Comprehensive image validation including type, size, and dimensions.
    
    Checks:
    1. File extension is in allowed image types
    2. File is a valid image (Pillow verification)
    3. File size is 5MB or less
    4. Image dimensions are within limits (optional)
    
    Args:
        file: Django UploadedFile object
        
    Raises:
        ValidationError: If any validation fails
    """
    # Validate image type (extension + content)
    validate_image_type(file)
    
    # Validate file size
    validate_image_size(file)
    
    # Validate dimensions
    validate_image_dimensions(file)
