from unittest.mock import patch

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.middleware.csrf import get_token
from django.urls import reverse
from rest_framework import permissions, status
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, APITestCase
from rest_framework.views import APIView
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
from rest_framework_simplejwt.tokens import RefreshToken

from apps.auth.authentication import CookieJWTAuthentication
from apps.auth.serializers import LoginSerializer, RegisterSerializer
from apps.auth.views import LoginView, LogoutView, MeView, RefreshView, RegisterView

User = get_user_model()

pytestmark = [pytest.mark.unit, pytest.mark.django_db]


def get_error_message(errors, key="error"):
    """Helper to extract error message from DRF error format."""
    if key in errors:
        error = errors[key]
        if isinstance(error, list):
            return str(error[0])
        return str(error)
    return str(errors)


def attach_csrf(request):
    request._dont_enforce_csrf_checks = False
    csrf_token = get_token(request)
    request.COOKIES[settings.CSRF_COOKIE_NAME] = csrf_token
    request.META["HTTP_X_CSRFTOKEN"] = csrf_token
    return csrf_token


class ProtectedWriteView(APIView):
    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        return Response({"ok": True}, status=status.HTTP_200_OK)


class TestRegisterSerializer:
    """Unit tests for RegisterSerializer."""

    def test_valid_registration_data(self):
        """Test serializer with valid registration data."""
        data = {
            "email": "newuser@example.com",
            "password": "SecurePass123!",
            "firstName": "John",
            "lastName": "Doe",
            "handle": "johndoe",
        }
        serializer = RegisterSerializer(data=data)
        assert serializer.is_valid() is True
        validated = serializer.validated_data
        assert validated["email"] == "newuser@example.com"
        assert validated["firstName"] == "John"
        assert validated["lastName"] == "Doe"
        assert validated["handle"] == "johndoe"

    def test_email_normalization(self):
        """Test email domain is normalized to lowercase."""
        data = {
            "email": "Test.User@EXAMPLE.COM",
            "password": "SecurePass123!",
            "firstName": "John",
            "lastName": "Doe",
            "handle": "johndoe",
        }
        serializer = RegisterSerializer(data=data)
        assert serializer.is_valid() is True
        # Django's normalize_email lowercases the domain only
        assert serializer.validated_data["email"] == "Test.User@example.com"

    def test_missing_email(self):
        """Test validation fails when email is missing."""
        data = {
            "password": "SecurePass123!",
            "firstName": "John",
            "lastName": "Doe",
            "handle": "johndoe",
        }
        serializer = RegisterSerializer(data=data)
        assert serializer.is_valid() is False
        assert "error" in serializer.errors
        assert "Email is required" in get_error_message(serializer.errors)

    def test_missing_password(self):
        """Test validation fails when password is missing."""
        data = {
            "email": "test@example.com",
            "firstName": "John",
            "lastName": "Doe",
            "handle": "johndoe",
        }
        serializer = RegisterSerializer(data=data)
        assert serializer.is_valid() is False
        assert "error" in serializer.errors
        assert "Password is required" in get_error_message(serializer.errors)

    @pytest.mark.parametrize("field", ["firstName", "lastName", "handle"])
    def test_missing_required_fields(self, field):
        """Test validation fails when required fields are missing."""
        data = {
            "email": "test@example.com",
            "password": "SecurePass123!",
            "firstName": "John",
            "lastName": "Doe",
            "handle": "johndoe",
        }
        del data[field]
        serializer = RegisterSerializer(data=data)
        assert serializer.is_valid() is False
        assert "error" in serializer.errors

    @pytest.mark.parametrize("field", ["password", "firstName", "lastName", "handle"])
    def test_empty_string_fields(self, field):
        """Test validation fails when fields contain only whitespace."""
        data = {
            "email": "test@example.com",
            "password": "SecurePass123!",
            "firstName": "John",
            "lastName": "Doe",
            "handle": "johndoe",
        }
        data[field] = "   "
        serializer = RegisterSerializer(data=data)
        assert serializer.is_valid() is False
        assert "error" in serializer.errors

    def test_empty_email_whitespace(self):
        """Test empty email fails - DRF handles blank check before custom validation."""
        data = {
            "email": "   ",
            "password": "SecurePass123!",
            "firstName": "John",
            "lastName": "Doe",
            "handle": "johndoe",
        }
        serializer = RegisterSerializer(data=data)
        assert serializer.is_valid() is False
        # EmailField trims whitespace, so it becomes blank and fails DRF validation
        assert "email" in serializer.errors or "error" in serializer.errors

    def test_duplicate_email(self):
        """Test validation fails when email already exists."""
        User.objects.create_user(
            email="existing@example.com",
            password="password123",
            first_name="Existing",
            last_name="User",
            handle="existing",
        )
        data = {
            "email": "existing@example.com",
            "password": "SecurePass123!",
            "firstName": "John",
            "lastName": "Doe",
            "handle": "newhandle",
        }
        serializer = RegisterSerializer(data=data)
        assert serializer.is_valid() is False
        assert "error" in serializer.errors
        assert "Email is already in use" in get_error_message(serializer.errors)

    def test_duplicate_email_case_insensitive(self):
        """Test email uniqueness check is case-insensitive."""
        User.objects.create_user(
            email="Existing@Example.COM",
            password="password123",
            first_name="Existing",
            last_name="User",
            handle="existing",
        )
        data = {
            "email": "EXISTING@EXAMPLE.COM",
            "password": "SecurePass123!",
            "firstName": "John",
            "lastName": "Doe",
            "handle": "newhandle",
        }
        serializer = RegisterSerializer(data=data)
        assert serializer.is_valid() is False
        assert "Email is already in use" in get_error_message(serializer.errors)

    def test_duplicate_handle(self):
        """Test validation fails when handle already exists."""
        User.objects.create_user(
            email="user1@example.com",
            password="password123",
            first_name="User",
            last_name="One",
            handle="testhandle",
        )
        data = {
            "email": "user2@example.com",
            "password": "SecurePass123!",
            "firstName": "John",
            "lastName": "Doe",
            "handle": "testhandle",
        }
        serializer = RegisterSerializer(data=data)
        assert serializer.is_valid() is False
        assert "error" in serializer.errors
        assert "Handle is already in use" in get_error_message(serializer.errors)

    def test_weak_password(self):
        """Test validation fails with weak password."""
        data = {
            "email": "test@example.com",
            "password": "123",
            "firstName": "John",
            "lastName": "Doe",
            "handle": "johndoe",
        }
        serializer = RegisterSerializer(data=data)
        assert serializer.is_valid() is False
        assert "error" in serializer.errors

    def test_handle_whitespace_stripping(self):
        """Test handle whitespace is stripped during validation."""
        data = {
            "email": "test@example.com",
            "password": "SecurePass123!",
            "firstName": "John",
            "lastName": "Doe",
            "handle": "  johndoe  ",
        }
        serializer = RegisterSerializer(data=data)
        assert serializer.is_valid() is True
        assert serializer.validated_data["handle"] == "johndoe"

    def test_create_user(self):
        """Test serializer creates user correctly."""
        data = {
            "email": "create@example.com",
            "password": "SecurePass123!",
            "firstName": "Create",
            "lastName": "User",
            "handle": "createuser",
        }
        serializer = RegisterSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        assert user.email == "create@example.com"
        assert user.first_name == "Create"
        assert user.last_name == "User"
        assert user.handle == "createuser"
        assert user.check_password("SecurePass123!")


