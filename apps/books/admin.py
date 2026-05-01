# Book admin configuration

from django.contrib import admin

from .models import Book, BookFollow, BookView


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    """
    Admin interface for Book model.

    Provides full CRUD capabilities with organized fieldsets for better UX.
    Auto-sets status='published' and owner to the current admin user on create.
    Satisfies ADM-01 (is_featured editable), ADM-02 (analytics fields editable),
    ADM-03 (commerce fields editable), and ADM-10 (search/filter/list display).
    """
    list_display = [
        'title', 'author', 'status', 'price', 'category',
        'access_type', 'is_featured', 'is_visible', 'created_at'
    ]
    list_filter = ['status', 'access_type', 'is_featured', 'is_visible', 'category', 'created_at']
    search_fields = ['title', 'author', 'category']
    raw_id_fields = ['owner']
    readonly_fields = ['created_at', 'updated_at']

    add_fieldsets = (
        ('Basic Info', {
            'fields': ('title', 'author', 'description', 'cover_image', 'pdf_file'),
            'description': 'Core book metadata.'
        }),
        ('Publication & Catalog', {
            'fields': ('price', 'category', 'access_type', 'is_featured', 'is_visible', 'status'),
            'description': 'Publication status, pricing, categorization, and visibility.'
        }),
        ('Analytics', {
            'fields': ('view_count', 'follower_count', 'revenue_total'),
            'description': 'Book statistics. Editable for manual corrections by superusers.'
        }),
    )

    change_fieldsets = (
        ('Basic Info', {
            'fields': ('title', 'author', 'description', 'cover_image', 'pdf_file'),
            'description': 'Core book metadata.'
        }),
        ('Publication & Catalog', {
            'fields': ('price', 'category', 'access_type', 'is_featured', 'is_visible', 'status', 'owner'),
            'description': 'Publication status, pricing, categorization, and visibility.'
        }),
        ('Analytics', {
            'fields': ('view_count', 'follower_count', 'revenue_total'),
            'description': 'Book statistics. Editable for manual corrections by superusers.'
        }),
    )

    def get_fieldsets(self, request, obj=None):
        if obj:
            return self.change_fieldsets
        return self.add_fieldsets

    def get_changeform_initial_data(self, request):
        return {'status': 'published'}

    def save_model(self, request, obj, form, change):
        if not change:
            if not obj.owner_id:
                obj.owner = request.user
        super().save_model(request, obj, form, change)

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