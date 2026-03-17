# Book admin configuration

from django.contrib import admin

from .models import Book, BookAuditLog, BookFile, BookFollow, BookView


class BookFileInline(admin.TabularInline):
    """Inline admin for managing book files within Book admin."""
    model = BookFile
    extra = 0
    fields = ['file', 'mime_type', 'original_filename', 'uploaded_at']
    readonly_fields = ['mime_type', 'original_filename', 'uploaded_at']


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    """
    Admin interface for Book model.

    Provides full CRUD capabilities with organized fieldsets for better UX.
    Satisfies ADM-01 (is_featured editable), ADM-02 (analytics fields editable),
    ADM-03 (commerce fields editable), and ADM-10 (search/filter/list display).
    """
    # List view configuration
    list_display = [
        'title', 'author', 'owner', 'status', 'price', 'category',
        'is_featured', 'is_visible', 'created_at'
    ]
    list_filter = ['status', 'is_featured', 'is_visible', 'category', 'created_at']
    search_fields = ['title', 'author', 'category', 'owner__email', 'owner__handle']
    raw_id_fields = ['owner']
    inlines = [BookFileInline]
    readonly_fields = ['created_at', 'updated_at']

    # Organized fieldsets for better admin UX
    fieldsets = (
        # Basic book information
        ('Basic Info', {
            'fields': ('title', 'author', 'description', 'owner', 'cover_image'),
            'description': 'Core book metadata and ownership information.'
        }),
        # Status, commerce, and feature flags
        ('Status & Commerce', {
            'fields': ('status', 'price', 'category', 'is_featured', 'is_visible'),
            'description': 'Publication status, pricing, categorization, and feature flags.'
        }),
        # Analytics fields - editable for manual corrections
        ('Analytics', {
            'fields': ('view_count', 'follower_count', 'revenue_total'),
            'description': 'Book statistics. Editable for manual corrections by superusers.'
        }),
    )

    @admin.action(description='Hide selected books from public listings')
    def hide_books(self, request, queryset):
        queryset.update(is_visible=False)

    @admin.action(description='Unhide selected books for public listings')
    def unhide_books(self, request, queryset):
        queryset.update(is_visible=True)

    actions = ['hide_books', 'unhide_books']


@admin.register(BookView)
class BookViewAdmin(admin.ModelAdmin):
    list_display = ['book', 'user', 'view_date', 'created_at']
    list_filter = ['view_date', 'created_at']
    search_fields = ['book__title', 'user__email']
    raw_id_fields = ['book', 'user']
    readonly_fields = ['created_at']


@admin.register(BookFollow)
class BookFollowAdmin(admin.ModelAdmin):
    list_display = ['book', 'user', 'created_at']
    list_filter = ['created_at']
    search_fields = ['book__title', 'user__email']
    raw_id_fields = ['book', 'user']
    readonly_fields = ['created_at']


@admin.register(BookAuditLog)
class BookAuditLogAdmin(admin.ModelAdmin):
    """
    Admin interface for BookAuditLog.
    
    Read-only access to maintain append-only audit trail integrity.
    """
    list_display = ['book', 'user', 'action', 'timestamp', 'ip_address']
    list_filter = ['action', 'timestamp', 'book']
    search_fields = ['book__title', 'user__email']
    raw_id_fields = ['book', 'user']
    readonly_fields = ['book', 'user', 'action', 'timestamp', 'details', 'ip_address']
    ordering = ['-timestamp']
    date_hierarchy = 'timestamp'

    def has_add_permission(self, request):
        """Audit logs are created programmatically, not via admin."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Audit logs are append-only."""
        return False

    def has_change_permission(self, request, obj=None):
        """Audit logs are immutable."""
        return False
