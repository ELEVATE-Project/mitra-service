from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django_filters.rest_framework import DjangoFilterBackend
from django.db import models

from chatbot.models import Tag, FileTypeChoices, FileDisplayMode
from chatbot.models.media_models import Media, KeyValue
from chatbot.serializer.media_serializer import (
    MediaListSerializer, MediaDetailSerializer, MediaSearchResultSerializer
)
from chatbot.filter.media_filters import MediaFilter
from chatbot.utils.chat_query_handler import query_database_with_metadata
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

    def filter_queryset(self, queryset):
        """
        Override to skip OrderingFilter when search is active to preserve search ranking
        """
        search_text = self.request.query_params.get('q', '').strip()

        if search_text and len(search_text) >= 3:
            # When search is active, apply all filters except OrderingFilter
            for backend in self.filter_backends:
                if backend != filters.OrderingFilter:
                    queryset = backend().filter_queryset(self.request, queryset, self)
            return queryset
        else:
            # Normal filtering when no search - apply all backends
            return super().filter_queryset(queryset)

    def get_queryset(self):
        # Filter to only show media with display_mode set to VISIBLE
        queryset = Media.objects.filter(display_mode=FileDisplayMode.VISIBLE)

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
            # SEARCH MODE: Apply search ranking and ignore other ordering
            queryset = self._apply_enhanced_multi_keyword_search(queryset, search_text, similarity_threshold)
            queryset = self._apply_custom_filters(queryset)
            # DO NOT apply any other ordering - search method handles it
        else:
            # NON-SEARCH MODE: Apply normal ordering
            queryset = queryset.annotate(
                keyword_coverage=Value(0, output_field=IntegerField()),
                total_matching_fields=Value(0, output_field=IntegerField()),
                avg_relevance_score=Value(0.0, output_field=FloatField()),
                max_similarity=Value(0.0, output_field=FloatField()),
                exact_title_match_flag=Value(0, output_field=IntegerField()),
                trigram_match=Value(0, output_field=IntegerField()),
                icontains_match=Value(0, output_field=IntegerField())
            )
            queryset = self._apply_custom_filters(queryset)
            # Normal ordering will be applied by DRF's OrderingFilter

        if self.action == 'list':
            queryset = self._apply_content_exclusion_filter(queryset)
            queryset = queryset.select_related('organization', 'parent').prefetch_related('tags')
        elif self.action == 'retrieve':
            queryset = queryset.select_related('organization', 'parent').prefetch_related(
                'tags', 'key_values', 'images', 'subdocuments'
            )

        return queryset.distinct()

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
        Enhanced search with multi-keyword ranking + exact + substring fallback.
        Search fields: Title, Organization, Document Type, Tags, Media Type
        Ranking priority:
            1. Exact title matches (always on top)
            2. Trigram similarity above threshold
            3. icontains fallback
        """
        keywords = [kw.strip().lower() for kw in search_text.split() if kw.strip()]
        if not keywords:
            return queryset.annotate(
                keyword_coverage=Value(0, output_field=IntegerField()),
                total_matching_fields=Value(0, output_field=IntegerField()),
                avg_relevance_score=Value(0.0, output_field=FloatField()),
                max_similarity=Value(0.0, output_field=FloatField()),
                exact_title_match_flag=Value(0, output_field=IntegerField()),
                trigram_match=Value(0, output_field=IntegerField()),
                icontains_match=Value(0, output_field=IntegerField())
            )

        # Document type subquery
        doc_type_subquery = KeyValue.objects.filter(
            media=OuterRef('pk'),
            key__iregex=r'^document[_\s]type$'
        ).values('value')[:1]

        queryset = queryset.annotate(
            doc_type=Subquery(doc_type_subquery, output_field=CharField()),
            exact_title_match=Case(
                When(title__iexact=search_text.strip(), then=Value(1)),
                default=Value(0),
                output_field=IntegerField()
            )
        )

        keyword_annotations = {}
        for i, keyword in enumerate(keywords):
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
                    Subquery(
                        Tag.objects.filter(
                            medias=OuterRef('pk')
                        ).annotate(
                            similarity=TrigramSimilarity('name', keyword)
                        ).values('similarity').order_by('-similarity')[:1]
                    ),
                    Value(0.0, output_field=FloatField())
                ),
                f'media_type_display_sim_{i}': Coalesce(
                    TrigramSimilarity('media_type_display', keyword),
                    Value(0.0, output_field=FloatField())
                )
            })

        queryset = queryset.annotate(**keyword_annotations)

        # Aggregate scores across keywords
        total_matching_fields = Value(0, output_field=IntegerField())
        total_relevance_score = Value(0.0, output_field=FloatField())
        max_similarity_overall = Value(0.0, output_field=FloatField())
        keyword_coverage_score = Value(0, output_field=IntegerField())

        for i, keyword in enumerate(keywords):
            keyword_matching_fields = (
                    Case(When(**{f'title_sim_{i}__gte': similarity_threshold}, then=Value(1)), default=Value(0),
                         output_field=IntegerField()) +
                    Case(When(**{f'org_sim_{i}__gte': similarity_threshold}, then=Value(1)), default=Value(0),
                         output_field=IntegerField()) +
                    Case(When(**{f'doc_type_sim_{i}__gte': similarity_threshold}, then=Value(1)), default=Value(0),
                         output_field=IntegerField()) +
                    Case(When(**{f'tag_sim_{i}__gte': similarity_threshold}, then=Value(1)), default=Value(0),
                         output_field=IntegerField()) +
                    Case(When(**{f'media_type_display_sim_{i}__gte': similarity_threshold}, then=Value(1)),
                         default=Value(0), output_field=IntegerField())
            )

            keyword_relevance = (
                    2.0 * F(f'title_sim_{i}') +
                    1.8 * F(f'tag_sim_{i}') +
                    1.6 * F(f'doc_type_sim_{i}') +
                    1.4 * F(f'org_sim_{i}') +
                    1.2 * F(f'media_type_display_sim_{i}')
            )

            keyword_max_sim = Greatest(
                f'title_sim_{i}', f'org_sim_{i}', f'doc_type_sim_{i}',
                f'tag_sim_{i}', f'media_type_display_sim_{i}'
            )

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

            total_matching_fields = total_matching_fields + keyword_matching_fields
            total_relevance_score = total_relevance_score + keyword_relevance
            max_similarity_overall = Greatest(max_similarity_overall, keyword_max_sim)
            keyword_coverage_score = keyword_coverage_score + keyword_has_match

        # Annotate final scores
        queryset = queryset.annotate(
            keyword_coverage=keyword_coverage_score,
            total_matching_fields=total_matching_fields,
            avg_relevance_score=total_relevance_score / len(keywords),
            max_similarity=max_similarity_overall
        )

        # Check for exact title match
        exact_title_condition = Q(title__iexact=search_text.strip())

        # Check for trigram similarity above threshold
        trigram_condition = Q(max_similarity__gte=similarity_threshold)

        # icontains fallback - check each field individually to avoid joins
        icontains_condition = (
                Q(title__icontains=search_text) |
                Q(organization_name__icontains=search_text) |
                Q(doc_type__icontains=search_text) |
                Q(media_type_display__icontains=search_text)
        )

        # Add tags icontains check using EXISTS subquery to avoid duplicates
        tag_icontains_condition = Q(
            id__in=Subquery(
                Tag.objects.filter(
                    medias=OuterRef('pk'),
                    name__icontains=search_text
                ).values('medias__id')
            )
        )

        icontains_condition |= tag_icontains_condition

        queryset = queryset.annotate(
            exact_title_match_flag=Case(
                When(exact_title_condition, then=Value(1)),
                default=Value(0),
                output_field=IntegerField()
            ),
            trigram_match=Case(
                When(trigram_condition, then=Value(1)),
                default=Value(0),
                output_field=IntegerField()
            ),
            icontains_match=Case(
                When(icontains_condition, then=Value(1)),
                default=Value(0),
                output_field=IntegerField()
            )
        )

        # Filter results that match any method
        queryset = queryset.filter(
            Q(exact_title_match_flag=1) | Q(trigram_match=1) | Q(icontains_match=1)
        )

        # Order by ranking
        return queryset.order_by(
            '-exact_title_match_flag',  # Exact title match ALWAYS first
            '-keyword_coverage',  # Then by keyword coverage
            '-total_matching_fields',  # Then by matching fields count
            '-avg_relevance_score',  # Then by relevance score
            '-max_similarity',  # Then by similarity
            '-trigram_match',  # Then trigram matches
            '-icontains_match'  # Finally substring matches
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
                    # Use EXISTS subquery to avoid duplicates
                    tag_conditions |= Q(
                        id__in=Subquery(
                            Tag.objects.filter(
                                medias=OuterRef('pk'),
                                name__icontains=tag
                            ).values('medias__id')
                        )
                    )
                filter_conditions &= tag_conditions

        if key_values_param:
            kv_pairs = {}
            for kv in key_values_param.split(","):
                if ":" in kv:
                    k, v = kv.split(":", 1)
                    kv_pairs[k.strip()] = v.strip()

            for key, value in kv_pairs.items():
                # Use EXISTS subquery to avoid duplicates
                filter_conditions &= Q(
                    id__in=Subquery(
                        KeyValue.objects.filter(
                            media=OuterRef('pk'),
                            key__iexact=key,
                            value__icontains=value
                        ).values('media__id')
                    )
                )

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
                    # Use EXISTS subquery to avoid duplicates
                    rt_conditions |= Q(
                        id__in=Subquery(
                            KeyValue.objects.filter(
                                media=OuterRef('pk'),
                                key__iregex=r'^document[_\s]type$',
                                value__icontains=rt
                            ).values('media__id')
                        )
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
            queryset = queryset.filter(filter_conditions)

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
                parent=media.parent,
                display_mode=FileDisplayMode.VISIBLE
            ).exclude(id=media.id)

        similar_tags = Media.objects.none()
        if media.tags.exists():
            tag_ids = media.tags.values_list('id', flat=True)
            similar_tags = Media.objects.filter(
                tags__in=tag_ids,
                display_mode=FileDisplayMode.VISIBLE
            ).exclude(id=media.id).distinct()

        related = (siblings | similar_tags).distinct()[:20]

        serializer = MediaListSerializer(related, many=True)
        return Response({
            'media_id': media.id,
            'related_count': related.count(),
            'related_media': serializer.data
        })


class MediaSearchV2View(APIView):
    """
    Version 2 of Media Search API that uses vector database search.
    
    GET /api/v2/media/?q=education classroom&limit=12&offset=0&ordering=-created_at
    GET /ai/documents/search?q=education classroom&limit=12&offset=0
    
    Query Parameters:
        - q (optional): Search query string. If not provided, returns all documents with filters applied
        - limit (optional): Number of results per page (default: 20)
        - offset (optional): Pagination offset (default: 0)
        - ordering (optional): Sort order (not used in v2, kept for compatibility)
        - categories (optional): Comma-separated list of categories/tags
        - organizations (optional): Comma-separated list of organizations
        - resource_type (optional): Comma-separated list of resource types
        - file_type (optional): Comma-separated list of file types (MIME types)
    """
    
    def get(self, request, format=None):
        # Extract query parameters
        query = request.query_params.get('q', '').strip()
        
        # Pagination parameters
        try:
            limit = int(request.query_params.get('limit', 20))
            offset = int(request.query_params.get('offset', 0))
        except ValueError:
            return Response({
                "error": "Invalid limit or offset parameter",
                "count": 0,
                "next": None,
                "previous": None,
                "results": []
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Filter parameters (convert comma-separated strings to lists)
        categories = self._parse_list_param(request.query_params.get('categories', ''))
        organizations = self._parse_list_param(request.query_params.get('organizations', ''))
        resource_type = self._parse_list_param(request.query_params.get('resource_type', ''))
        file_type = self._parse_list_param(request.query_params.get('file_type', ''))
        
        # Calculate top_k for vector DB (offset + limit to get enough results)
        top_k = offset + limit
        
        print(f"[MediaSearchV2View] Query: '{query}', top_k: {top_k}, offset: {offset}, limit: {limit}")
        print(f"[MediaSearchV2View] Filters - categories: {categories}, organizations: {organizations}, "
              f"resource_type: {resource_type}, file_type: {file_type}")
        
        # Call vector database search
        # If query is empty, pass None or empty string to get all documents with filters
        vector_response = query_database_with_metadata(
            query=query if query else None,
            top_k=top_k,
            categories=categories if categories else None,
            organizations=organizations if organizations else None,
            resource_type=resource_type if resource_type else None,
            file_type=file_type if file_type else None
        )
        
        # Handle error response from vector DB
        if vector_response.get('error'):
            error_status = vector_response.get('status_code', 500)
            return Response({
                "error": vector_response.get('message', 'Vector database error'),
                "count": 0,
                "next": None,
                "previous": None,
                "results": [],
                "search_metadata": {
                    "query": query,
                    "vector_db_error": True
                }
            }, status=error_status)
        
        # Extract results from vector DB response
        all_results = vector_response.get('results', [])
        total_results = vector_response.get('total_results', len(all_results))
        
        # Apply pagination (slice results based on offset and limit)
        paginated_results = all_results[offset:offset + limit] if offset < len(all_results) else []
        
        # Serialize results
        serializer = MediaSearchResultSerializer(paginated_results, many=True)
        
        # Build pagination URLs
        base_url = request.build_absolute_uri(request.path)
        next_url = None
        previous_url = None
        
        if offset + limit < total_results:
            next_offset = offset + limit
            next_url = f"{base_url}?q={query}&limit={limit}&offset={next_offset}"
            if categories:
                next_url += f"&categories={','.join(categories)}"
            if organizations:
                next_url += f"&organizations={','.join(organizations)}"
            if resource_type:
                next_url += f"&resource_type={','.join(resource_type)}"
            if file_type:
                next_url += f"&file_type={','.join(file_type)}"
        
        if offset > 0:
            previous_offset = max(0, offset - limit)
            previous_url = f"{base_url}?q={query}&limit={limit}&offset={previous_offset}"
            if categories:
                previous_url += f"&categories={','.join(categories)}"
            if organizations:
                previous_url += f"&organizations={','.join(organizations)}"
            if resource_type:
                previous_url += f"&resource_type={','.join(resource_type)}"
            if file_type:
                previous_url += f"&file_type={','.join(file_type)}"
        
        # Build response in DRF pagination format
        response_data = {
            "count": total_results,
            "next": next_url,
            "previous": previous_url,
            "results": serializer.data,
            "search_metadata": {
                "query": query,
                "top_k": top_k,
                "offset": offset,
                "limit": limit,
                "returned_results": len(serializer.data),
                "search_config": vector_response.get('search_config', {})
            }
        }
        
        print(f"[MediaSearchV2View] Returning {len(serializer.data)} results out of {total_results} total")
        
        return Response(response_data, status=status.HTTP_200_OK)
    
    def _parse_list_param(self, param_value):
        """
        Parse comma-separated string parameter into a list.
        Returns empty list if param is empty.
        """
        if not param_value or not param_value.strip():
            return []
        return [item.strip() for item in param_value.split(',') if item.strip()]
