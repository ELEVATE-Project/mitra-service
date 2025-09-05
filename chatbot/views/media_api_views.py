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
        resource_type = request.query_params.get('resource_type', '').strip()
        priority = request.query_params.get('priority', '').strip()
        limit = min(int(request.query_params.get('limit', 20)), 100)

        if not 0.0 <= similarity_threshold <= 1.0:
            return Response({
                'error': 'similarity_threshold must be between 0.0 and 1.0'
            }, status=status.HTTP_400_BAD_REQUEST)

        tags_list = [t.strip() for t in tags_param.split(",") if t.strip()] if tags_param else []
        kv_pairs = {}
        if key_values_param:
            for kv in key_values_param.split(","):
                if ":" in kv:
                    k, v = kv.split(":", 1)
                    kv_pairs[k.strip()] = v.strip()

        organizations_list = [org.strip() for org in organization.split(",") if org.strip()] if organization else []
        resource_types_list = [rt.strip() for rt in resource_type.split(",") if rt.strip()] if resource_type else []

        media_types_list = []
        if media_type:
            requested_types = [mt.strip() for mt in media_type.split(",") if mt.strip()]
            media_types_list = self._resolve_media_types(requested_types)

        queryset = self.get_queryset()
        results = None
        search_method = None

        if search_text and len(search_text) >= 3:
            from chatbot.models import KeyValue, Tag

            tag_similarity_subquery = Tag.objects.filter(
                medias=OuterRef('pk')
            ).annotate(
                similarity=TrigramSimilarity('name', search_text)
            ).values('similarity').order_by('-similarity')[:1]

            kv_similarity_subquery = KeyValue.objects.filter(
                media=OuterRef('pk')
            ).annotate(
                similarity=TrigramSimilarity('value', search_text)
            ).values('similarity').order_by('-similarity')[:1]

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
                max_similarity=Greatest(
                    'name_similarity',
                    'desc_similarity',
                    'tag_similarity',
                    'kv_similarity'
                )
            )

            trigram_qs = trigram_qs.filter(max_similarity__gte=similarity_threshold)

            filter_conditions = Q()

            if tags_list:
                tag_conditions = Q()
                for tag in tags_list:
                    tag_conditions |= Q(tags__name__icontains=tag)
                filter_conditions &= tag_conditions

            if kv_pairs:
                for key, value in kv_pairs.items():
                    filter_conditions &= Q(key_values__key__iexact=key, key_values__value__icontains=value)

            if organizations_list:
                org_conditions = Q()
                for org in organizations_list:
                    org_conditions |= Q(
                        key_values__key__iexact='ORGANIZATION',
                        key_values__value__icontains=org
                    )
                filter_conditions &= org_conditions

            if media_types_list:
                filter_conditions &= Q(media_type__in=media_types_list)

            if resource_types_list:
                rt_conditions = Q()
                for rt in resource_types_list:
                    rt_conditions |= Q(
                        key_values__key__iregex=r'^document[_\s]type$',
                        key_values__value__icontains=rt
                    )
                filter_conditions &= rt_conditions

            if priority:
                filter_conditions &= Q(priority=priority)

            if filter_conditions:
                trigram_qs = trigram_qs.filter(filter_conditions)

            trigram_qs = trigram_qs.distinct().order_by('-max_similarity', '-updated_at')[:limit]

            trigram_results = list(trigram_qs)
            if trigram_results:
                results = trigram_results
                search_method = 'trigram_similarity'
                for result in results:
                    result.similarity_info = {
                        'max_value': round(result.max_similarity, 3),
                        'name': round(result.name_similarity, 3),
                        'description': round(result.desc_similarity, 3),
                        'tag': round(result.tag_similarity, 3),
                        'key_value': round(result.kv_similarity, 3)
                    }

        if results is None:
            fallback_conditions = Q()

            if search_text:
                text_conditions = Q()
                text_conditions |= Q(name__icontains=search_text)
                text_conditions |= Q(description__icontains=search_text)
                text_conditions |= Q(tags__name__icontains=search_text)
                text_conditions |= Q(key_values__value__icontains=search_text)
                fallback_conditions &= text_conditions

            if tags_list:
                tag_conditions = Q()
                for tag in tags_list:
                    tag_conditions |= Q(tags__name__icontains=tag)
                fallback_conditions &= tag_conditions

            if kv_pairs:
                for key, value in kv_pairs.items():
                    fallback_conditions &= Q(key_values__key__iexact=key, key_values__value__icontains=value)

            if organizations_list:
                org_conditions = Q()
                for org in organizations_list:
                    org_conditions |= Q(
                        key_values__key__iexact='ORGANIZATION',
                        key_values__value__icontains=org
                    )
                fallback_conditions &= org_conditions

            if media_types_list:
                fallback_conditions &= Q(media_type__in=media_types_list)

            if resource_types_list:
                rt_conditions = Q()
                for rt in resource_types_list:
                    rt_conditions |= Q(
                        key_values__key__iregex=r'^document[_\s]type$',
                        key_values__value__icontains=rt
                    )
                fallback_conditions &= rt_conditions

            if priority:
                fallback_conditions &= Q(priority=priority)

            if fallback_conditions:
                fallback_qs = queryset.filter(fallback_conditions).distinct()
            else:
                fallback_qs = Media.objects.none()

            results = list(fallback_qs.order_by('-updated_at')[:limit])
            search_method = 'fallback_filter'

        serializer = MediaListSerializer(results, many=True)
        serialized_data = serializer.data

        if search_method == 'trigram_similarity' and results and hasattr(results[0], 'similarity_info'):
            for i, item in enumerate(serialized_data):
                if i < len(results) and hasattr(results[i], 'similarity_info'):
                    item['similarity_scores'] = results[i].similarity_info

        response_data = {
            'search_params': {
                'q': search_text,
                'similarity_threshold': similarity_threshold,
                'tags': tags_list,
                'key_values': kv_pairs,
                'organization': organizations_list,
                'media_type': {
                    'requested': media_type.split(',') if media_type else [],
                    'resolved': media_types_list
                },
                'resource_type': resource_types_list,
                'priority': priority,
                'limit': limit
            },
            'search_method': search_method,
            'count': len(serialized_data),
            'results': serialized_data
        }

        return Response(response_data)

    def _resolve_media_types(self, requested_types):
        from chatbot.models import FileTypeChoices

        resolved_types = []

        for requested_type in requested_types:
            requested_lower = requested_type.lower().strip()

            if '/' in requested_type:
                resolved_types.append(requested_type)
                continue

            mime_type = FileTypeChoices.get_mime_from_extension(requested_lower)
            if mime_type:
                resolved_types.append(mime_type)
                continue

            matches = []
            for choice in FileTypeChoices.choices:
                mime_type = choice[0]
                display_name = choice[1] if len(choice) > 1 else mime_type

                if (requested_lower in mime_type.lower() or
                        requested_lower in display_name.lower() or
                        mime_type.lower().endswith(f'/{requested_lower}') or
                        mime_type.lower().startswith(f'{requested_lower}/')):
                    matches.append(mime_type)

            resolved_types.extend(matches)

            if not matches and requested_type not in resolved_types:
                resolved_types.append(requested_type)

        return list(dict.fromkeys(resolved_types))

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

        resource_types = []

        document_type_data = (
            KeyValue.objects
            .filter(
                key__iregex=r'^document[_\s]type$',
                media__in=queryset
            )
            .values('value')
            .annotate(count=Count('media', distinct=True))
            .order_by('value')
        )

        for item in document_type_data:
            document_type_value = item['value']
            count = item['count']

            if document_type_value and count > 0:
                display_name = document_type_value.replace('_', ' ').title()

                resource_types.append({
                    'value': document_type_value,
                    'display': display_name,
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
