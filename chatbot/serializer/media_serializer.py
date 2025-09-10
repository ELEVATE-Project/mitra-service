from rest_framework import serializers
from django.db.models import TextField, Value
from django.db.models.functions import Lower, Replace
from chatbot.models import Media, KeyValue, Tag
from chatbot.models.media_models import MediaImage


class KeyValueSerializer(serializers.ModelSerializer):
    class Meta:
        model = KeyValue
        fields = ['id', 'key', 'value']


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ['id', 'name', 'status', 'source_type', 'description']


class MediaImageSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = MediaImage
        fields = ['id', 'name', 'media_type', 'page', 'width', 'height', 'file_url', 'created_at']

    def get_file_url(self, obj):
        if obj.file:
            return obj.file.url
        return None


class MediaListSerializer(serializers.ModelSerializer):
    s3_url = serializers.SerializerMethodField()
    file = serializers.SerializerMethodField()
    tag_names = serializers.SerializerMethodField()
    media_type_display = serializers.CharField(source='get_media_type_display', read_only=True)
    priority_display = serializers.CharField(source='get_priority_display', read_only=True)
    title = serializers.SerializerMethodField()
    organization = serializers.SerializerMethodField()
    document_type = serializers.SerializerMethodField()
    key_entities = serializers.SerializerMethodField()
    file_size = serializers.SerializerMethodField()

    class Meta:
        model = Media
        fields = [
            'id', 'name', 'description', 'priority', 'priority_display',
            'media_type', 'media_type_display', 'created_at', 'updated_at',
            's3_url', 'file', 'tag_names', 'title', 'organization',
            'document_type', 'key_entities', 'file_size'
        ]

    def get_s3_url(self, obj):
        # If current doc is Source Document
        if obj.key_values.annotate(
                norm_key=Lower(Replace('key', Value('_'), Value(' '), output_field=TextField()))
        ).filter(
            norm_key='document type',
            value__icontains='source document'
        ).exists():
            return obj.get_s3_url()

        # Check parent
        if obj.parent and obj.parent.key_values.annotate(
                norm_key=Lower(Replace('key', Value('_'), Value(' '), output_field=TextField()))
        ).filter(
            norm_key='document type',
            value__icontains='source document'
        ).exists():
            return obj.parent.get_s3_url()

        # Check children
        child = obj.subdocuments.annotate(
            norm_key=Lower(Replace('key_values__key', Value('_'), Value(' '), output_field=TextField()))
        ).filter(
            norm_key='document type',
            key_values__value__icontains='source document'
        ).first()
        if child:
            return child.get_s3_url()

        # fallback
        return obj.get_s3_url()

    def get_file(self, obj):
        return obj.get_s3_url() if hasattr(obj, 'get_s3_url') else None

    def get_tag_names(self, obj):
        return list(obj.tags.values_list("name", flat=True))

    def get_metadata_field(self, obj, key_name):
        kv = obj.key_values.filter(key__iexact=key_name).first()
        return kv.value if kv else None

    def get_title(self, obj):
        return self.get_metadata_field(obj, 'TITLE')

    def get_organization(self, obj):
        return self.get_metadata_field(obj, 'ORGANIZATION')

    def get_document_type(self, obj):
        return self.get_metadata_field(obj, 'DOCUMENT TYPE')

    def get_key_entities(self, obj):
        return self.get_metadata_field(obj, 'KEY ENTITIES')

    def get_file_size(self, obj):
        return getattr(obj.file, "size", None) if obj.file else None


