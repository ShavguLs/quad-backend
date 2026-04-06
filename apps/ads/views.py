from django.db.models import Count
from django.shortcuts import get_object_or_404
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.ads.models import Ad
from apps.ads.serializers import AdListSerializer, AdSerializer
from apps.users.models import User


class AdViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = AdSerializer
    lookup_field = 'slug'

    def get_queryset(self):
        queryset = Ad.objects.filter(is_published=True).select_related('publisher')

        if self.action != 'list':
            return queryset

        publisher = self.request.query_params.get('publisher')
        category = self.request.query_params.get('category')
        search = self.request.query_params.get('search')

        if publisher:
            queryset = queryset.filter(publisher__handle_normalized=publisher.lower())
        if category:
            queryset = queryset.filter(category=category)
        if search:
            queryset = queryset.filter(title__icontains=search)

        return queryset

    def get_serializer_class(self):
        if self.action == 'list':
            return AdListSerializer
        return AdSerializer

    def retrieve(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        ad = get_object_or_404(queryset, slug=kwargs.get('slug'))
        serializer = self.get_serializer(ad)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def publishers(self, request):
        publishers = (
            User.objects.filter(ads__is_published=True)
            .distinct()
            .order_by('handle')
        )

        payload = []
        for publisher in publishers:
            display_name = (publisher.display_name or '').strip()
            if not display_name:
                first_name = (publisher.first_name or '').strip()
                last_name = (publisher.last_name or '').strip()
                display_name = ' '.join(part for part in [first_name, last_name] if part) or None

            profile_image = None
            if publisher.profile_image:
                profile_image = publisher.profile_image.url
                if request is not None:
                    profile_image = request.build_absolute_uri(profile_image)

            payload.append({
                'id': publisher.id,
                'handle': publisher.handle,
                'display_name': display_name,
                'profile_image': profile_image,
            })

        return Response(payload)

    @action(detail=False, methods=['get'])
    def categories(self, request):
        categories = (
            Ad.objects.filter(is_published=True)
            .values('category')
            .annotate(count=Count('id'))
            .order_by('category')
        )
        return Response([
            {'category': item['category'], 'count': item['count']}
            for item in categories
        ])
