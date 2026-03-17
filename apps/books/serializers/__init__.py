"""Books serializers package.

Exports all serializers for the books app.
"""

# Main serializers (from old serializers.py)
from apps.books.serializers.main import (
    BookFileSerializer,
    BookSerializer,
    MyBookSerializer,
    PageNoteSerializer,
    BookAuditLogSerializer,
    SavedPageSerializer,
    ReadingPositionSerializer,
)

# Theme serializers (from 38-01)
from apps.books.serializers.theme import (
    BookThemeSerializer,
)

__all__ = [
    # Main
    'BookFileSerializer',
    'BookSerializer',
    'MyBookSerializer',
    'PageNoteSerializer',
    'BookAuditLogSerializer',
    # Theme
    'BookThemeSerializer',
    # Saved pages
    'SavedPageSerializer',
    'ReadingPositionSerializer',
]
