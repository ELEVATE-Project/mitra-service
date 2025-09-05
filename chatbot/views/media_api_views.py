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
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter, filters.SearchFilter]
    filterset_class = MediaFilter
    ordering_fields = ['id', 'name', 'created_at', 'updated_at', 'priority', 'media_type', 'organization']
    ordering = ['-created_at']
    search_fields = ['name', 'description', 'extracted_text']

    def get_queryset(self):
        queryset = Media.objects.all()

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

        search_text = self.request.query_params.get('q', '').strip()
        similarity_threshold = float(self.request.query_params.get('similarity_threshold', 0.3))

        if search_text and len(search_text) >= 3:
            queryset = self._apply_trigram_search(queryset, search_text, similarity_threshold)

        queryset = self._apply_custom_filters(queryset)

        if self.action == 'list':
            queryset = queryset.select_related('company_bot', 'parent')
            queryset = queryset.prefetch_related('tags')
        elif self.action == 'retrieve':
            queryset = queryset.select_related('company_bot', 'parent')
            queryset = queryset.prefetch_related(
                'tags', 'key_values', 'images', 'subdocuments'
            )

        return queryset

    def _apply_trigram_search(self, queryset, search_text, similarity_threshold):
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

        queryset = queryset.annotate(
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

        return queryset.filter(max_similarity__gte=similarity_threshold)

    def _apply_custom_filters(self, queryset):
        tags_param = self.request.query_params.get('tags', '').strip()
        key_values_param = self.request.query_params.get('key_values', '').strip()
        organization = self.request.query_params.get('organizations', '').strip()
        media_type = self.request.query_params.get('media_types', '').strip()
        resource_type = self.request.query_params.get('resource_types', '').strip()
        priority = self.request.query_params.get('priorities', '').strip()

        filter_conditions = Q()

        if tags_param:
            tags_list = [t.strip() for t in tags_param.split(",") if t.strip()]
            if tags_list:
                tag_conditions = Q()
                for tag in tags_list:
                    tag_conditions |= Q(tags__name__icontains=tag)
                filter_conditions &= tag_conditions

        if key_values_param:
            kv_pairs = {}
            for kv in key_values_param.split(","):
                if ":" in kv:
                    k, v = kv.split(":", 1)
                    kv_pairs[k.strip()] = v.strip()

            for key, value in kv_pairs.items():
                filter_conditions &= Q(key_values__key__iexact=key, key_values__value__icontains=value)

        # Use subqueries for organization filter to avoid JOIN issues
        if organization:
            organizations_list = [org.strip() for org in organization.split(",") if org.strip()]
            if organizations_list:
                org_conditions = Q()
                for org in organizations_list:
                    org_conditions |= Q(
                        key__iexact='ORGANIZATION',
                        value__icontains=org
                    )

                # Get media IDs that match organization criteria
                matching_org_media_ids = KeyValue.objects.filter(org_conditions).values_list('media_id', flat=True)
                filter_conditions &= Q(id__in=matching_org_media_ids)

        # Use subqueries for resource type filter to avoid JOIN issues
        if resource_type:
            resource_types_list = [rt.strip() for rt in resource_type.split(",") if rt.strip()]
            if resource_types_list:
                rt_conditions = Q()
                for rt in resource_types_list:
                    rt_conditions |= Q(
                        key__iregex=r'^document[_\s]type$',
                        value__icontains=rt
                    )

                # Get media IDs that match resource type criteria
                matching_rt_media_ids = KeyValue.objects.filter(rt_conditions).values_list('media_id', flat=True)
                filter_conditions &= Q(id__in=matching_rt_media_ids)

        if media_type:
            requested_types = [mt.strip() for mt in media_type.split(",") if mt.strip()]
            media_types_list = self._resolve_media_types(requested_types)
            if media_types_list:
                filter_conditions &= Q(media_type__in=media_types_list)

        if priority:
            filter_conditions &= Q(priority=priority)

        if filter_conditions:
            queryset = queryset.filter(filter_conditions).distinct()

        return queryset

    def get_serializer_class(self):
        if self.action == 'list':
            return MediaListSerializer
        return MediaDetailSerializer

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
        from chatbot.models import FileTypeChoices, PriorityChoices

        queryset = self.filter_queryset(self.get_queryset())

        organizations = (
            KeyValue.objects
            .filter(key='ORGANIZATION', media__in=queryset)
            .values('value')
            .annotate(
                lower_value=Lower('value')
            )
            .values('lower_value')
            .distinct()
            .values_list('lower_value', flat=True)
        )
        organizations = sorted([org.title() if org else '' for org in organizations])

        media_types = []
        media_type_counts = dict(
            queryset.values_list('media_type')
            .annotate(count=Count('id'))
            .values_list('media_type', 'count')
        )

        for choice in FileTypeChoices.choices:
            mime_type = choice[0]
            display_name = choice[1]
            count = media_type_counts.get(mime_type, 0)
            if count > 0:
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
        media = self.get_object()

        siblings = Media.objects.none()
        if media.parent:
            siblings = Media.objects.filter(
                parent=media.parent
            ).exclude(id=media.id)

        similar_tags = Media.objects.none()
        if media.tags.exists():
            tag_ids = media.tags.values_list('id', flat=True)
            similar_tags = Media.objects.filter(
                tags__in=tag_ids
            ).exclude(id=media.id).distinct()

        related = (siblings | similar_tags).distinct()[:20]

        serializer = MediaListSerializer(related, many=True)
        return Response({
            'media_id': media.id,
            'related_count': related.count(),
            'related_media': serializer.data
        })