class TestLoginSerializer:
    """Unit tests for LoginSerializer."""

    @pytest.fixture
    def user(self):
        """Create a test user for login tests."""
        return User.objects.create_user(
            email="login@example.com",
            password="SecurePass123!",
            first_name="Login",
            last_name="User",
            handle="loginuser",
        )

    def test_valid_credentials(self, user):
        """Test serializer with valid credentials."""
        data = {
            "email": "login@example.com",
            "password": "SecurePass123!",
        }
        serializer = LoginSerializer(data=data)
        assert serializer.is_valid() is True
        assert serializer.validated_data["user"] == user

    def test_email_case_insensitive(self, user):
        """Test login works with different email case."""
        data = {
            "email": "LOGIN@EXAMPLE.COM",
            "password": "SecurePass123!",
        }
        serializer = LoginSerializer(data=data)
        assert serializer.is_valid() is True
        assert serializer.validated_data["user"] == user

    def test_missing_email(self):
        """Test validation fails when email is missing."""
        data = {"password": "SecurePass123!"}
        serializer = LoginSerializer(data=data)
        assert serializer.is_valid() is False
        assert "error" in serializer.errors
        assert "Email is required" in get_error_message(serializer.errors)

    def test_empty_email(self):
        """Test validation fails with empty/whitespace email - DRF trims first."""
        data = {"email": "   ", "password": "SecurePass123!"}
        serializer = LoginSerializer(data=data)
        assert serializer.is_valid() is False
        # EmailField trims whitespace, so it becomes blank and fails DRF validation
        # or custom validation catches the empty value
        error_msg = get_error_message(serializer.errors) if "error" in serializer.errors else str(serializer.errors)
        assert "required" in error_msg.lower() or "blank" in error_msg.lower()

    def test_missing_password(self):
        """Test validation fails when password is missing."""
        data = {"email": "test@example.com"}
        serializer = LoginSerializer(data=data)
        assert serializer.is_valid() is False
        assert "error" in serializer.errors
        assert "Password is required" in get_error_message(serializer.errors)

    def test_empty_password(self):
        """Test validation fails with empty/whitespace password."""
        data = {"email": "test@example.com", "password": "   "}
        serializer = LoginSerializer(data=data)
        assert serializer.is_valid() is False
        error_msg = get_error_message(serializer.errors) if "error" in serializer.errors else str(serializer.errors)
        assert "Password is required" in error_msg

    def test_invalid_credentials_wrong_password(self, user):
        """Test authentication fails with wrong password."""
        data = {
            "email": "login@example.com",
            "password": "WrongPassword123!",
        }
        serializer = LoginSerializer(data=data)
        with pytest.raises(AuthenticationFailed) as exc_info:
            serializer.is_valid(raise_exception=True)
        assert "Invalid email or password" in str(exc_info.value.detail)

    def test_invalid_credentials_nonexistent_user(self):
        """Test authentication fails with non-existent user."""
        data = {
            "email": "nonexistent@example.com",
            "password": "SecurePass123!",
        }
        serializer = LoginSerializer(data=data)
        with pytest.raises(AuthenticationFailed) as exc_info:
            serializer.is_valid(raise_exception=True)
        assert "Invalid email or password" in str(exc_info.value.detail)

    def test_inactive_user(self, user):
        """Test authentication fails for inactive user."""
        user.is_active = False
        user.save()
        data = {
            "email": "login@example.com",
            "password": "SecurePass123!",
        }
        serializer = LoginSerializer(data=data)
        with pytest.raises(AuthenticationFailed) as exc_info:
            serializer.is_valid(raise_exception=True)
        assert "Account is disabled" in str(exc_info.value.detail)


