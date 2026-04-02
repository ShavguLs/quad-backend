"""
Admin configuration for users app.

Registers User model in Django admin with full management capabilities.
"""

from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from apps.users.models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Admin configuration for User model with full management capabilities."""
    
    list_display = [
        'email',
        'first_name',
        'last_name',
        'handle',
        'can_upload_books',
        'is_active',
        'is_staff',
        'created_at',
    ]
    list_filter = ['is_active', 'is_staff', 'can_upload_books', 'created_at']
    search_fields = ['email', 'first_name', 'last_name', 'handle']
    readonly_fields = ['created_at', 'updated_at']
    ordering = ['-created_at']
    actions = ['activate_users', 'deactivate_users', 'make_staff', 'remove_staff']
    
    fieldsets = [
        (None, {'fields': ('email', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'handle')}),
        (
            'Permissions',
            {
                'fields': (
                    'is_active',
                    'is_staff',
                    'is_superuser',
                    'can_upload_books',
                    'groups',
                    'user_permissions',
                )
            },
        ),
        ('Important dates', {'fields': ('created_at', 'updated_at')}),
    ]
    add_fieldsets = [
        (None, {
            'classes': ('wide',),
            'fields': (
                'email',
                'first_name',
                'last_name',
                'handle',
                'can_upload_books',
                'password1',
                'password2',
            ),
        }),
    ]

    @admin.action(description='Activate selected users')
    def activate_users(self, request, queryset):
        """Bulk activate selected users."""
        count = queryset.update(is_active=True)
        self.message_user(
            request,
            f'{count} user(s) activated.',
            messages.SUCCESS
        )

    @admin.action(description='Deactivate selected users')
    def deactivate_users(self, request, queryset):
        """Bulk deactivate selected users."""
        count = queryset.update(is_active=False)
        self.message_user(
            request,
            f'{count} user(s) deactivated.',
            messages.SUCCESS
        )

    @admin.action(description='Grant staff status to selected users')
    def make_staff(self, request, queryset):
        """Grant staff status to selected users."""
        count = queryset.update(is_staff=True)
        self.message_user(
            request,
            f'{count} user(s) granted staff status.',
            messages.SUCCESS
        )

    @admin.action(description='Remove staff status from selected users')
    def remove_staff(self, request, queryset):
        """Remove staff status from selected users."""
        count = queryset.update(is_staff=False)
        self.message_user(
            request,
            f'{count} user(s) had staff status removed.',
            messages.SUCCESS
        )
