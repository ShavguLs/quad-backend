import logging
import re
import secrets
import uuid

from django.conf import settings
from django.middleware.csrf import get_token
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from rest_framework import exceptions, permissions, status
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response
from rest_framework.authentication import CSRFCheck
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from apps.users.models import User
from apps.users.serializers import UserSerializer

from .serializers import LoginSerializer, RegisterSerializer


logger = logging.getLogger(__name__)
SESSION_ID_CLAIM = "session_id"


def _cookie_secure() -> bool:
    return bool(settings.AUTH_COOKIE_SECURE)


def _cookie_samesite() -> str:
    return settings.AUTH_COOKIE_SAMESITE


def _enforce_csrf(request):
    request._dont_enforce_csrf_checks = False
    check = CSRFCheck(lambda req: None)
    check.process_request(request)
    reason = check.process_view(request, None, (), {})
    if reason:
        raise exceptions.PermissionDenied("CSRF check failed.")


def _set_auth_cookies(response: Response, *, access: str, refresh: str):
    response.set_cookie(
        settings.AUTH_ACCESS_COOKIE_NAME,
        access,
        max_age=settings.AUTH_ACCESS_COOKIE_MAX_AGE,
        httponly=True,
        secure=_cookie_secure(),
        samesite=_cookie_samesite(),
        domain=settings.AUTH_COOKIE_DOMAIN,
        path=settings.AUTH_ACCESS_COOKIE_PATH,
    )
    response.set_cookie(
        settings.AUTH_REFRESH_COOKIE_NAME,
        refresh,
        max_age=settings.AUTH_REFRESH_COOKIE_MAX_AGE,
        httponly=True,
        secure=_cookie_secure(),
        samesite=_cookie_samesite(),
        domain=settings.AUTH_COOKIE_DOMAIN,
        path=settings.AUTH_REFRESH_COOKIE_PATH,
    )


def _clear_auth_cookies(response: Response):
    response.delete_cookie(
        settings.AUTH_ACCESS_COOKIE_NAME,
        domain=settings.AUTH_COOKIE_DOMAIN,
        path=settings.AUTH_ACCESS_COOKIE_PATH,
        samesite=_cookie_samesite(),
    )
    response.delete_cookie(
        settings.AUTH_REFRESH_COOKIE_NAME,
        domain=settings.AUTH_COOKIE_DOMAIN,
        path=settings.AUTH_REFRESH_COOKIE_PATH,
        samesite=_cookie_samesite(),
    )


def _issue_tokens_for_user(user: User, *, rotate_session: bool = True) -> tuple[str, str]:
    if rotate_session:
        user.active_session_id = uuid.uuid4()
        user.save(update_fields=["active_session_id"])

    refresh = RefreshToken.for_user(user)
    refresh[SESSION_ID_CLAIM] = str(user.active_session_id)
    return str(refresh.access_token), str(refresh)


class RegisterView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        _enforce_csrf(request)
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        access, refresh_token = _issue_tokens_for_user(user)

        response = Response({"user": UserSerializer(user, context={"request": request}).data}, status=status.HTTP_201_CREATED)
        _set_auth_cookies(response, access=access, refresh=refresh_token)
        get_token(request)
        return response


class LoginView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        _enforce_csrf(request)
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]

        access, refresh_token = _issue_tokens_for_user(user)
        response = Response({
            "user": UserSerializer(user, context={"request": request}).data,
        }, status=status.HTTP_200_OK)
        _set_auth_cookies(response, access=access, refresh=refresh_token)
        get_token(request)
        return response