class TestRegisterView:
    """Unit tests for RegisterView."""

    def setup_method(self):
        self.factory = APIRequestFactory()
        self.view = RegisterView.as_view()

    def test_register_success(self):
        """Test successful user registration."""
        data = {
            "email": "register@example.com",
            "password": "SecurePass123!",
            "firstName": "Register",
            "lastName": "User",
            "handle": "registeruser",
        }
        request = self.factory.post("/auth/register", data, format="json")
        attach_csrf(request)
        response = self.view(request)

        assert response.status_code == status.HTTP_201_CREATED
        assert "user" in response.data
        assert response.data["user"]["email"] == "register@example.com"
        assert response.data["user"]["handle"] == "registeruser"
        assert settings.AUTH_ACCESS_COOKIE_NAME in response.cookies
        assert settings.AUTH_REFRESH_COOKIE_NAME in response.cookies

        # Verify user was created
        user = User.objects.get(email="register@example.com")
        assert user is not None
        assert user.check_password("SecurePass123!")

    def test_register_validation_error(self):
        """Test registration with invalid data returns 400."""
        data = {
            "email": "invalid-email",
            "password": "SecurePass123!",
            "firstName": "Test",
            "lastName": "User",
            "handle": "testuser",
        }
        request = self.factory.post("/auth/register", data, format="json")
        attach_csrf(request)
        response = self.view(request)

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_register_missing_fields(self):
        """Test registration with missing fields returns 400."""
        data = {"email": "test@example.com"}
        request = self.factory.post("/auth/register", data, format="json")
        attach_csrf(request)
        response = self.view(request)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "error" in response.data

    def test_register_duplicate_email(self):
        """Test registration with duplicate email returns 400."""
        User.objects.create_user(
            email="duplicate@example.com",
            password="password123",
            first_name="Existing",
            last_name="User",
            handle="existing",
        )
        data = {
            "email": "duplicate@example.com",
            "password": "SecurePass123!",
            "firstName": "Test",
            "lastName": "User",
            "handle": "newhandle",
        }
        request = self.factory.post("/auth/register", data, format="json")
        attach_csrf(request)
        response = self.view(request)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        error_data = response.data.get("error", [])
        if isinstance(error_data, list):
            error_data = error_data[0] if error_data else ""
        assert "Email is already in use" in str(error_data)


