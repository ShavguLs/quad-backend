from django.contrib import admin

from apps.ads.models import Ad


@admin.register(Ad)
class AdAdmin(admin.ModelAdmin):
    list_display = ['title', 'publisher', 'category', 'is_published', 'created_at']
    list_filter = ['category', 'is_published', 'created_at']
    search_fields = ['title', 'publisher__display_name', 'publisher__handle']
    prepopulated_fields = {'slug': ('title',)}
    fieldsets = (
        (None, {'fields': ('publisher', 'title', 'slug')}),
        ('Content', {'fields': ('content', 'image', 'category')}),
        ('SEO', {'fields': ('seo_title', 'seo_description', 'seo_keywords')}),
        ('Publishing', {'fields': ('is_published',)}),
        ('Timestamps', {'fields': ('created_at', 'updated_at')}),
    )
    readonly_fields = ['created_at', 'updated_at']
