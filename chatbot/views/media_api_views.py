from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from chatbot.models import Tag, FileTypeChoices
from chatbot.models.media_models import Media, KeyValue
from chatbot.serializer.media_serializer import (
    MediaListSerializer, MediaDetailSerializer
)
from chatbot.filter.media_filters import MediaFilter
from django.contrib.postgres.search import TrigramSimilarity
from django.db.models import Count, Q, Value, FloatField, OuterRef, Subquery, TextField, CharField, IntegerField, Case, \
    When, F
from django.db.models.functions import Greatest, Coalesce, Lower


class MediaViewSet(viewsets.ReadOnlyModelViewSet):
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter, filters.SearchFilter]
    filterset_class = MediaFilter
    ordering_fields = ['id', 'name', 'created_at', 'updated_at', 'priority', 'media_type', 'organization', 'title']
    ordering = ['-created_at']
    search_fields = ['name', 'description', 'extracted_text']

    def get_queryset(self):
        queryset = Media.objects.all()

        title_subquery = KeyValue.objects.filter(
            media=OuterRef('pk'),
            key__iexact='TITLE'
        ).values('value')[:1]

        queryset = queryset.annotate(
            title=Subquery(title_subquery, output_field=CharField()),
            organization_name=Coalesce(
                'organization__name',
                Value('', output_field=CharField())
            ),
            media_type_display=Case(
                *[
                    When(media_type=choice[0], then=Value(str(choice[1])))
                    for choice in FileTypeChoices.choices
                ],
                default=Value(''),
                output_field=CharField()
            )
        )

        search_text = self.request.query_params.get('q', '').strip()
        similarity_threshold = float(self.request.query_params.get('similarity_threshold', 0.3))

        if search_text and len(search_text) >= 3:
            queryset = self._apply_enhanced_multi_keyword_search(queryset, search_text, similarity_threshold)
        else:
            # Add default score annotations for non-search queries
            queryset = queryset.annotate(
                keyword_coverage=Value(0, output_field=IntegerField()),
                total_matching_fields=Value(0, output_field=IntegerField()),
                avg_relevance_score=Value(0.0, output_field=FloatField()),
                max_similarity=Value(0.0, output_field=FloatField())
            )

        queryset = self._apply_custom_filters(queryset)

        if self.action == 'list':
            queryset = self._apply_content_exclusion_filter(queryset)
            queryset = queryset.select_related('organization', 'parent').prefetch_related('tags')
        elif self.action == 'retrieve':
            queryset = queryset.select_related('organization', 'parent').prefetch_related(
                'tags', 'key_values', 'images', 'subdocuments'
            )

        return queryset

    def _apply_content_exclusion_filter(self, queryset):
        """
        Exclude media where document_type is "Source Document"
        """
        source_document_media = KeyValue.objects.annotate(
            norm_key=Lower('key', output_field=TextField())
        ).filter(
            norm_key__iregex=r'^document[_\s]type$',
            value__icontains='source document'
        ).values_list('media_id', flat=True)

        return queryset.exclude(id__in=source_document_media)

    def _apply_enhanced_multi_keyword_search(self, queryset, search_text, similarity_threshold):
        """
        Enhanced search with multi-keyword ranking:
        Search fields: Title, Organization, Document Type, Tags, Media Type
        Ranking:
        1. Files matching multiple keywords listed first
        2. Files matching single keyword listed last
        3. Within each group, ordered by relevance score (highest first)
        4. Four-level ranking: keyword_coverage -> total_matching_fields -> avg_relevance_score -> max_similarity
        """
        # Split search text into keywords
        keywords = [keyword.strip().lower() for keyword in search_text.split() if keyword.strip()]

        if not keywords:
            return queryset

        # Get document type subquery
        doc_type_subquery = KeyValue.objects.filter(
            media=OuterRef('pk'),
            key__iregex=r'^document[_\s]type$'
        ).values('value')[:1]

        queryset = queryset.annotate(
            doc_type=Subquery(doc_type_subquery, output_field=CharField())
        )

        # Initialize aggregated scores
        total_matching_fields = Value(0, output_field=IntegerField())
        total_relevance_score = Value(0.0, output_field=FloatField())
        max_similarity_overall = Value(0.0, output_field=FloatField())
        keyword_coverage_score = Value(0, output_field=IntegerField())

        # Process each keyword and build annotations
        keyword_annotations = {}

        for i, keyword in enumerate(keywords):
            # Tag similarity subquery for this keyword
            tag_similarity_subquery = Tag.objects.filter(
                medias=OuterRef('pk')
            ).annotate(
                similarity=TrigramSimilarity('name', keyword)
            ).values('similarity').order_by('-similarity')[:1]

            # Individual field similarities for this keyword
            keyword_annotations.update({
                f'title_sim_{i}': Coalesce(
                    TrigramSimilarity('title', keyword),
                    Value(0.0, output_field=FloatField())
                ),
                f'org_sim_{i}': Coalesce(
                    TrigramSimilarity('organization_name', keyword),
                    Value(0.0, output_field=FloatField())
                ),
                f'doc_type_sim_{i}': Coalesce(
                    TrigramSimilarity('doc_type', keyword),
                    Value(0.0, output_field=FloatField())
                ),
                f'tag_sim_{i}': Coalesce(
                    Subquery(tag_similarity_subquery),
                    Value(0.0, output_field=FloatField())
                ),
                f'media_type_display_sim_{i}': Coalesce(
                    TrigramSimilarity('media_type_display', keyword),
                    Value(0.0, output_field=FloatField())
                )
            })

        # Apply all keyword annotations at once
        queryset = queryset.annotate(**keyword_annotations)

        # Now calculate aggregated scores
        for i, keyword in enumerate(keywords):
            # Count matching fields for this keyword (fields above threshold)
            keyword_matching_fields = (
                    Case(When(**{f'title_sim_{i}__gte': similarity_threshold}, then=Value(1)),
                         default=Value(0), output_field=IntegerField()) +
                    Case(When(**{f'org_sim_{i}__gte': similarity_threshold}, then=Value(1)),
                         default=Value(0), output_field=IntegerField()) +
                    Case(When(**{f'doc_type_sim_{i}__gte': similarity_threshold}, then=Value(1)),
                         default=Value(0), output_field=IntegerField()) +
                    Case(When(**{f'tag_sim_{i}__gte': similarity_threshold}, then=Value(1)),
                         default=Value(0), output_field=IntegerField()) +
                    Case(When(**{f'media_type_display_sim_{i}__gte': similarity_threshold}, then=Value(1)),
                         default=Value(0), output_field=IntegerField())

            )

            # Calculate weighted relevance score for this keyword
            keyword_relevance = (
                    2.0 * F(f'title_sim_{i}') +  # Title: highest priority
                    1.8 * F(f'tag_sim_{i}') +  # Tags: very important
                    1.6 * F(f'doc_type_sim_{i}') +  # Document Type: important
                    1.4 * F(f'org_sim_{i}') +  # Organization: moderately important
                    1.2 * F(f'media_type_display_sim_{i}')  # Media Type: lower priority
            )

            # Get max similarity for this keyword across all fields
            keyword_max_sim = Greatest(
                f'title_sim_{i}', f'org_sim_{i}', f'doc_type_sim_{i}',
                f'tag_sim_{i}', f'media_type_display_sim_{i}'
            )

            # Check if this keyword has any match above threshold (for keyword coverage)
            keyword_has_match = Case(
                When(
                    Q(**{f'title_sim_{i}__gte': similarity_threshold}) |
                    Q(**{f'org_sim_{i}__gte': similarity_threshold}) |
                    Q(**{f'doc_type_sim_{i}__gte': similarity_threshold}) |
                    Q(**{f'tag_sim_{i}__gte': similarity_threshold}) |
                    Q(**{f'media_type_display_sim_{i}__gte': similarity_threshold}),
                    then=Value(1)
                ),
                default=Value(0),
                output_field=IntegerField()
            )

            # Aggregate totals
            total_matching_fields = total_matching_fields + keyword_matching_fields
            total_relevance_score = total_relevance_score + keyword_relevance
            max_similarity_overall = Greatest(max_similarity_overall, keyword_max_sim)
            keyword_coverage_score = keyword_coverage_score + keyword_has_match

        # Final annotations for ranking
        queryset = queryset.annotate(
            keyword_coverage=keyword_coverage_score,  # How many keywords matched
            total_matching_fields=total_matching_fields,  # Total field matches across all keywords
            avg_relevance_score=total_relevance_score / len(keywords),  # Average weighted relevance
            max_similarity=max_similarity_overall  # Best single similarity score
        )

        # Filter results that meet minimum threshold and apply 4-level ranking
        return queryset.filter(
            max_similarity__gte=similarity_threshold
        ).order_by(
            '-keyword_coverage',  # 1st: Files matching more keywords first
            '-total_matching_fields',  # 2nd: More field matches within keyword groups
            '-avg_relevance_score',  # 3rd: Higher weighted relevance scores
            '-max_similarity'  # 4th: Best individual field match
        )

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

        if organization:
            organizations_list = [org.strip() for org in organization.split(",") if org.strip()]
            if organizations_list:
                org_conditions = Q()
                for org in organizations_list:
                    org_conditions |= Q(organization__name__icontains=org)
                filter_conditions &= org_conditions

        if resource_type:
            resource_types_list = [rt.strip() for rt in resource_type.split(",") if rt.strip()]
            if resource_types_list:
                rt_conditions = Q()
                for rt in resource_types_list:
                    rt_conditions |= Q(
                        key_values__key__iregex=r'^document[_\s]type$',
                        key_values__value__icontains=rt
                    )
                filter_conditions &= rt_conditions

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

    def _resolve_keyword_to_mime_types(self, keyword):
        """
        Convert file extension keywords to MIME types using FileTypeChoices
        Examples: 'pdf' -> ['application/pdf'], 'docx' -> ['application/vnd.openxmlformats-officedocument.wordprocessingml.document']
        """
        from chatbot.models import FileTypeChoices

        keyword_lower = keyword.lower().strip()
        resolved_types = []

        # Use FileTypeChoices method to get MIME type from extension
        mime_type = FileTypeChoices.get_mime_from_extension(keyword_lower)
        if mime_type:
            resolved_types.append(mime_type)
            return resolved_types

        # Check if keyword matches any valid extensions from FileTypeChoices
        valid_extensions = FileTypeChoices.get_valid_extensions()
        if keyword_lower in valid_extensions:
            mime_type = FileTypeChoices.get_mime_from_extension(keyword_lower)
            if mime_type:
                resolved_types.append(mime_type)
                return resolved_types

        # Fallback: search in FileTypeChoices for partial matches
        for choice in FileTypeChoices.choices:
            mime_type = choice[0]
            display_name = choice[1] if len(choice) > 1 else mime_type

            if (keyword_lower in mime_type.lower() or
                    keyword_lower in display_name.lower() or
                    mime_type.lower().endswith(f'/{keyword_lower}') or
                    mime_type.lower().startswith(f'{keyword_lower}/')):
                resolved_types.append(mime_type)

        return resolved_types if resolved_types else None

    def _resolve_media_types(self, requested_types):
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
        from chatbot.models import PriorityChoices

        queryset = self.filter_queryset(self.get_queryset())

        # Already correct - using direct organization field
        organizations = (
            queryset
            .exclude(organization__name__isnull=True)
            .exclude(organization__name='')
            .annotate(
                lower_name=Lower('organization__name')
            )
            .values_list('lower_name', flat=True)
            .distinct()
        )
        # Convert to set to remove any remaining duplicates, then sort
        organizations = sorted(list(set([org.title() for org in organizations if org])))

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
