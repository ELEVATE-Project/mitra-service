from rest_framework import serializers
from django.db.models import TextField, Value, Q
from django.db.models.functions import Lower, Replace
from chatbot.models import Media, KeyValue, Tag, FileDisplayMode
from chatbot.models.media_models import MediaImage
import ast
import json


class S3UrlMixin:
    def resolve_s3_url(self, obj):
        # Rule 1: Check if this media has a child with document type "source document"
        linked_file = obj.subdocuments.filter(
            key_values__key__iregex=r'^document[_\s]type$',
            key_values__value__icontains="source document"
        ).first()

        if linked_file:
            return linked_file.get_s3_url()

        # Rule 2: AI extracted file (subdocument of template's linked file)
        # If this object is a child, check if parent is template or source document
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


class MediaSearchResultSerializer(serializers.Serializer):
    """
    Serializer for vector database search results (v2 API).
    Transforms vector DB response format to match the existing Media API V1 format exactly.
    """
    
    def to_representation(self, instance):
        """
        Transform vector DB result to match Media API V1 format.
        Maps vector DB fields to V1 API fields based on the response structure.
        """
        metadata = instance.get('metadata', {})
        
        # Extract key fields from metadata
        url = metadata.get('url', '')
        company = metadata.get('company', '')
        created_at = metadata.get('created_at', '')
        updated_at = metadata.get('updated_at', '')
        file_type = metadata.get('type', '')
        priority = metadata.get('priority', 'P1')
        
        # Get source_id (this is the actual Media model ID)
        source_id = instance.get('source_id', '')
        
        # Convert source_id to integer if possible
        try:
            media_id = int(source_id) if source_id else None
        except (ValueError, TypeError):
            media_id = source_id
        
        # Get title from metadata or instance
        title = metadata.get('title', instance.get('title', ''))
        
        # Get tags from instance
        tags = instance.get('tags', [])
        
        # Get document_type from metadata
        document_type = None
        for key in ['DOCUMENT_TYPE', 'document_type', 'Document Type']:
            if key in metadata:
                document_type = metadata[key]
                break
        
        # Build response matching V1 format exactly
        return {
            'id': media_id,
            'name': title,
            'description': instance.get('summary', ''),
            'priority': priority,
            'priority_display': priority,
            'media_type': file_type,
            'media_type_display': self._get_media_type_display(file_type),
            'created_at': created_at,
            'updated_at': updated_at,
            's3_url': url,
            'file': url,
            'tag_names': tags,
            'title': title,
            'organization': company,
            'document_type': document_type,
            'key_entities': metadata.get('KEY ENTITIES', metadata.get('key_entities', None)),
            'file_size': metadata.get('file_size', None),
            'organization_url': None,
            'org_logo': None,
            # V2 specific fields (additional metadata)
            'vector_id': instance.get('id'),
            'score': instance.get('score', 0),
            'field_scores': instance.get('field_scores', {}),
        }
    
    def _get_media_type_display(self, mime_type):
        """
        Convert MIME type to display name matching FileTypeChoices.
        """
        mime_to_display = {
            'application/pdf': 'PDF',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'DOCX',
            'application/msword': 'DOC',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'XLSX',
            'application/vnd.ms-excel': 'XLS',
            'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'PPTX',
            'application/vnd.ms-powerpoint': 'PPT',
            'text/plain': 'TXT',
            'text/csv': 'CSV',
            'image/jpeg': 'JPEG',
            'image/png': 'PNG',
            'image/gif': 'GIF',
            'video/mp4': 'MP4',
            'audio/mpeg': 'MP3',
        }
        return mime_to_display.get(mime_type, mime_type.upper() if mime_type else '')


