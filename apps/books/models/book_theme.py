"""Book theme mixin for per-book theming support.

This module provides BookThemeMixin which adds theme capabilities to the Book model.
Themes include Draft Studio style profiles: font, palette, animation, and layout.
"""

from typing import Any, Dict, Optional


class BookThemeMixin:
    """Mixin providing theme functionality for Book model.
    
    Provides theme constants, validation, and methods for getting/setting
    per-book theme configuration stored in JSONField.
    Supports both legacy (paper_background/font_family) and Draft Studio fields.
    """
    
    # Paper background options with their colors
    PAPER_BACKGROUNDS: Dict[str, Dict[str, str]] = {
        'parchment': {
            'color': '#f5e6c8',
            'text_color': '#4a3c28',
        },
        'white': {
            'color': '#ffffff',
            'text_color': '#1a1a1a',
        },
        'dark': {
            'color': '#1a1a2e',
            'text_color': '#e0e0e0',
        },
        'sepia': {
            'color': '#f4ecd8',
            'text_color': '#5c4b37',
        },
    }
    
    # Font family options with their CSS stacks
    FONT_FAMILIES: Dict[str, str] = {
        'serif': 'Georgia, "Times New Roman", serif',
        'sans': 'system-ui, -apple-system, sans-serif',
        'mtavruli': '"BPG Extrasquare Mtavruli", sans-serif',
    }

    # Valid Draft Studio option IDs
    VALID_FONT_IDS = ['bpg-mtavruli', 'vvpirikit', 'tfmecomicse', 'gf-alaverdi']
    VALID_PALETTE_IDS = ['paper-ivory', 'ink-night', 'sage', 'sunset', 'ocean-breeze', 'lavender-dream', 'autumn-leaf', 'obsidian']
    VALID_ANIMATION_IDS = ['none', 'flare', 'snow', 'vortex', 'sparkle']
    VALID_PAPER_IDS = ['clean', 'parchment', 'grain', 'notebook', 'vintage', 'blueprint']
    VALID_BACKGROUND_IDS = ['none', 'nature', 'galaxy', 'moon']
    
    # Default theme configuration (includes all Draft Studio fields)
    DEFAULT_THEME: Dict[str, Any] = {
        'paper_background': 'white',
        'font_family': 'mtavruli',
        # Draft Studio fields
        'font_id': 'bpg-mtavruli',
        'palette_id': 'paper-ivory',
        'animation_id': 'none',
        'paper_id': 'clean',
        'background_id': 'none',
        'base_font_size': 17,
        'line_height': 1.75,
        'letter_spacing': 0.01,
        'content_width': 740,
    }
    
    def get_theme(self) -> Dict[str, Any]:
        """Get the current theme configuration with defaults applied.
        
        Returns:
            Dict with all theme keys (legacy + Draft Studio).
            Uses defaults for any missing values.
        """
        stored_theme = getattr(self, 'theme_data', {}) or {}
        
        theme = {}
        for key, default_val in self.DEFAULT_THEME.items():
            theme[key] = stored_theme.get(key, default_val)
        
        return theme
    
    def set_theme(self, **kwargs) -> None:
        """Set theme configuration with validation.
        
        Accepts any known theme key as keyword argument.
        Unknown keys are silently ignored.
        
        Raises:
            ValueError: If provided values are not valid choices
        """
        current_theme = self.get_theme()
        
        # Legacy field validation
        if 'paper_background' in kwargs and kwargs['paper_background'] is not None:
            if kwargs['paper_background'] not in self.PAPER_BACKGROUNDS:
                valid_options = list(self.PAPER_BACKGROUNDS.keys())
                raise ValueError(
                    f"Invalid paper_background '{kwargs['paper_background']}'. "
                    f"Must be one of: {valid_options}"
                )
            current_theme['paper_background'] = kwargs['paper_background']
        
        if 'font_family' in kwargs and kwargs['font_family'] is not None:
            if kwargs['font_family'] not in self.FONT_FAMILIES:
                valid_options = list(self.FONT_FAMILIES.keys())
                raise ValueError(
                    f"Invalid font_family '{kwargs['font_family']}'. "
                    f"Must be one of: {valid_options}"
                )
            current_theme['font_family'] = kwargs['font_family']

        # Draft Studio fields (validated where applicable)
        if 'font_id' in kwargs and kwargs['font_id'] is not None:
            if kwargs['font_id'] not in self.VALID_FONT_IDS:
                raise ValueError(f"Invalid font_id '{kwargs['font_id']}'. Must be one of: {self.VALID_FONT_IDS}")
            current_theme['font_id'] = kwargs['font_id']

        if 'palette_id' in kwargs and kwargs['palette_id'] is not None:
            if kwargs['palette_id'] not in self.VALID_PALETTE_IDS:
                raise ValueError(f"Invalid palette_id '{kwargs['palette_id']}'. Must be one of: {self.VALID_PALETTE_IDS}")
            current_theme['palette_id'] = kwargs['palette_id']

        if 'animation_id' in kwargs and kwargs['animation_id'] is not None:
            if kwargs['animation_id'] not in self.VALID_ANIMATION_IDS:
                raise ValueError(f"Invalid animation_id '{kwargs['animation_id']}'. Must be one of: {self.VALID_ANIMATION_IDS}")
            current_theme['animation_id'] = kwargs['animation_id']

        if 'paper_id' in kwargs and kwargs['paper_id'] is not None:
            if kwargs['paper_id'] not in getattr(self, 'VALID_PAPER_IDS', ['clean', 'parchment', 'grain', 'notebook', 'vintage', 'blueprint']):
                raise ValueError(f"Invalid paper_id '{kwargs['paper_id']}'")
            current_theme['paper_id'] = kwargs['paper_id']

        if 'background_id' in kwargs and kwargs['background_id'] is not None:
            if kwargs['background_id'] not in getattr(self, 'VALID_BACKGROUND_IDS', ['none', 'nature', 'galaxy', 'moon']):
                raise ValueError(f"Invalid background_id '{kwargs['background_id']}'")
            current_theme['background_id'] = kwargs['background_id']

        # Numeric fields with range validation
        for field, min_v, max_v in [
            ('base_font_size', 14, 24),
            ('line_height', 1.0, 3.0),
            ('letter_spacing', 0, 0.1),
            ('content_width', 400, 1000),
        ]:
            if field in kwargs and kwargs[field] is not None:
                val = float(kwargs[field])
                if val < min_v or val > max_v:
                    raise ValueError(f"Invalid {field} '{val}'. Must be between {min_v} and {max_v}.")
                current_theme[field] = val
        
        self.theme_data = current_theme
        self.save(update_fields=['theme_data', 'updated_at'])
    
    def reset_theme(self) -> None:
        """Reset theme to default values."""
        self.theme_data = self.DEFAULT_THEME.copy()
        self.save(update_fields=['theme_data', 'updated_at'])
    
    def get_theme_colors(self) -> Dict[str, str]:
        """Get CSS-ready color values for the current theme.
        
        Returns:
            Dict with background_color and text_color for current paper_background
        """
        theme = self.get_theme()
        paper_bg = theme['paper_background']
        bg_config = self.PAPER_BACKGROUNDS.get(paper_bg, self.PAPER_BACKGROUNDS['white'])
        
        return {
            'background_color': bg_config['color'],
            'text_color': bg_config['text_color'],
        }
    
    def get_theme_font_stack(self) -> str:
        """Get CSS font stack for the current theme.
        
        Returns:
            CSS font-family value for current font_family setting
        """
        theme = self.get_theme()
        font_key = theme['font_family']
        return self.FONT_FAMILIES.get(font_key, self.FONT_FAMILIES['mtavruli'])
