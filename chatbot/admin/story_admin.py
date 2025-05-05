from django.utils.html import format_html
from django.contrib import admin
from django.db.models import Q
from chatbot.filter.admin_filter import StoryCompanyFilter, StoryStateFilter, StoryDistrictFilter, StoryBlockFilter
from chatbot.models import StoryTag, StoryMedia, Story, Profile, ProfileType, MediaTypeChoices
from chatbot.models.geo_models import ProfileAddress
from chatbot.resources.story_resource import (
    redirect_to_export_view, generate_csv_response, generate_xls_response, generate_docx_response,
    get_story_fields, get_story_data, generate_zip_response
)
from chatbot.utils.shikshalokam_story_utils import update_story_pdf
from django.urls import path
from django.shortcuts import render
import tablib


class StoryTagInline(admin.TabularInline):
    model = StoryTag
    exclude = ['created_by']
    extra = 1  # Number of empty forms to display for adding new tags


class StoryMediaInline(admin.TabularInline):
    model = StoryMedia
    exclude = ['base64_str', 'file']
    extra = 0
    readonly_fields = ['public_url']

    def public_url(self, obj):
        url = obj.get_public_url()
        if obj.media_type == MediaTypeChoices.PDF:
            return url
        return format_html('<img src="%s" width="100" height="100" />' % url)

    public_url.short_description = 'Public URL'


@admin.register(Story)
class StoryAdmin(admin.ModelAdmin):
    list_display = ('title', 'author', 'session', 'created_at',)
    list_filter = (
        'created_at', StoryCompanyFilter, 'author', 'session', StoryStateFilter,
        StoryDistrictFilter, StoryBlockFilter
    )
    search_fields = ('title', 'session',)
    exclude = ('formatted_content', )
    inlines = [StoryTagInline, StoryMediaInline]
    list_per_page = 20


    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related('author').defer('formatted_content')
        user_email = request.user.email
        profile = Profile.objects.filter(email=user_email).first()
        if request.user.is_superuser:
            return qs
        elif profile and profile.profile_type == ProfileType.MODERATOR:
            profile_address = ProfileAddress.objects.filter(profile=profile).first()
            print("profile_address: ", profile_address)
            query = Q(author__company=profile.company)
            print("Query: ", query)
            if profile_address and profile_address.district:
                query &= Q(author__profile__profile_address__district=profile_address.district)
            if profile_address and profile_address.state:
                query &= Q(author__profile__profile_address__state=profile_address.state)
            results = qs.filter(query)
            print("Filtered results:", results)
            return results
            # return qs.filter(query)
        else:
            return qs.none()

    def save_model(self, request, obj, form, change):
        print(f"Story saved: {obj.title}")
        flow = obj.other_params.get('flow') if obj.other_params else None
        update_story_pdf(
            access_token=None, session=obj.session, flow=flow,
            is_edit_story=False
        )

        super().save_model(request, obj, form, change)

    actions = [redirect_to_export_view]

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('export_stories/', self.admin_site.admin_view(self.export_stories_view), name='export_stories'),
        ]
        return custom_urls + urls

    def export_stories_view(self, request):
        ids = request.GET.get('ids', '')
        selected_ids = ids.split(',') if ids else []
        stories = Story.objects.filter(id__in=selected_ids)

        if request.method == 'POST':
            export_format = request.POST.get('format')
            dataset = tablib.Dataset()
            fields_to_export = [
                "id", "title", "author", "content", "blurb", "objective", "action_steps", "impact",
                "location", "language", "stage", "created_at", "organisation"
            ]
            # fields_to_export=[]
            headers = get_story_fields(stories, fields_to_export)
            dataset.headers = headers
            for story in stories:
                dataset.append(get_story_data(story, headers))

            if export_format == 'csv':
                return generate_csv_response(dataset)
            elif export_format == 'xls':
                return generate_xls_response(dataset)
            elif export_format == 'docx':
                return generate_docx_response(stories, fields_to_export)
            elif export_format == 'zip-pdf':
                return generate_zip_response(stories)


        return render(request, 'admin/export_story_format.html', {'ids': ids})
