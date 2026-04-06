from rest_framework import serializers

from apps.ads.models import Ad
from apps.users.serializers import UserSerializer


class AdSerializer(serializers.ModelSerializer):
    publisher = UserSerializer(read_only=True)
    image = serializers.SerializerMethodField()

    class Meta:
        model = Ad
        fields = [
            'id',
            'publisher',
            'title',
            'slug',
            'content',
            'category',
            'image',
            'is_published',
            'seo_title',
            'seo_description',
            'seo_keywords',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['publisher', 'slug', 'created_at', 'updated_at']

    def get_image(self, obj):
        if not obj.image:
            return None

        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(obj.image.url)
        return obj.image.url


class AdListSerializer(AdSerializer):
    excerpt = serializers.SerializerMethodField()

    class Meta(AdSerializer.Meta):
        fields = [
            'id',
            'publisher',
            'title',
            'slug',
            'excerpt',
            'category',
            'image',
            'created_at',
            'updated_at',
        ]

    def get_excerpt(self, obj) -> str:
        text = obj.plain_content
        if len(text) <= 150:
            return text
        return f'{text[:147].rstrip()}...'
