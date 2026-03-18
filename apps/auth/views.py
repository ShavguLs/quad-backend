import logging

from django.conf import settings
from django.middleware.csrf import get_token
from rest_framework import exceptions, permissions, status
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response
from rest_framework.authentication import CSRFCheck
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from apps.users.serializers import UserSerializer

from .serializers import LoginSerializer, RegisterSerializer


logger = logging.getLogger(__name__)


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


class RegisterView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        _enforce_csrf(request)
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        refresh = RefreshToken.for_user(user)
        access = str(refresh.access_token)
        refresh_token = str(refresh)

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

        # Generate token pair
        refresh = RefreshToken.for_user(user)

        access = str(refresh.access_token)
        refresh_token = str(refresh)
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
        refresh = request.data.get("refresh") or request.COOKIES.get(settings.AUTH_REFRESH_COOKIE_NAME)
        if not refresh:
            raise DRFValidationError({"detail": "Refresh token missing."})

        try:
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


class LogoutView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        _enforce_csrf(request)
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
