"""
Shared serializer utilities and field naming conventions.

This module provides reusable serializer fields and documents the naming
conventions used across all API serializers.

## Field Naming Conventions

### Backend Model Fields (Django Convention)
- Use `snake_case` for all model fields
- Examples: `cover_image`, `view_count`, `created_at`

### Frontend-Facing Fields (JavaScript/TypeScript Convention)
- Use `camelCase` for fields that map directly to TypeScript interfaces
- Examples: `coverUrl`, `createdAt`, `bookTitle`

### Dual Field Naming Strategy
- Base fields use `snake_case` for API consistency
- Frontend aliases use `camelCase` as read-only SerializerMethodField
- Both field names appear in responses for backward compatibility

### Data Format Standards

#### Dates and Times
- All date/time fields use ISO 8601 format
- Use `format='iso-8601'` on DateTimeField serializers
- JavaScript can parse these directly with `new Date(isoString)`

#### Currency
- All monetary values stored as DecimalField (never FloatField)
- API responses format currency with ₾ prefix: "₾10.99"
- Use FormattedCurrencyField for consistent formatting

#### Booleans
- Boolean model fields serialize as native JSON booleans (true/false)
- Never use string representations ("true"/"false")
- DRF BooleanField handles this automatically

#### Image/File URLs
- All media URLs are absolute (include domain)
- Use AbsoluteURLField or SerializerMethodField with request context
- Return None (null in JSON) for missing images, not empty string

### Example Usage

```python
from rest_framework import serializers
from config.serializers import FormattedCurrencyField, AbsoluteURLField


class MySerializer(serializers.ModelSerializer):
    # Frontend alias for camelCase compatibility
    createdAt = serializers.DateTimeField(source='created_at', format='iso-8601')
    
    # Formatted currency field
    price = FormattedCurrencyField()
    
    # Absolute URL for images
    coverUrl = AbsoluteURLField(source='cover_image')
    
    class Meta:
        fields = ['id', 'created_at', 'createdAt', 'price', 'coverUrl']
```
"""

from decimal import Decimal, ROUND_HALF_UP

from rest_framework import serializers


class FormattedCurrencyField(serializers.Field):
    """
    Field that formats Decimal as ₾ string with 2 decimal places.
    
    Usage:
        price = FormattedCurrencyField()  # Uses source field name
        price = FormattedCurrencyField(source='amount')  # Custom source
    
    Output:
        "₾10.99"  # Always with ₾ prefix and exactly 2 decimal places
    """
    
    def to_representation(self, value):
        """Format Decimal as ₾ string with 2 decimal places."""
        if value is None:
            return None
        
        # Ensure we're working with a Decimal
        if not isinstance(value, Decimal):
            value = Decimal(str(value))
        
        # Quantize to 2 decimal places
        value = value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        
        return f'₾{value}'
    
    def to_internal_value(self, data):
        """Parse currency string back to Decimal."""
        if data is None:
            return None
        
        # Strip ₾ prefix if present
        if isinstance(data, str):
            data = data.strip()
            if data.startswith('₾'):
                data = data[1:]
            # Handle empty string after stripping
            if not data:
                return None
        
        try:
            return Decimal(data)
        except (ValueError, TypeError) as exc:
            raise serializers.ValidationError(
                f"Invalid currency format: {data}. Expected format: ₾10.99 or 10.99"
            ) from exc


class AbsoluteURLField(serializers.Field):
    """
    Field that generates absolute URLs for file/image fields with request context.
    
    Usage:
        coverUrl = AbsoluteURLField(source='cover_image')
        downloadUrl = AbsoluteURLField(source='file')
    
    Output:
        "http://localhost:8000/media/books/covers/2024/01/image.jpg"
        None  # If source field is empty
    """
    
    def __init__(self, source, **kwargs):
        """
        Initialize with source attribute name.
        
        Args:
            source: Name of the FileField/ImageField on the model
        """
        self.source = source
        super().__init__(**kwargs)
    
    def to_representation(self, value):
        """Generate absolute URL for file/image field."""
        if not value:
            return None
        
        # Get request from context for building absolute URI
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(value.url)
        
        # Fallback to relative URL if no request in context
        return value.url
    
    def to_internal_value(self, data):
        """This field is read-only."""
        raise serializers.ValidationError(
            "AbsoluteURLField is read-only. Use the source field directly for writes."
        )


class ISO8601DateTimeField(serializers.DateTimeField):
    """
    DateTimeField that always formats as ISO 8601.
    
    This is a convenience wrapper that sets format='iso-8601' by default.
    
    Usage:
        createdAt = ISO8601DateTimeField(source='created_at')
        updatedAt = ISO8601DateTimeField(source='updated_at')
    
    Output:
        "2024-01-15T10:30:00Z"
    """
    
    def __init__(self, **kwargs):
        kwargs.setdefault('format', 'iso-8601')
        super().__init__(**kwargs)


class BooleanField(serializers.BooleanField):
    """
    BooleanField with explicit JSON boolean output documentation.
    
    This field exists to document that booleans are serialized as native
    JSON booleans (true/false), not strings.
    
    Usage:
        is_featured = BooleanField()
        is_active = BooleanField(source='is_active')
    
    Output:
        true   # JSON boolean, not "true" string
        false  # JSON boolean, not "false" string
    """
    
    def to_representation(self, value):
        """Return native Python bool which JSON serializes as true/false."""
        return bool(value) if value is not None else None
