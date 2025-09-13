from rest_framework import serializers
from django.db.models import TextField, Value, Q
from django.db.models.functions import Lower, Replace
from chatbot.models import Media, KeyValue, Tag
from chatbot.models.media_models import MediaImage
import ast
import json


class S3UrlMixin:
    def resolve_s3_url(self, obj):
        # Get document type (case-insensitive)
        doc_type = None
        kv = obj.key_values.filter(key__iregex=r'^document[_\s]type$').first()
        if kv and kv.value:
            doc_type = kv.value.lower()

        # Rule 1: Template File
        if doc_type == "template":
            linked_file = obj.subdocuments.filter(
                key_values__key__iregex=r'^document[_\s]type$',
                key_values__value__icontains="source document"
            ).first()
            if linked_file:
                return linked_file.get_s3_url()
            return obj.get_s3_url()

        # Rule 2: Non-template file → download directly
        if doc_type and doc_type != "template":
            return obj.get_s3_url()

        # Rule 3: AI extracted file (subdocument of template’s linked file)
        if obj.parent:
            parent_kv = obj.parent.key_values.filter(key__iregex=r'^document[_\s]type$').first()
            parent_doc_type = parent_kv.value.lower() if parent_kv and parent_kv.value else None
            if parent_doc_type in ["template", "source document"]:
                return obj.get_s3_url()

        # Default fallback
        return obj.get_s3_url()


class KeyValueSerializer(serializers.ModelSerializer):
    value = serializers.SerializerMethodField()

    class Meta:
        model = KeyValue
        fields = ['id', 'key', 'value']

    def get_value(self, obj):
        """Convert string representations of lists back to actual lists"""
        value = obj.value

        # Check if the value looks like a list string representation
        if isinstance(value, str) and value.strip().startswith('[') and value.strip().endswith(']'):
            try:
                # Try to safely evaluate the string as a Python literal
                parsed_value = ast.literal_eval(value)
                if isinstance(parsed_value, list):
                    return parsed_value
            except (ValueError, SyntaxError):
                # If parsing fails, try JSON parsing
                try:
                    parsed_value = json.loads(value)
                    if isinstance(parsed_value, list):
                        return parsed_value
                except (json.JSONDecodeError, TypeError):
                    pass
        # Return original value if not a list or parsing failed
        return value


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


class MediaListSerializer(serializers.ModelSerializer, S3UrlMixin):
    s3_url = serializers.SerializerMethodField()
    file = serializers.SerializerMethodField()
    tag_names = serializers.SerializerMethodField()
    media_type_display = serializers.CharField(source='get_media_type_display', read_only=True)
    priority_display = serializers.CharField(source='get_priority_display', read_only=True)
    title = serializers.SerializerMethodField()
    organization = serializers.SerializerMethodField()
    organization_url = serializers.SerializerMethodField()
    document_type = serializers.SerializerMethodField()
    key_entities = serializers.SerializerMethodField()
    file_size = serializers.SerializerMethodField()

    # Search matching scores
    keyword_coverage = serializers.IntegerField(read_only=True)
    total_matching_fields = serializers.IntegerField(read_only=True)
    avg_relevance_score = serializers.FloatField(read_only=True)
    max_similarity = serializers.FloatField(read_only=True)

    class Meta:
        model = Media
        fields = [
            'id', 'name', 'description', 'priority', 'priority_display',
            'media_type', 'media_type_display', 'created_at', 'updated_at',
            's3_url', 'file', 'tag_names', 'title', 'organization',
            'document_type', 'key_entities', 'file_size', 'organization_url',
            'keyword_coverage', 'total_matching_fields', 'avg_relevance_score', 'max_similarity'
        ]

    def get_s3_url(self, obj):
        return self.resolve_s3_url(obj)

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
        # Already correct - using direct organization field
        if obj.organization:
            return obj.organization.name
        return None

    def get_organization_url(self, obj):
        # New method for organization URL
        if obj.organization:
            return obj.organization.url
        return None

    def get_document_type(self, obj):
        # Handle both DOCUMENT_TYPE and DOCUMENT TYPE variants
        document_type = obj.key_values.filter(key__iregex=r'^document[_\s]type$').first()
        return document_type.value if document_type else None

    def get_key_entities(self, obj):
        return self.get_metadata_field(obj, 'KEY ENTITIES')

    def get_file_size(self, obj):
        return getattr(obj.file, "size", None) if obj.file else None


