from django.urls import path

from .views import CsrfTokenView, LoginView, LogoutView, MeView, RefreshView, RegisterView

urlpatterns = [
    path("csrf", CsrfTokenView.as_view(), name="auth-csrf"),
    path("register", RegisterView.as_view(), name="auth-register"),
    path("login", LoginView.as_view(), name="auth-login"),
    path("refresh", RefreshView.as_view(), name="auth-refresh"),
    path("me", MeView.as_view(), name="auth-me"),
    path("logout", LogoutView.as_view(), name="auth-logout"),
]
