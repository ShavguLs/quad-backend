"""
Library app configuration.
"""

from django.apps import AppConfig


class LibraryConfig(AppConfig):
    """Configuration for the library app."""
    
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.library'
    verbose_name = 'Library'
    
    def ready(self):
        """Called when the app is ready."""
        pass
