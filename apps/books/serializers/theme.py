"""Book theme serializers.

Provides BookThemeSerializer for theme data serialization and validation.
Supports both legacy (paper_background/font_family) and Draft Studio fields.
"""

from rest_framework import serializers


class BookThemeSerializer(serializers.Serializer):
    """Serializer for book theme configuration.

    Validates and serializes theme data including legacy fields and
    Draft Studio style profile (font, palette, animation, layout).
    """

    # Legacy fields
    PAPER_BACKGROUNDS = {
        'parchment': {'color': '#f5e6c8', 'text_color': '#4a3c28'},
        'white': {'color': '#ffffff', 'text_color': '#1a1a1a'},
        'dark': {'color': '#1a1a2e', 'text_color': '#e0e0e0'},
        'sepia': {'color': '#f4ecd8', 'text_color': '#5c4b37'},
    }

    FONT_FAMILIES = {
        'serif': 'Georgia, "Times New Roman", serif',
        'sans': 'system-ui, -apple-system, sans-serif',
        'mtavruli': '"BPG Extrasquare Mtavruli", sans-serif',
    }

    # Valid Draft Studio IDs
    VALID_FONT_IDS = ['bpg-mtavruli', 'vvpirikit', 'tfmecomicse', 'gf-alaverdi']
    VALID_PALETTE_IDS = ['paper-ivory', 'ink-night', 'sage', 'sunset', 'ocean-breeze', 'lavender-dream', 'autumn-leaf', 'obsidian']
    VALID_ANIMATION_IDS = ['none', 'flare', 'snow', 'vortex', 'sparkle']
    VALID_PAPER_IDS = ['clean', 'parchment', 'grain', 'notebook', 'vintage', 'blueprint']
    VALID_BACKGROUND_IDS = ['none', 'nature', 'galaxy', 'moon']

    # Legacy serializer fields
    paper_background = serializers.ChoiceField(
        choices=list(PAPER_BACKGROUNDS.keys()),
        default='white',
        required=False,
        help_text='Paper background theme choice',
    )
    font_family = serializers.ChoiceField(
        choices=list(FONT_FAMILIES.keys()),
        default='mtavruli',
        required=False,
        help_text='Font family theme choice',
    )

    # Draft Studio fields
    font_id = serializers.ChoiceField(
        choices=VALID_FONT_IDS,
        default='bpg-mtavruli',
        required=False,
        help_text='Draft Studio font profile ID',
    )
    palette_id = serializers.ChoiceField(
        choices=VALID_PALETTE_IDS,
        default='paper-ivory',
        required=False,
        help_text='Draft Studio color palette ID',
    )
    animation_id = serializers.ChoiceField(
        choices=VALID_ANIMATION_IDS,
        default='none',
        required=False,
        help_text='Draft Studio animation effect ID',
    )
    paper_id = serializers.ChoiceField(
        choices=VALID_PAPER_IDS,
        default='clean',
        required=False,
        help_text='Draft Studio paper texture ID',
    )
    background_id = serializers.ChoiceField(
        choices=VALID_BACKGROUND_IDS,
        default='none',
        required=False,
        help_text='Draft Studio background image ID',
    )
    base_font_size = serializers.FloatField(
        default=17,
        required=False,
        min_value=14,
        max_value=24,
        help_text='Base font size in pixels',
    )
    line_height = serializers.FloatField(
        default=1.75,
        required=False,
        min_value=1.0,
        max_value=3.0,
        help_text='Line height multiplier',
    )
    letter_spacing = serializers.FloatField(
        default=0.01,
        required=False,
        min_value=0,
        max_value=0.1,
        help_text='Letter spacing in em',
    )
    content_width = serializers.FloatField(
        default=740,
        required=False,
        min_value=400,
        max_value=1000,
        help_text='Maximum content width in pixels',
    )

    # Computed field
    css_variables = serializers.SerializerMethodField(
        help_text='Computed CSS variables for frontend',
    )

    # All known fields for easy iteration
    DEFAULTS = {
        'paper_background': 'white',
        'font_family': 'mtavruli',
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

    def get_css_variables(self, obj: dict) -> dict:
        """Generate CSS variables from theme configuration."""
        paper_bg = obj.get('paper_background', 'white')
        font_family = obj.get('font_family', 'mtavruli')

        bg_config = self.PAPER_BACKGROUNDS.get(paper_bg, self.PAPER_BACKGROUNDS['white'])
        font_stack = self.FONT_FAMILIES.get(font_family, self.FONT_FAMILIES['mtavruli'])

        return {
            '--book-bg-color': bg_config['color'],
            '--book-text-color': bg_config['text_color'],
            '--book-font-family': font_stack,
        }

    def to_representation(self, instance: dict) -> dict:
        """Convert theme dict to serializable representation."""
        if not isinstance(instance, dict):
            instance = {}

        data = {}
        for key, default_val in self.DEFAULTS.items():
            data[key] = instance.get(key, default_val)

        data['css_variables'] = self.get_css_variables(data)
        return data

    def to_internal_value(self, data: dict) -> dict:
        """Convert input data to internal representation with validation."""
        result = {}

        # Legacy fields
        if 'paper_background' in data:
            if data['paper_background'] not in self.PAPER_BACKGROUNDS:
                raise serializers.ValidationError({
                    'paper_background': f"Invalid choice. Must be one of: {list(self.PAPER_BACKGROUNDS.keys())}"
                })
            result['paper_background'] = data['paper_background']

        if 'font_family' in data:
            if data['font_family'] not in self.FONT_FAMILIES:
                raise serializers.ValidationError({
                    'font_family': f"Invalid choice. Must be one of: {list(self.FONT_FAMILIES.keys())}"
                })
            result['font_family'] = data['font_family']

        # Draft Studio choice fields
        choice_fields = {
            'font_id': self.VALID_FONT_IDS,
            'palette_id': self.VALID_PALETTE_IDS,
            'animation_id': self.VALID_ANIMATION_IDS,
            'paper_id': self.VALID_PAPER_IDS,
            'background_id': self.VALID_BACKGROUND_IDS,
        }
        for field, valid_values in choice_fields.items():
            if field in data:
                if data[field] not in valid_values:
                    raise serializers.ValidationError({
                        field: f"Invalid choice. Must be one of: {valid_values}"
                    })
                result[field] = data[field]

        # Numeric fields
        numeric_fields = {
            'base_font_size': (14, 24),
            'line_height': (1.0, 3.0),
            'letter_spacing': (0, 0.1),
            'content_width': (400, 1000),
        }
        for field, (min_v, max_v) in numeric_fields.items():
            if field in data:
                try:
                    val = float(data[field])
                except (TypeError, ValueError):
                    raise serializers.ValidationError({
                        field: f"Must be a number between {min_v} and {max_v}."
                    })
                if val < min_v or val > max_v:
                    raise serializers.ValidationError({
                        field: f"Must be between {min_v} and {max_v}."
                    })
                result[field] = val

        return result