class RefreshView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        _enforce_csrf(request)
        refresh = request.COOKIES.get(settings.AUTH_REFRESH_COOKIE_NAME)
        if not refresh:
            raise DRFValidationError({"detail": "Refresh token missing."})

        try:
            refresh_token = RefreshToken(refresh)
            user_id = refresh_token.get("user_id")
            session_id = refresh_token.get(SESSION_ID_CLAIM)
            user = User.objects.filter(id=user_id, is_active=True).first()

            if not user_id or not session_id or not user or session_id != str(user.active_session_id):
                logger.warning("Stale or malformed refresh token provided during refresh.")
                response = Response(
                    {"detail": "Refresh token is invalid or has been revoked."},
                    status=status.HTTP_401_UNAUTHORIZED,
                )
                _clear_auth_cookies(response)
                return response

            serializer = TokenRefreshSerializer(data={"refresh": refresh})
            serializer.is_valid(raise_exception=True)
        except (TokenError, DRFValidationError):
            logger.warning("Invalid or blacklisted refresh token provided during refresh.")
            response = Response(
                {"detail": "Refresh token is invalid or has been revoked."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
            _clear_auth_cookies(response)
            return response
        except Exception:
            logger.exception("Unexpected error during token refresh.")
            response = Response(
                {"detail": "Failed to refresh access token."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
            _clear_auth_cookies(response)
            return response

        access = serializer.validated_data["access"]
        rotated_refresh = serializer.validated_data.get("refresh") or refresh

        access_token = AccessToken(access)
        if access_token.get(SESSION_ID_CLAIM) != str(user.active_session_id):
            access_token[SESSION_ID_CLAIM] = str(user.active_session_id)
            access = str(access_token)

        rotated_refresh_token = RefreshToken(rotated_refresh)
        if rotated_refresh_token.get(SESSION_ID_CLAIM) != str(user.active_session_id):
            rotated_refresh_token[SESSION_ID_CLAIM] = str(user.active_session_id)
            rotated_refresh = str(rotated_refresh_token)

        response = Response(status=status.HTTP_200_OK)
        _set_auth_cookies(response, access=access, refresh=rotated_refresh)
        get_token(request)
        return response


class MeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response({"user": UserSerializer(request.user, context={"request": request}).data}, status=status.HTTP_200_OK)


class CsrfTokenView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        token = get_token(request)
        return Response({"csrfToken": token}, status=status.HTTP_200_OK)


def _generate_unique_handle(base: str) -> str:
    """Derive a unique handle from a Google user's given name."""
    slug = re.sub(r"[^a-z0-9]", "", base.lower())[:20] or "user"
    for _ in range(10):
        candidate = f"{slug}_{secrets.token_hex(2)}"
        if not User.objects.filter(handle_normalized=candidate).exists():
            return candidate
    return f"user_{secrets.token_hex(4)}"


class GoogleLoginView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        _enforce_csrf(request)

        credential = request.data.get("credential")
        if not credential:
            raise DRFValidationError({"detail": "Google credential missing."})

        client_id = settings.GOOGLE_CLIENT_ID
        if not client_id:
            raise DRFValidationError({"detail": "Google login is not configured."})

        try:
            payload = google_id_token.verify_oauth2_token(
                credential,
                google_requests.Request(),
                client_id,
            )
        except ValueError as exc:
            logger.warning("Google ID token verification failed: %s", exc)
            raise exceptions.AuthenticationFailed("Invalid Google token.") from exc

        google_sub = payload["sub"]
        email = payload.get("email", "")
        email_verified = payload.get("email_verified") is True
        if not email or not email_verified:
            raise exceptions.AuthenticationFailed("Google email is not verified.")
        first_name = payload.get("given_name", "") or email.split("@")[0]
        last_name = payload.get("family_name", "") or "."

        try:
            user = User.objects.get(google_id=google_sub)
        except User.DoesNotExist:
            try:
                user = User.objects.get(email=email)
                user.google_id = google_sub
                user.save(update_fields=["google_id"])
            except User.DoesNotExist:
                handle = _generate_unique_handle(first_name)
                user = User(
                    email=email,
                    first_name=first_name,
                    last_name=last_name,
                    handle=handle,
                    google_id=google_sub,
                )
                user.set_unusable_password()
                user.save()

        access, refresh = _issue_tokens_for_user(user)
        response = Response(
            {"user": UserSerializer(user, context={"request": request}).data},
            status=status.HTTP_200_OK,
        )
        _set_auth_cookies(response, access=access, refresh=refresh)
        get_token(request)
        return response


class LogoutView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        _enforce_csrf(request)

        if request.user.is_authenticated:
            request.user.active_session_id = uuid.uuid4()
            request.user.save(update_fields=["active_session_id"])

        raw_refresh_token = request.COOKIES.get(settings.AUTH_REFRESH_COOKIE_NAME)
        if raw_refresh_token:
            try:
                RefreshToken(raw_refresh_token).blacklist()
            except TokenError:
                logger.warning("Invalid refresh token provided during logout.")
            except Exception:
                logger.exception("Failed to blacklist refresh token during logout.")
                response = Response(
                    {"detail": "Failed to invalidate refresh token."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
                _clear_auth_cookies(response)
                return response

        response = Response(status=status.HTTP_204_NO_CONTENT)
        _clear_auth_cookies(response)
        return response