class MediaDetailSerializer(serializers.ModelSerializer):
    s3_url = serializers.SerializerMethodField()
    file = serializers.SerializerMethodField()
    tags = TagSerializer(many=True, read_only=True)
    key_values = serializers.SerializerMethodField()
    images = MediaImageSerializer(many=True, read_only=True)
    parent_info = serializers.SerializerMethodField()
    children = serializers.SerializerMethodField()
    media_type_display = serializers.CharField(source='get_media_type_display', read_only=True)
    priority_display = serializers.CharField(source='get_priority_display', read_only=True)
    company_bot_name = serializers.CharField(source='company_bot.name', read_only=True)
    title = serializers.SerializerMethodField()
    organization = serializers.SerializerMethodField()
    document_type = serializers.SerializerMethodField()
    key_entities = serializers.SerializerMethodField()
    file_size = serializers.SerializerMethodField()
    size = serializers.SerializerMethodField()

    class Meta:
        model = Media
        fields = [
            'id', 'name', 'description', 'priority', 'priority_display',
            'media_type', 'media_type_display', 'extracted_text',
            'file', 'url', 'company_bot', 'company_bot_name',
            'parent', 'parent_info', 'created_at', 'updated_at',
            's3_url', 'tags', 'title', 'organization', 'document_type',
            'key_entities', 'key_values', 'images', 'children',
            'file_size', 'size',
        ]

    def get_s3_url(self, obj):
        # If current doc is Source Document
        if obj.key_values.annotate(
                norm_key=Lower(Replace('key', Value('_'), Value(' '), output_field=TextField()))
        ).filter(
            norm_key='document type',
            value__icontains='source document'
        ).exists():
            return obj.get_s3_url()

        # Check parent
        if obj.parent and obj.parent.key_values.annotate(
                norm_key=Lower(Replace('key', Value('_'), Value(' '), output_field=TextField()))
        ).filter(
            norm_key='document type',
            value__icontains='source document'
        ).exists():
            return obj.parent.get_s3_url()

        # Check children
        child = obj.subdocuments.annotate(
            norm_key=Lower(Replace('key_values__key', Value('_'), Value(' '), output_field=TextField()))
        ).filter(
            norm_key='document type',
            key_values__value__icontains='source document'
        ).first()
        if child:
            return child.get_s3_url()

        # fallback
        return obj.get_s3_url()

    def get_file(self, obj):
        return obj.get_s3_url() if hasattr(obj, 'get_s3_url') else None

    def get_key_values(self, obj):
        excluded_keys = ['TITLE', 'ORGANIZATION', 'DOCUMENT TYPE', 'KEY ENTITIES', 'ORIGINAL_FILE_URL',
                         'FOUND_IN_DOCUMENT', 'DOCUMENT TYPE REASON']
        filtered_kvs = obj.key_values.exclude(key__in=excluded_keys)

        # If no key-value pairs exist after exclusion, include the metadata fields
        if not filtered_kvs.exists():
            metadata_kvs = obj.key_values.filter(key__in=['TITLE', 'ORGANIZATION', 'DOCUMENT TYPE', 'KEY ENTITIES'])
            return KeyValueSerializer(metadata_kvs, many=True).data

        return KeyValueSerializer(filtered_kvs, many=True).data

    def get_parent_info(self, obj):
        if obj.parent:
            return {
                'id': obj.parent.id,
                'name': obj.parent.name,
                'media_type': obj.parent.media_type
            }
        return None

    def get_children(self, obj):
        children = obj.subdocuments.all()
        return MediaListSerializer(children, many=True).data if children.exists() else []

    def get_metadata_field(self, obj, key_name):
        kv = obj.key_values.filter(key__iexact=key_name).first()
        return kv.value if kv else None

    def get_title(self, obj):
        return self.get_metadata_field(obj, 'TITLE')

    def get_organization(self, obj):
        return self.get_metadata_field(obj, 'ORGANIZATION')

    def get_document_type(self, obj):
        return self.get_metadata_field(obj, 'DOCUMENT TYPE')

    def get_key_entities(self, obj):
        return self.get_metadata_field(obj, 'KEY ENTITIES')

    def get_file_size(self, obj):
        """Get file size in bytes"""
        try:
            if obj.file and hasattr(obj.file, 'size'):
                return obj.file.size
            return None
        except (ValueError, AttributeError):
            return None

    def get_size(self, obj):
        """Get human-readable file size"""
        try:
            if obj.file and hasattr(obj.file, 'size'):
                size = obj.file.size
                if size is None:
                    return None

                # Convert bytes to human readable format
                for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
                    if size < 1024.0:
                        return f"{size:.1f} {unit}"
                    size /= 1024.0
                return f"{size:.1f} PB"
            return None
        except (ValueError, AttributeError):
            return None
