"""DRF serializers for diagnostics data.

Provides serialization for Diagnostic and DiagnosticsReport dataclasses
for API responses.
"""

from rest_framework import serializers


class DiagnosticSerializer(serializers.Serializer):
    """Serializer for a single diagnostic item."""
    
    severity = serializers.ChoiceField(
        choices=[("warning", "Warning"), ("critical", "Critical")],
        read_only=True,
    )
    type = serializers.CharField(read_only=True)
    section_id = serializers.CharField(allow_null=True, read_only=True)
    message = serializers.CharField(read_only=True)
    action = serializers.ChoiceField(
        choices=[
            ("verify", "Verify"),
            ("reformat", "Reformat"),
            ("ignore", "Ignore"),
        ],
        read_only=True,
    )
    page = serializers.IntegerField(allow_null=True, read_only=True)
    location_hint = serializers.CharField(allow_null=True, read_only=True)


class DiagnosticsReportSerializer(serializers.Serializer):
    """Serializer for complete diagnostics report."""
    
    items = DiagnosticSerializer(many=True, read_only=True)
    summary = serializers.DictField(read_only=True)
    by_section = serializers.DictField(
        child=DiagnosticSerializer(many=True),
        read_only=True,
    )
    
    def to_representation(self, instance):
        """Override to handle both dataclass instances and dicts."""
        # Handle dataclass with to_dict method
        if hasattr(instance, 'to_dict'):
            data = instance.to_dict()
        else:
            data = instance
        
        # Ensure items is a list
        if 'items' not in data or data['items'] is None:
            data['items'] = []
        
        # Ensure summary exists
        if 'summary' not in data or data['summary'] is None:
            data['summary'] = {
                'total': 0,
                'by_severity': {'warning': 0, 'critical': 0},
                'by_type': {},
            }
        
        # Ensure by_section exists
        if 'by_section' not in data or data['by_section'] is None:
            data['by_section'] = {}
        
        return super().to_representation(data)
