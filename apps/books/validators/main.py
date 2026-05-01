"""
Image validators for the books app.
"""

from PIL import Image
from django.core.exceptions import ValidationError


# Allowed image extensions
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

# Maximum image size: 5MB
MAX_IMAGE_SIZE = 5 * 1024 * 1024

# Maximum image dimensions
MAX_IMAGE_WIDTH = 2000
MAX_IMAGE_HEIGHT = 2000


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
        raise ValidationError("Only JPG, JPEG, PNG, GIF, and WEBP images are allowed.")

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


def validate_image_dimensions(
    file, max_width=MAX_IMAGE_WIDTH, max_height=MAX_IMAGE_HEIGHT
):
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
