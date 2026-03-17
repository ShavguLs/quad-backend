"""Analytics views for the books app."""

from django.db.models import Count, Q
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated

from apps.books.models import Book
from apps.books.serializers import MyBookSerializer


class MyBooksAnalyticsView(ListAPIView):
    """Return the authenticated author's books in MyBook format for dashboard."""

    serializer_class = MyBookSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Book.objects.filter(
            owner=self.request.user
        ).select_related('owner').annotate(
            owners_count=Count(
                'orders',
                filter=Q(orders__status='COMPLETED'),
                distinct=True,
            )
        )
