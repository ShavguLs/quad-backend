"""Books views package.

Exports all views for the books app.
"""

# Main views (from old views.py)
from apps.books.views.main import (
    BookViewSet,
    PageNoteViewSet,
    ReadingPositionView,
)

# Theme views (from 38-01)
from apps.books.views.theme import (
    BookThemeViewSet,
)

__all__ = [
    # Main
    'BookViewSet',
    'PageNoteViewSet',
    'ReadingPositionView',
    # Theme
    'BookThemeViewSet',
]
