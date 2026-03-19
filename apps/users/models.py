from __future__ import annotations

from unicodedata import normalize

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils import timezone


def normalize_handle(value: str) -> str:
    if value is None:
        return ""
    return normalize("NFKC", value.strip()).lower()


class UserManager(BaseUserManager):
    def create_user(self, email, password, first_name, last_name, handle, **extra_fields):
        if not email:
            raise ValueError("Users must have an email address")
        if not first_name:
            raise ValueError("Users must have a first name")
        if not last_name:
            raise ValueError("Users must have a last name")
        if not handle:
            raise ValueError("Users must have a handle")

        email = self.normalize_email(email)
        handle_normalized = normalize_handle(handle)

        user = self.model(
            email=email,
            first_name=first_name,
            last_name=last_name,
            handle=handle,
            handle_normalized=handle_normalized,
            **extra_fields,
        )
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(
        self,
        email,
        password,
        first_name,
        last_name,
        handle,
        **extra_fields,
    ):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True")

        return self.create_user(email, password, first_name, last_name, handle, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    display_name = models.CharField(max_length=150, blank=True, null=True)
    bio = models.TextField(blank=True, null=True)
    profile_image = models.ImageField(
        upload_to="users/avatars/%Y/%m/",
        blank=True,
        null=True,
    )
    handle = models.CharField(max_length=50)
    handle_normalized = models.CharField(max_length=50, unique=True, db_index=True)
    google_id = models.CharField(max_length=255, unique=True, blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name", "handle"]

    def save(self, *args, **kwargs):
        self.handle_normalized = normalize_handle(self.handle)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.email
