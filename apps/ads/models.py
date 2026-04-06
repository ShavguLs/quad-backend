import json
import re

from django.conf import settings
from django.db import models


_HTML_TAG_PATTERN = re.compile(r'<[^>]+>')


class Ad(models.Model):
    CATEGORY_PROMO = 'promo'
    CATEGORY_ANNOUNCEMENT = 'announcement'
    CATEGORY_SHOWCASE = 'showcase'
    CATEGORY_NEWS = 'news'

    CATEGORY_CHOICES = [
        (CATEGORY_PROMO, 'Promotion'),
        (CATEGORY_ANNOUNCEMENT, 'Announcement'),
        (CATEGORY_SHOWCASE, 'Showcase'),
        (CATEGORY_NEWS, 'News'),
    ]

    publisher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='ads',
    )
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True)
    content = models.TextField()
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES)
    image = models.ImageField(upload_to='ads/', blank=True, null=True)
    is_published = models.BooleanField(default=False)
    seo_title = models.CharField(max_length=70, blank=True)
    seo_description = models.CharField(max_length=160, blank=True)
    seo_keywords = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Ad'
        verbose_name_plural = 'Ads'

    def __str__(self) -> str:
        return self.title

    @staticmethod
    def _collect_text(value, parts: list[str]) -> None:
        if isinstance(value, str):
            normalized = value.strip()
            if normalized:
                parts.append(normalized)
            return

        if isinstance(value, dict):
            for item in value.values():
                Ad._collect_text(item, parts)
            return

        if isinstance(value, list):
            for item in value:
                Ad._collect_text(item, parts)

    @property
    def plain_content(self) -> str:
        stripped = self.content.strip()
        if not stripped:
            return ''

        if stripped.startswith('<'):
            return _HTML_TAG_PATTERN.sub(' ', stripped).strip()

        if stripped[0] in ('{', '['):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                return stripped

            text_parts: list[str] = []
            self._collect_text(parsed, text_parts)
            return ' '.join(text_parts).strip()

        return stripped
