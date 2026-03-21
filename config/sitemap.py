from xml.sax.saxutils import escape

from django.conf import settings
from django.http import HttpRequest, HttpResponse

from apps.books.models import Book

SITEMAP_STATIC_ROUTES = ('/', '/books', '/community', '/reviews', '/terms')


def _absolute_url(path: str) -> str:
    base_url = getattr(settings, 'SITE_BASE_URL', 'https://quaduni.com').rstrip('/')
    return f'{base_url}{path}'


def _url_entry(location: str, lastmod: str | None = None) -> str:
    parts = [f'<loc>{escape(location)}</loc>']
    if lastmod:
        parts.append(f'<lastmod>{escape(lastmod)}</lastmod>')
    return f"  <url>{''.join(parts)}</url>"


def sitemap_xml(request: HttpRequest) -> HttpResponse:
    public_books = Book._default_manager.filter(
        status='published',
        is_visible=True,
    ).only('id', 'updated_at').order_by('id')

    entries = [_url_entry(_absolute_url(route)) for route in SITEMAP_STATIC_ROUTES]
    entries.extend(
        _url_entry(_absolute_url(f'/book/{book.id}'), book.updated_at.isoformat())
        for book in public_books
    )

    xml = '\n'.join([
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        *entries,
        '</urlset>',
        '',
    ])
    return HttpResponse(xml.encode('utf-8'), content_type='application/xml')
