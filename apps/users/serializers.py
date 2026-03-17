from django.core.validators import FileExtensionValidator
from rest_framework import serializers

from config.serializers import ISO8601DateTimeField

from .models import User


class DisplayNameField(serializers.Field):
    def to_representation(self, obj):
        display_name = (getattr(obj, "display_name", None) or "").strip()
        if display_name:
            return display_name
        first = (getattr(obj, "first_name", "") or "").strip()
        last = (getattr(obj, "last_name", "") or "").strip()
        full = " ".join(part for part in [first, last] if part)
        return full or None

    def to_internal_value(self, data):
        if data is None:
            return {"display_name": None}
        if not isinstance(data, str):
            raise serializers.ValidationError("Name must be a string.")
        return {"display_name": data.strip()}


class ProfileImageField(serializers.ImageField):
    """Custom ImageField that returns absolute URLs and validates image uploads."""

    # Valid image extensions
    ALLOWED_EXTENSIONS = ["jpg", "jpeg", "png", "webp"]
    # Maximum file size: 5MB
    MAX_FILE_SIZE = 5 * 1024 * 1024

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Add file extension validator
        self.validators.append(
            FileExtensionValidator(allowed_extensions=self.ALLOWED_EXTENSIONS)
        )

    def to_internal_value(self, data):
        """Handle incoming image file with size validation."""
        # Let parent class handle basic file validation
        file_obj = super().to_internal_value(data)

        # Validate file size
        if file_obj and hasattr(file_obj, "size"):
            if file_obj.size > self.MAX_FILE_SIZE:
                raise serializers.ValidationError(
                    f"Image file too large. Maximum size is {self.MAX_FILE_SIZE // (1024 * 1024)}MB."
                )

        return file_obj

    def to_representation(self, value):
        if not value:
            return None
        request = self.context.get("request")
        url = value.url
        return request.build_absolute_uri(url) if request else url


class UserSerializer(serializers.ModelSerializer):
    name = DisplayNameField(source="*", read_only=True)
    createdAt = ISO8601DateTimeField(source="created_at")
    profile_image = ProfileImageField(read_only=True)
    profileImage = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "name",
            "handle",
            "bio",
            "profile_image",
            "profileImage",
            "createdAt",
        ]
        extra_kwargs = {
            "email": {"required": False, "allow_null": True},
            "handle": {"required": False, "allow_null": True},
            "bio": {"required": False, "allow_null": True, "allow_blank": True},
        }

    def get_profileImage(self, obj):
        return self.fields["profile_image"].to_representation(obj.profile_image)


class ProfileSerializer(serializers.ModelSerializer):
    name = DisplayNameField(source="*", required=False)
    createdAt = ISO8601DateTimeField(source="created_at", read_only=True)
    profile_image = ProfileImageField(required=False, allow_null=True)
    profileImage = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "name",
            "handle",
            "bio",
            "profile_image",
            "profileImage",
            "createdAt",
        ]
        extra_kwargs = {
            "email": {"read_only": True},
            "handle": {"read_only": True},
            "bio": {"required": False, "allow_null": True, "allow_blank": True},
        }

    def get_profileImage(self, obj):
        return self.fields["profile_image"].to_representation(obj.profile_image)