class MediaListSerializer(serializers.ModelSerializer, S3UrlMixin):
    s3_url = serializers.SerializerMethodField()
    file = serializers.SerializerMethodField()
    tag_names = serializers.SerializerMethodField()
    media_type_display = serializers.CharField(source='get_media_type_display', read_only=True)
    priority_display = serializers.CharField(source='get_priority_display', read_only=True)
    title = serializers.SerializerMethodField()
    organization = serializers.SerializerMethodField()
    organization_url = serializers.SerializerMethodField()
    org_logo = serializers.SerializerMethodField()
    document_type = serializers.SerializerMethodField()
    key_entities = serializers.SerializerMethodField()
    file_size = serializers.SerializerMethodField()

    # Search matching scores
    keyword_coverage = serializers.IntegerField(read_only=True)
    total_matching_fields = serializers.IntegerField(read_only=True)
    avg_relevance_score = serializers.FloatField(read_only=True)
    max_similarity = serializers.FloatField(read_only=True)
    match_reason = serializers.SerializerMethodField()

    class Meta:
        model = Media
        fields = [
            'id', 'name', 'description', 'priority', 'priority_display',
            'media_type', 'media_type_display', 'created_at', 'updated_at',
            's3_url', 'file', 'tag_names', 'title', 'organization',
            'document_type', 'key_entities', 'file_size', 'organization_url', 'org_logo',
            'keyword_coverage', 'total_matching_fields', 'avg_relevance_score', 'max_similarity',
            'match_reason'
        ]

    def get_match_reason(self, obj):
        """
        Return a human-readable explanation of why this record was returned.
        Uses the annotated match flags from the viewset.
        """
        # Get the similarity threshold from the request context
        request = self.context.get('request')
        similarity_threshold = 0.3  # default
        if request:
            similarity_threshold = float(request.query_params.get('similarity_threshold', 0.3))

        # Check exact title match first (highest priority)
        if getattr(obj, "exact_title_match_flag", 0) == 1:
            return "Exact title match found."

        # Check trigram similarity match
        if getattr(obj, "trigram_match", 0) == 1:
            max_sim = getattr(obj, "max_similarity", 0)
            if max_sim >= similarity_threshold:
                return f"Fuzzy string similarity match found (similarity: {max_sim:.2f}, threshold: {similarity_threshold})."

        # Check icontains match (substring match)
        if getattr(obj, "icontains_match", 0) == 1:
            return "Direct text match found in one or more fields."

        # Fallback for legacy code or edge cases
        if getattr(obj, "keyword_coverage", 0) > 0:
            return "This result matched your search keywords."

        if getattr(obj, "max_similarity", 0) > 0:
            max_sim = getattr(obj, "max_similarity", 0)
            return f"Fuzzy string similarity found (similarity: {max_sim:.2f})."

        return "Match found through search criteria."

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
        if obj.organization:
            return obj.organization.name
        return None

    def get_organization_url(self, obj):
        if obj.organization:
            return obj.organization.url
        return None

    def get_org_logo(self, obj):
        """Get organization logo S3 URL"""
        if obj.organization and obj.organization.logo:
            return obj.organization.get_public_url()
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
    title = serializers.SerializerMethodField()
    organization = serializers.SerializerMethodField()
    org_logo = serializers.SerializerMethodField()
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
            's3_url', 'tags', 'title', 'organization', 'org_logo', 'document_type',
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
                Q(key__in=['TITLE', 'KEY ENTITIES', 'GEOGRAPHY']) |
                Q(key__iregex=r'^document[_\s]type$')
            ).exclude(
                Q(key__isnull=True, value__isnull=True) |
                Q(key='', value='')
            )
            key_values_data = KeyValueSerializer(metadata_kvs, many=True).data

            # Add organization from direct organization FK if it exists
            if organization_name:
                org_kv = {
                    'id': None,
                    'key': 'ORGANIZATION',
                    'value': organization_name
                }
                key_values_data.append(org_kv)

        if obj.tags.exists():
            tag_names = list(obj.tags.values_list("name", flat=True))
            tags_classification_kv = {
                'id': None,
                'key': 'Tags for Classification',
                'value': tag_names
            }
            key_values_data.append(tags_classification_kv)

        references_html = self._get_references_and_associated_documents(obj)
        if references_html:
            references_kv = {
                'id': None,
                'key': 'References and Associated Documents',
                'value': references_html
            }
            key_values_data.append(references_kv)

        return key_values_data

    def _get_references_and_associated_documents(self, obj):
        """
        Get references and associated documents for a media object.
        """
        references_html = []
        children = obj.subdocuments.all()

        for child in children:
            # Check if child is a "source document"
            child_doc_type_kv = child.key_values.filter(key__iregex=r'^document[_\s]type$').first()
            is_source_doc = False

            if child_doc_type_kv and child_doc_type_kv.value:
                is_source_doc = 'source document' in child_doc_type_kv.value.lower()

            # If it's a source document
            if is_source_doc:
                # Only process if it has VISIBLE children
                if child.subdocuments.filter(display_mode=FileDisplayMode.VISIBLE).exists():
                    grandchildren = child.subdocuments.filter(display_mode=FileDisplayMode.VISIBLE)
                    for grandchild in grandchildren:
                        # Get title for grandchild
                        grandchild_title_kv = grandchild.key_values.filter(key__iexact='TITLE').first()
                        grandchild_title = grandchild_title_kv.value if grandchild_title_kv and grandchild_title_kv.value else grandchild.name

                        references_html.append(
                            f'<div><a class="text-blue-600 underline underline-offset-2" '
                            f'href="/{grandchild.id}" target="_blank" '
                            f'rel="noopener noreferrer">{grandchild_title}</a></div>'
                        )
            else:
                child_title_kv = child.key_values.filter(key__iexact='TITLE').first()
                child_title = child_title_kv.value if child_title_kv and child_title_kv.value else child.name

                # Create HTML link for child
                references_html.append(
                    f'<div><a class="text-blue-600 underline underline-offset-2" '
                    f'href="/{child.id}" target="_blank" '
                    f'rel="noopener noreferrer">{child_title}</a></div>'
                )

        return references_html

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

    def get_org_logo(self, obj):
        """Get organization logo S3 URL"""
        if obj.organization and obj.organization.logo:
            return obj.organization.get_public_url()
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
