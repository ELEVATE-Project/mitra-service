from rest_framework import serializers
from chatbot.models import Media


class MediaSerializer(serializers.ModelSerializer):
    s3_url = serializers.SerializerMethodField()
    tag_names = serializers.SerializerMethodField()

    class Meta:
        model = Media
        fields = ["id", "name", "description", "priority", "created_at", "s3_url", "tag_names"]

    def get_s3_url(self, obj):
        return obj.get_s3_url()

    def get_tag_names(self, obj):
        return list(obj.tags.values_list("name", flat=True))