class MediaDetailSerializer(serializers.ModelSerializer, S3UrlMixin):
    s3_url = serializers.SerializerMethodField()
    file = serializers.SerializerMethodField()
    tags = TagSerializer(many=True, read_only=True)
    key_values = serializers.SerializerMethodField()
    images = MediaImageSerializer(many=True, read_only=True)
    parent_info = serializers.SerializerMethodField()
    children = serializers.SerializerMethodField()
    media_type_display = serializers.CharField(source='get_media_type_display', read_only=True)
    priority_display = serializers.CharField(source='get_priority_display', read_only=True)
    # company_bot_name = serializers.CharField(source='company_bot.name', read_only=True)
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
            'file', 'url', 'company_bot',
            'parent', 'parent_info', 'created_at', 'updated_at',
            's3_url', 'tags', 'title', 'organization', 'document_type',
            'key_entities', 'key_values', 'images', 'children',
            'file_size', 'size',
        ]

    def get_s3_url(self, obj):
        return self.resolve_s3_url(obj)

    def get_file(self, obj):
        return obj.get_s3_url() if hasattr(obj, 'get_s3_url') else None

    def get_key_values(self, obj):
        # Create basic information array
        basic_info = []

        # Get basic information fields
        title = obj.key_values.filter(key__iexact='TITLE').first()
        organization_name = None
        if obj.organization:
            organization_name = obj.organization.name

        geography = obj.key_values.filter(key__iexact='GEOGRAPHY').first()
        # Handle both DOCUMENT_TYPE and DOCUMENT TYPE variants
        document_type = obj.key_values.filter(key__iregex=r'^document[_\s]type$').first()

        # Add title to basic info
        if title and title.value:
            basic_info.append(f"<div><b>Title:</b> {title.value}</div>")

        # Add organization with link to basic info (from direct organization FK)
        if organization_name:
            organization_url = obj.organization.url if obj.organization and obj.organization.url else "#"
            basic_info.append(
                f'<div><b>Organization:</b> <a class="text-blue-600 underline underline-offset-2" href="{organization_url}" target="_blank" rel="noopener noreferrer">{organization_name}</a></div>')
        if geography and geography.value:
            basic_info.append(f"<div><b>Geography:</b> {geography.value}</div>")

        # Add document type to basic info
        if document_type and document_type.value:
            basic_info.append(f"<div><b>Document Type:</b> {document_type.value}</div>")

        # Get filtered key-value pairs (excluding basic info fields and ORGANIZATION since we get it from FK)
        # Use regex to exclude both DOCUMENT_TYPE and DOCUMENT TYPE variants
        filtered_kvs = obj.key_values.exclude(
            Q(key__in=['TITLE', 'ORGANIZATION', 'KEY ENTITIES', 'GEOGRAPHY',
                       'ORIGINAL_FILE_URL', 'FOUND_IN_DOCUMENT', 'DOCUMENT TYPE REASON']) |
            Q(key__iregex=r'^document[_\s]type$') |
            Q(key__isnull=True, value__isnull=True) |
            Q(key='', value='')
        )

        # Serialize filtered key-value pairs
        key_values_data = KeyValueSerializer(filtered_kvs, many=True).data

        # Add Tags for Classification if tags exist and document type is not template
        if obj.tags.exists():
            document_type_value = document_type.value.lower() if document_type and document_type.value else ''
            if document_type_value != 'template':
                tag_names = list(obj.tags.values_list("name", flat=True))
                tags_classification_kv = {
                    'id': None,
                    'key': 'Tags for Classification',
                    'value': tag_names
                }
                key_values_data.append(tags_classification_kv)

        # Add basic information as the first key-value pair if any basic info exists
        if basic_info:
            basic_info_kv = {
                'id': None,
                'key': 'Basic Information',
                'value': basic_info
            }
            key_values_data.insert(0, basic_info_kv)

        # If no key-value pairs exist after exclusion and no basic info, include the metadata fields
        if not filtered_kvs.exists() and not basic_info:
            metadata_kvs = obj.key_values.filter(
                Q(key__in=['TITLE', 'KEY ENTITIES', 'GEOGRAPHY']) |  # Removed ORGANIZATION from here
                Q(key__iregex=r'^document[_\s]type$')
            ).exclude(
                Q(key__isnull=True, value__isnull=True) |
                Q(key='', value='')
            )
            serialized_data = KeyValueSerializer(metadata_kvs, many=True).data

            # Add organization from direct organization FK if it exists
            if organization_name:
                org_kv = {
                    'id': None,
                    'key': 'ORGANIZATION',
                    'value': organization_name
                }
                serialized_data.append(org_kv)

            # Add Tags for Classification in fallback case (if document type is not template)
            if obj.tags.exists():
                # Re-check document type for this case
                fallback_document_type = obj.key_values.filter(key__iregex=r'^document[_\s]type$').first()
                document_type_value = fallback_document_type.value.lower() if fallback_document_type and fallback_document_type.value else ''
                if document_type_value != 'template':
                    tag_names = list(obj.tags.values_list("name", flat=True))
                    tags_classification_kv = {
                        'id': None,
                        'key': 'Tags for Classification',
                        'value': tag_names
                    }
                    serialized_data.append(tags_classification_kv)

            return serialized_data

        return key_values_data

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
        if obj.organization:
            return obj.organization.name
        return None

    def get_document_type(self, obj):
        # Handle both DOCUMENT_TYPE and DOCUMENT TYPE variants
        document_type = obj.key_values.filter(key__iregex=r'^document[_\s]type$').first()
        return document_type.value if document_type else None

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
