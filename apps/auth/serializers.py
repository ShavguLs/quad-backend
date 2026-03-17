from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed

from apps.users.models import User, normalize_handle


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False)
    password = serializers.CharField(required=False, write_only=True, trim_whitespace=False)
    firstName = serializers.CharField(required=False, allow_blank=True)
    lastName = serializers.CharField(required=False, allow_blank=True)
    handle = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        missing_fields = []
        for field in ["email", "password", "firstName", "lastName", "handle"]:
            value = attrs.get(field)
            if value is None or (isinstance(value, str) and not value.strip()):
                missing_fields.append(field)

        if missing_fields:
            field = missing_fields[0]
            messages = {
                "email": "Email is required.",
                "password": "Password is required.",
                "firstName": "First name is required.",
                "lastName": "Last name is required.",
                "handle": "Handle is required.",
            }
            raise serializers.ValidationError({"error": messages[field]})

        email = User.objects.normalize_email(attrs["email"]).strip()
        handle = attrs["handle"].strip()
        first_name = attrs["firstName"].strip()
        last_name = attrs["lastName"].strip()
        handle_normalized = normalize_handle(handle)

        if User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError({"error": "Email is already in use."})
        if User.objects.filter(handle_normalized=handle_normalized).exists():
            raise serializers.ValidationError({"error": "Handle is already in use."})

        try:
            validate_password(attrs["password"])
        except DjangoValidationError as exc:
            message = exc.messages[0] if exc.messages else "Password is invalid."
            raise serializers.ValidationError({"error": message})

        attrs["email"] = email
        attrs["handle"] = handle
        attrs["firstName"] = first_name
        attrs["lastName"] = last_name
        return attrs

    def create(self, validated_data):
        return User.objects.create_user(
            email=validated_data["email"],
            password=validated_data["password"],
            first_name=validated_data["firstName"],
            last_name=validated_data["lastName"],
            handle=validated_data["handle"],
        )


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False)
    password = serializers.CharField(required=False, write_only=True, trim_whitespace=False)

    def validate(self, attrs):
        email = attrs.get("email")
        password = attrs.get("password")

        if not email or not str(email).strip():
            raise serializers.ValidationError({"error": "Email is required."})
        if not password or not str(password).strip():
            raise serializers.ValidationError({"error": "Password is required."})

        email = User.objects.normalize_email(email).strip()
        user = User.objects.filter(email__iexact=email).first()
        if not user or not user.check_password(password):
            raise AuthenticationFailed({"error": "Invalid email or password."})
        if not user.is_active:
            raise AuthenticationFailed({"error": "Account is disabled."})

        attrs["user"] = user
        return attrs