class TestLoginView:
    """Unit tests for LoginView."""

    def setup_method(self):
        self.factory = APIRequestFactory()
        self.view = LoginView.as_view()
        self.user = User.objects.create_user(
            email="logintest@example.com",
            password="SecurePass123!",
            first_name="Login",
            last_name="Test",
            handle="logintest",
        )

    def test_login_success(self):
        """Test successful login returns user and sets auth cookies."""
        data = {
            "email": "logintest@example.com",
            "password": "SecurePass123!",
        }
        request = self.factory.post("/auth/login", data, format="json")
        attach_csrf(request)
        response = self.view(request)

        assert response.status_code == status.HTTP_200_OK
        assert "user" in response.data
        assert response.data["user"]["email"] == "logintest@example.com"
        assert settings.AUTH_ACCESS_COOKIE_NAME in response.cookies
        assert settings.AUTH_REFRESH_COOKIE_NAME in response.cookies

    def test_login_sets_refresh_cookie_path_compatible_with_logout(self):
        """Test refresh cookie path allows browser to send it to /auth/logout."""
        data = {
            "email": "logintest@example.com",
            "password": "SecurePass123!",
        }
        request = self.factory.post("/auth/login", data, format="json")
        attach_csrf(request)
        response = self.view(request)

        assert response.status_code == status.HTTP_200_OK
        refresh_cookie_path = response.cookies[settings.AUTH_REFRESH_COOKIE_NAME]["path"]
        assert refresh_cookie_path == "/auth"

    def test_login_invalid_credentials(self):
        """Test login with invalid credentials returns 401."""
        data = {
            "email": "logintest@example.com",
            "password": "WrongPassword123!",
        }
        request = self.factory.post("/auth/login", data, format="json")
        attach_csrf(request)
        response = self.view(request)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert "error" in response.data

    def test_login_missing_fields(self):
        """Test login with missing fields returns 400."""
        data = {"email": "logintest@example.com"}
        request = self.factory.post("/auth/login", data, format="json")
        attach_csrf(request)
        response = self.view(request)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "error" in response.data

    def test_login_inactive_user(self):
        """Test login for inactive user returns 401."""
        self.user.is_active = False
        self.user.save()
        data = {
            "email": "logintest@example.com",
            "password": "SecurePass123!",
        }
        request = self.factory.post("/auth/login", data, format="json")
        attach_csrf(request)
        response = self.view(request)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Account is disabled" in response.data["error"]


