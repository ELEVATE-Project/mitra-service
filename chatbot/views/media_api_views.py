from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from chatbot.models import Tag
from chatbot.models.media_models import Media, KeyValue
from chatbot.serializer.media_serializer import (
    MediaListSerializer, MediaDetailSerializer
)
from chatbot.filter.media_filters import MediaFilter
from django.contrib.postgres.search import TrigramSimilarity
from django.db.models import Count, Q, Value, FloatField, OuterRef, Subquery, CharField
from django.db.models.functions import Greatest, Coalesce
from django.db.models.functions import Lower


class MediaViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for Media objects - read-only operations

    list: Get paginated list of media with filtering and sorting
    retrieve: Get single media by ID with full details
    search_similar: Search for similar media based on text
    statistics: Get media statistics
    """
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter, filters.SearchFilter]
    filterset_class = MediaFilter
    ordering_fields = ['id', 'name', 'created_at', 'updated_at', 'priority', 'media_type', 'organization']
    ordering = ['-created_at']  # Default ordering
    search_fields = ['name', 'description', 'extracted_text']

    def get_queryset(self):
        """Base queryset with optimizations"""
        queryset = Media.objects.all()

        # Add organization annotation for ordering
        org_subquery = KeyValue.objects.filter(
            media=OuterRef('pk'),
            key='ORGANIZATION'
        ).values('value')[:1]

        queryset = queryset.annotate(
            organization=Coalesce(
                Subquery(org_subquery),
                Value('', output_field=CharField())
            )
        )

        # Optimize queries based on action
        if self.action == 'list':
            queryset = queryset.select_related('company_bot', 'parent')
            queryset = queryset.prefetch_related('tags')
        elif self.action == 'retrieve':
            queryset = queryset.select_related('company_bot', 'parent')
            queryset = queryset.prefetch_related(
                'tags', 'key_values', 'images', 'subdocuments'
            )

        return queryset

    def get_serializer_class(self):
        """Use different serializers for list and detail views"""
        if self.action == 'list':
            return MediaListSerializer
        return MediaDetailSerializer


    @action(detail=False, methods=['get'])
    def search_similar(self, request):
        """
        Advanced search with trigram similarity and multiple filters
        Query params:
        - q: Text to search (uses trigram similarity)
        - similarity_threshold: Minimum similarity score (0.0-1.0, default 0.3)
        - tags: Comma-separated tag names
        - key_values: Comma-separated key:value pairs
        - organization: Organization name filter
        - media_type: Media type filter
        - priority: Priority filter (P1, P2, etc.)
        - limit: Maximum results (default 20, max 100)
        """
        # Parse parameters
        search_text = request.query_params.get('q', '').strip()
        similarity_threshold = float(request.query_params.get('similarity_threshold', 0.3))
        tags_param = request.query_params.get('tags', '').strip()
        key_values_param = request.query_params.get('key_values', '').strip()
        organization = request.query_params.get('organization', '').strip()
        media_type = request.query_params.get('media_type', '').strip()
        priority = request.query_params.get('priority', '').strip()
        limit = min(int(request.query_params.get('limit', 20)), 100)

        # Validate similarity threshold
        if not 0.0 <= similarity_threshold <= 1.0:
            return Response({
                'error': 'similarity_threshold must be between 0.0 and 1.0'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Parse tags and key-values
        tags_list = [t.strip() for t in tags_param.split(",") if t.strip()] if tags_param else []
        kv_pairs = {}
        if key_values_param:
            for kv in key_values_param.split(","):
                if ":" in kv:
                    k, v = kv.split(":", 1)
                    kv_pairs[k.strip()] = v.strip()

        # Start with base queryset
        queryset = self.get_queryset()
        results = None
        search_method = None

        # STEP 1: Try trigram similarity search if text is provided
        if search_text and len(search_text) >= 3:  # Trigram needs at least 3 characters
            # Create subqueries that properly scope to current media item
            from chatbot.models import KeyValue, Tag

            # Subquery for max tag similarity for current media
            tag_similarity_subquery = Tag.objects.filter(
                medias=OuterRef('pk')  # Use the related_name from ManyToMany
            ).annotate(
                similarity=TrigramSimilarity('name', search_text)
            ).values('similarity').order_by('-similarity')[:1]

            # Subquery for max key value similarity for current media
            kv_similarity_subquery = KeyValue.objects.filter(
                media=OuterRef('pk')  # Direct foreign key reference
            ).annotate(
                similarity=TrigramSimilarity('value', search_text)
            ).values('similarity').order_by('-similarity')[:1]

            # Annotate with similarity scores
            trigram_qs = queryset.annotate(
                name_similarity=Coalesce(
                    TrigramSimilarity('name', search_text),
                    Value(0.0, output_field=FloatField())
                ),
                desc_similarity=Coalesce(
                    TrigramSimilarity('description', search_text),
                    Value(0.0, output_field=FloatField())
                ),
                tag_similarity=Coalesce(
                    Subquery(tag_similarity_subquery),
                    Value(0.0, output_field=FloatField())
                ),
                kv_similarity=Coalesce(
                    Subquery(kv_similarity_subquery),
                    Value(0.0, output_field=FloatField())
                ),
                # Max similarity - take the highest score
                max_similarity=Greatest(
                    'name_similarity',
                    'desc_similarity',
                    'tag_similarity',
                    'kv_similarity'
                )
            )

            # Apply similarity threshold
            trigram_qs = trigram_qs.filter(max_similarity__gte=similarity_threshold)

            # Apply additional filters if provided
            filter_conditions = Q()

            if tags_list:
                tag_conditions = Q()
                for tag in tags_list:
                    tag_conditions |= Q(tags__name__icontains=tag)
                filter_conditions &= tag_conditions

            if kv_pairs:
                for key, value in kv_pairs.items():
                    filter_conditions &= Q(key_values__key__iexact=key, key_values__value__icontains=value)

            if organization:
                filter_conditions &= Q(
                    key_values__key__iexact='ORGANIZATION',
                    key_values__value__icontains=organization
                )

            if media_type:
                filter_conditions &= Q(media_type=media_type)

            if priority:
                filter_conditions &= Q(priority=priority)

            if filter_conditions:
                trigram_qs = trigram_qs.filter(filter_conditions)

            # Get distinct results ordered by similarity
            trigram_qs = trigram_qs.distinct().order_by('-max_similarity', '-updated_at')[:limit]

            # Check if we have results
            trigram_results = list(trigram_qs)
            if trigram_results:
                results = trigram_results
                search_method = 'trigram_similarity'
                # Add similarity scores to results for debugging
                for result in results:
                    result.similarity_info = {
                        'max_value': round(result.max_similarity, 3),
                        'name': round(result.name_similarity, 3),
                        'description': round(result.desc_similarity, 3),
                        'tag': round(result.tag_similarity, 3),
                        'key_value': round(result.kv_similarity, 3)
                    }

        # STEP 2: Fallback to basic filtering if no trigram results or no search text
        if results is None:
            fallback_conditions = Q()

            # Text search using icontains (less sophisticated)
            if search_text:
                text_conditions = Q()
                text_conditions |= Q(name__icontains=search_text)
                text_conditions |= Q(description__icontains=search_text)
                text_conditions |= Q(tags__name__icontains=search_text)
                text_conditions |= Q(key_values__value__icontains=search_text)
                fallback_conditions &= text_conditions

            # Apply all other filters
            if tags_list:
                tag_conditions = Q()
                for tag in tags_list:
                    tag_conditions |= Q(tags__name__icontains=tag)
                fallback_conditions &= tag_conditions

            if kv_pairs:
                for key, value in kv_pairs.items():
                    fallback_conditions &= Q(key_values__key__iexact=key, key_values__value__icontains=value)

            if organization:
                fallback_conditions &= Q(
                    key_values__key__iexact='ORGANIZATION',
                    key_values__value__icontains=organization
                )

            if media_type:
                fallback_conditions &= Q(media_type=media_type)

            if priority:
                fallback_conditions &= Q(priority=priority)

            # Apply filters and get results
            if fallback_conditions:
                fallback_qs = queryset.filter(fallback_conditions).distinct()
            else:
                # If no conditions, return empty results
                fallback_qs = Media.objects.none()

            results = list(fallback_qs.order_by('-updated_at')[:limit])
            search_method = 'fallback_filter'

        # Serialize results
        serializer = MediaListSerializer(results, many=True)
        serialized_data = serializer.data

        # Add similarity scores to response if using trigram
        if search_method == 'trigram_similarity' and results and hasattr(results[0], 'similarity_info'):
            for i, item in enumerate(serialized_data):
                if i < len(results) and hasattr(results[i], 'similarity_info'):
                    item['similarity_scores'] = results[i].similarity_info

        # Build response
        response_data = {
            'search_params': {
                'q': search_text,
                'similarity_threshold': similarity_threshold,
                'tags': tags_list,
                'key_values': kv_pairs,
                'organization': organization,
                'media_type': media_type,
                'priority': priority,
                'limit': limit
            },
            'search_method': search_method,
            'count': len(serialized_data),
            'results': serialized_data
        }

        return Response(response_data)

    @action(detail=False, methods=['get'])
    def master_list(self, request):
        """Get master data for filters and dropdowns"""
        from chatbot.models import FileTypeChoices, MediaTypeChoices, PriorityChoices

        queryset = self.filter_queryset(self.get_queryset())

        # Get all unique organizations from key_values
        organizations = (
            KeyValue.objects
            .filter(key='ORGANIZATION', media__in=queryset)
            .values('value')
            .annotate(
                # Create lowercase version for grouping
                lower_value=Lower('value')
            )
            .values('lower_value')
            .distinct()
            .values_list('lower_value', flat=True)
        )
        organizations = sorted([org.title() if org else '' for org in organizations])

        # Get all media types with counts
        media_types = []
        media_type_counts = dict(
            queryset.values_list('media_type')
            .annotate(count=Count('id'))
            .values_list('media_type', 'count')
        )

        # Map media types to display names using FileTypeChoices
        for choice in FileTypeChoices.choices:
            mime_type = choice[0]
            display_name = choice[1]
            count = media_type_counts.get(mime_type, 0)
            if count > 0:  # Only include types that exist in the data
                media_types.append({
                    'value': mime_type,
                    'display': display_name,
                    'count': count
                })

        # Initialize resource type counts
        resource_counts = {
            'documents': 0,
            'images': 0,
            'spreadsheets': 0,
            'videos': 0,
            'audio': 0,
            'other': 0
        }

        # Define document and spreadsheet MIME types from FileTypeChoices
        document_types = [FileTypeChoices.PDF.value, FileTypeChoices.DOC.value,
                          FileTypeChoices.DOCX.value, FileTypeChoices.TXT.value]
        spreadsheet_types = [FileTypeChoices.CSV.value, FileTypeChoices.XLS.value,
                             FileTypeChoices.XLSX.value]

        # Define image MIME types from MediaTypeChoices
        image_types = [MediaTypeChoices.JPEG.value, MediaTypeChoices.PNG.value,
                       MediaTypeChoices.SVG.value, MediaTypeChoices.WEBP.value,
                       MediaTypeChoices.HEIF.value, MediaTypeChoices.HEIC.value]

        # Categorize based on MIME types
        for mime_type, count in media_type_counts.items():
            if mime_type in document_types:
                resource_counts['documents'] += count
            elif mime_type in spreadsheet_types:
                resource_counts['spreadsheets'] += count
            elif mime_type in image_types:
                resource_counts['images'] += count
            elif 'video' in mime_type.lower():
                resource_counts['videos'] += count
            elif 'audio' in mime_type.lower():
                resource_counts['audio'] += count
            else:
                resource_counts['other'] += count

        # Format resource_types in the same structure as media_types
        resource_types = []
        resource_type_display_names = {
            'documents': 'Documents',
            'spreadsheets': 'Spreadsheets',
            'images': 'Images',
            'videos': 'Videos',
            'audio': 'Audio',
            'other': 'Other'
        }

        for resource_type, count in resource_counts.items():
            if count > 0:  # Only include types that exist
                resource_types.append({
                    'value': resource_type,
                    'display': resource_type_display_names[resource_type],
                    'count': count
                })

        # Get all priorities with counts
        priorities = []
        priority_counts = dict(
            queryset.values_list('priority')
            .annotate(count=Count('id'))
            .values_list('priority', 'count')
        )

        for choice in PriorityChoices.choices:
            priority_value = choice[0]
            count = priority_counts.get(priority_value, 0)
            if count > 0:
                priorities.append({
                    'value': priority_value,
                    'display': choice[1] if len(choice) > 1 else priority_value,
                    'count': count
                })

        # Get all tags
        tags = list(
            Tag.objects
            .filter(medias__in=queryset)
            .values('id', 'name')
            .annotate(count=Count('medias'))
            .order_by('name')
            .distinct()
        )

        return Response({
            'total_count': queryset.count(),
            'organizations': list(organizations),
            'media_types': media_types,
            'resource_types': resource_types,
            'priorities': priorities,
            'tags': tags
        })

    @action(detail=True, methods=['get'])
    def related_media(self, request, pk=None):
        """Get media related to this one (same parent or same tags)"""
        media = self.get_object()

        # Get media with same parent
        siblings = Media.objects.none()
        if media.parent:
            siblings = Media.objects.filter(
                parent=media.parent
            ).exclude(id=media.id)

        # Get media with similar tags
        similar_tags = Media.objects.none()
        if media.tags.exists():
            tag_ids = media.tags.values_list('id', flat=True)
            similar_tags = Media.objects.filter(
                tags__in=tag_ids
            ).exclude(id=media.id).distinct()

        # Combine and limit results
        related = (siblings | similar_tags).distinct()[:20]

        serializer = MediaListSerializer(related, many=True)
        return Response({
            'media_id': media.id,
            'related_count': related.count(),
            'related_media': serializer.data
        })
