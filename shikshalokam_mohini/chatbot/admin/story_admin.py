from django.utils.html import format_html
from import_export.admin import ExportActionMixin
from django.contrib import admin
from django.db.models import Q
from chatbot.filter.admin_filter import StoryCompanyFilter, StoryLocationFilter
from chatbot.filter.custom_date_from_filter import CustomAdvanceDateFilter
from chatbot.models import StoryTag, StoryMedia, Story, Profile, ProfileType, MediaTypeChoices


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
class StoryAdmin(ExportActionMixin, admin.ModelAdmin):
    list_display = ('title', 'author', 'session', 'created_at',)
    list_filter = (CustomAdvanceDateFilter, StoryCompanyFilter, 'author', 'session', StoryLocationFilter)
    search_fields = ('title', 'session',)
    exclude = ('formatted_content', )
    inlines = [StoryTagInline, StoryMediaInline]
    list_per_page = 20

    actions = ['export_selected']
    list_export = ('csv', 'xlsx')

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related('author').defer('formatted_content')
        user_email = request.user.email
        profile = Profile.objects.filter(email=user_email).first()
        if request.user.is_superuser:
            return qs
        elif profile and profile.profile_type == ProfileType.MODERATOR:
            return qs.filter(Q(author__company=profile.company))
        else:
            return qs.none()