class TestMeView:
    """Unit tests for MeView."""

    def setup_method(self):
        self.factory = APIRequestFactory()
        self.view = MeView.as_view()
        self.user = User.objects.create_user(
            email="me@example.com",
            password="SecurePass123!",
            first_name="Me",
            last_name="User",
            handle="meuser",
        )

    def test_get_me_authenticated(self):
        """Test authenticated user can get their profile."""
        from rest_framework.test import force_authenticate
        request = self.factory.get("/auth/me")
        force_authenticate(request, user=self.user)
        response = self.view(request)

        assert response.status_code == status.HTTP_200_OK
        assert "user" in response.data
        assert response.data["user"]["email"] == "me@example.com"
        assert response.data["user"]["handle"] == "meuser"

    def test_get_me_unauthenticated(self):
        """Test unauthenticated request is rejected."""
        from django.contrib.auth.models import AnonymousUser

        request = self.factory.get("/auth/me")
        request.user = AnonymousUser()
        response = self.view(request)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestLogoutView:
    """Unit tests for LogoutView."""

    def setup_method(self):
        self.factory = APIRequestFactory()
        self.view = LogoutView.as_view()
        self.user = User.objects.create_user(
            email="logout@example.com",
            password="SecurePass123!",
            first_name="Logout",
            last_name="User",
            handle="logoutuser",
        )

    def test_logout_authenticated(self):
        """Test authenticated user can logout."""
        from rest_framework.test import force_authenticate
        request = self.factory.post("/auth/logout")
        attach_csrf(request)
        force_authenticate(request, user=self.user)
        response = self.view(request)

        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_logout_unauthenticated(self):
        """Test unauthenticated request still clears cookies and succeeds."""
        request = self.factory.post("/auth/logout")
        attach_csrf(request)
        response = self.view(request)

        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_logout_blacklist_failure_returns_500(self):
        """Test logout surfaces server-side blacklist failures."""
        refresh_token = str(RefreshToken.for_user(self.user))
        request = self.factory.post("/auth/logout")
        attach_csrf(request)
        request.COOKIES[settings.AUTH_REFRESH_COOKIE_NAME] = refresh_token

        with patch.object(RefreshToken, "blacklist", side_effect=Exception("db unavailable")):
            response = self.view(request)

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert response.data["detail"] == "Failed to invalidate refresh token."
        # APIRequestFactory bypasses browser cookie-path scoping, so this check only
        # verifies deletion headers, not that the browser would have sent the cookie.
        assert response.cookies[settings.AUTH_ACCESS_COOKIE_NAME]["max-age"] == 0
        assert response.cookies[settings.AUTH_REFRESH_COOKIE_NAME]["max-age"] == 0


class TestRefreshView:
    """Unit tests for RefreshView error handling."""

    def setup_method(self):
        self.factory = APIRequestFactory()
        self.view = RefreshView.as_view()
        self.user = User.objects.create_user(
            email="refresh@example.com",
            password="SecurePass123!",
            first_name="Refresh",
            last_name="User",
            handle="refreshuser",
        )

    def test_refresh_with_invalid_token_returns_401_and_clears_cookies(self):
        """Test refresh with a malformed token returns 401 and clears auth cookies."""
        request = self.factory.post("/auth/refresh")
        attach_csrf(request)
        request.COOKIES[settings.AUTH_REFRESH_COOKIE_NAME] = "not.a.valid.token"
        response = self.view(request)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.data["detail"] == "Refresh token is invalid or has been revoked."
        assert response.cookies[settings.AUTH_ACCESS_COOKIE_NAME]["max-age"] == 0
        assert response.cookies[settings.AUTH_REFRESH_COOKIE_NAME]["max-age"] == 0

    def test_refresh_with_non_jwt_string_returns_401(self):
        """Test refresh with non-JWT string is handled as an auth failure."""
        request = self.factory.post("/auth/refresh")
        attach_csrf(request)
        request.COOKIES[settings.AUTH_REFRESH_COOKIE_NAME] = "not-a-jwt"
        response = self.view(request)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.data["detail"] == "Refresh token is invalid or has been revoked."

    def test_refresh_db_failure_returns_500_and_clears_cookies(self):
        """Test refresh surfaces unexpected server errors and clears auth cookies."""
        from rest_framework_simplejwt.serializers import TokenRefreshSerializer

        refresh_token = str(RefreshToken.for_user(self.user))
        request = self.factory.post("/auth/refresh")
        attach_csrf(request)
        request.COOKIES[settings.AUTH_REFRESH_COOKIE_NAME] = refresh_token

        with patch.object(TokenRefreshSerializer, "is_valid", side_effect=Exception("db unavailable")):
            response = self.view(request)

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert response.data["detail"] == "Failed to refresh access token."
        assert response.cookies[settings.AUTH_ACCESS_COOKIE_NAME]["max-age"] == 0
        assert response.cookies[settings.AUTH_REFRESH_COOKIE_NAME]["max-age"] == 0

    def test_refresh_missing_token_returns_400(self):
        """Test refresh without any token returns 400."""
        request = self.factory.post("/auth/refresh")
        attach_csrf(request)
        response = self.view(request)

        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestAuthIntegration(APITestCase):
    """Integration tests for auth endpoints using APIClient."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="integration@example.com",
            password="SecurePass123!",
            first_name="Integration",
            last_name="User",
            handle="integration",
        )

    def _load_csrf(self):
        csrf_response = self.client.get(reverse("auth-csrf"))
        assert csrf_response.status_code == status.HTTP_200_OK
        return csrf_response.data["csrfToken"]

    def test_register_endpoint(self):
        """Test full registration endpoint flow."""
        url = reverse("auth-register")
        csrf_token = self._load_csrf()
        data = {
            "email": "newintegration@example.com",
            "password": "SecurePass123!",
            "firstName": "New",
            "lastName": "Integration",
            "handle": "newintegration",
        }
        response = self.client.post(url, data, format="json", HTTP_X_CSRFTOKEN=csrf_token)

        assert response.status_code == status.HTTP_201_CREATED
        assert User.objects.filter(email="newintegration@example.com").exists()
        assert settings.AUTH_ACCESS_COOKIE_NAME in response.cookies
        assert settings.AUTH_REFRESH_COOKIE_NAME in response.cookies

    def test_login_endpoint(self):
        """Test full login endpoint flow sets cookies."""
        url = reverse("auth-login")
        csrf_token = self._load_csrf()
        data = {
            "email": "integration@example.com",
            "password": "SecurePass123!",
        }
        response = self.client.post(url, data, format="json", HTTP_X_CSRFTOKEN=csrf_token)

        assert response.status_code == status.HTTP_200_OK
        assert "user" in response.data
        assert settings.AUTH_ACCESS_COOKIE_NAME in response.cookies
        assert settings.AUTH_REFRESH_COOKIE_NAME in response.cookies

    def test_me_endpoint_cookie_authenticated(self):
        """Test /me endpoint with access token cookie."""
        access = str(RefreshToken.for_user(self.user).access_token)
        self.client.cookies[settings.AUTH_ACCESS_COOKIE_NAME] = access

        url = reverse("auth-me")
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["user"]["email"] == "integration@example.com"

    def test_me_endpoint_authenticated(self):
        """Test /me endpoint with authentication."""
        self.client.force_authenticate(user=self.user)
        url = reverse("auth-me")
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["user"]["email"] == "integration@example.com"

    def test_me_endpoint_unauthenticated(self):
        """Test /me endpoint without authentication."""
        url = reverse("auth-me")
        response = self.client.get(url)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_logout_endpoint_authenticated(self):
        """Test logout endpoint with authentication."""
        csrf_token = self._load_csrf()
        self.client.force_authenticate(user=self.user)
        url = reverse("auth-logout")
        response = self.client.post(url, HTTP_X_CSRFTOKEN=csrf_token)

        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_logout_endpoint_blacklists_refresh_token(self):
        """Test logout blacklists refresh token from cookie."""
        csrf_token = self._load_csrf()
        login_url = reverse("auth-login")
        login_data = {
            "email": "integration@example.com",
            "password": "SecurePass123!",
        }
        login_response = self.client.post(login_url, login_data, format="json", HTTP_X_CSRFTOKEN=csrf_token)
        refresh_token = login_response.cookies[settings.AUTH_REFRESH_COOKIE_NAME].value

        csrf_token = self._load_csrf()
        self.client.cookies[settings.AUTH_REFRESH_COOKIE_NAME] = refresh_token
        logout_url = reverse("auth-logout")
        logout_response = self.client.post(logout_url, HTTP_X_CSRFTOKEN=csrf_token)

        assert logout_response.status_code == status.HTTP_204_NO_CONTENT

        refresh = RefreshToken(refresh_token, verify=False)
        assert BlacklistedToken.objects.filter(token__jti=refresh["jti"]).exists()

    def test_logout_endpoint_unauthenticated(self):
        """Test logout endpoint without authentication."""
        csrf_token = self._load_csrf()
        url = reverse("auth-logout")
        response = self.client.post(url, HTTP_X_CSRFTOKEN=csrf_token)

        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_token_refresh_endpoint(self):
        """Test token refresh endpoint using refresh cookie."""
        csrf_token = self._load_csrf()
        login_url = reverse("auth-login")
        login_data = {
            "email": "integration@example.com",
            "password": "SecurePass123!",
        }
        login_response = self.client.post(login_url, login_data, format="json", HTTP_X_CSRFTOKEN=csrf_token)
        refresh_token = login_response.cookies[settings.AUTH_REFRESH_COOKIE_NAME].value

        csrf_token = self._load_csrf()
        refresh_url = reverse("auth-refresh")
        self.client.cookies[settings.AUTH_REFRESH_COOKIE_NAME] = refresh_token
        refresh_response = self.client.post(refresh_url, {}, format="json", HTTP_X_CSRFTOKEN=csrf_token)

        assert refresh_response.status_code == status.HTTP_200_OK
        assert settings.AUTH_ACCESS_COOKIE_NAME in refresh_response.cookies


class TestCookieCsrfEnforcement:
    """Integration-style tests for cookie auth + CSRF requirements."""

    def setup_method(self):
        self.factory = APIRequestFactory()
        self.view = ProtectedWriteView.as_view()
        self.user = User.objects.create_user(
            email="cookiecsrf@example.com",
            password="SecurePass123!",
            first_name="Cookie",
            last_name="Csrf",
            handle="cookiecsrf",
        )

    def test_cookie_auth_rejects_post_without_csrf(self):
        access = str(RefreshToken.for_user(self.user).access_token)
        request = self.factory.post("/auth/protected-write", {}, format="json")
        request._dont_enforce_csrf_checks = False
        request.COOKIES[settings.AUTH_ACCESS_COOKIE_NAME] = access

        response = self.view(request)

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_cookie_auth_allows_post_with_csrf(self):
        access = str(RefreshToken.for_user(self.user).access_token)
        request = self.factory.post("/auth/protected-write", {}, format="json")
        csrf_token = attach_csrf(request)
        request.COOKIES[settings.AUTH_ACCESS_COOKIE_NAME] = access
        request.COOKIES[settings.CSRF_COOKIE_NAME] = csrf_token
        request.META["HTTP_X_CSRFTOKEN"] = csrf_token

        response = self.view(request)

        assert response.status_code == status.HTTP_200_OK
