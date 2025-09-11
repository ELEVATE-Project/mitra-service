from django.contrib import admin
from .generic_upload_admin import BatchUploadMixin
from chatbot.form.media.media_form import MediaAdminForm
from chatbot.models import Tag, Profile, TagChoices, TagSourceChoices
from chatbot.models.media_models import Media, KeyValue, MediaImage
from chatbot.views.admin.media_upload_views import (
    BatchMediaUploadView,
    BatchMediaExtractView,
    BatchMediaSaveView,
    BatchMediaTaskStatusView,
    BatchMediaRetryExtractView,
    BatchMediaRetrySaveView, VectorDBTaskStatusView, GetCachedItemView
)
from simple_history.admin import SimpleHistoryAdmin
from chatbot.models.enums import ProfileType


class KeyValueInline(admin.TabularInline):
    model = KeyValue
    extra = 1


class MediaImagesInline(admin.TabularInline):
    model = MediaImage
    extra = 1
    fk_name = 'media'
    fields = ('name', 'media_type', 'page', 'width', 'height')
    readonly_fields = ('created_at',)


@admin.register(Media)
class MediaAdmin(SimpleHistoryAdmin, admin.ModelAdmin):
    form = MediaAdminForm
    list_display = ('file_name', 'get_title', 'media_type', 'parent__name', 'created_at')
    search_fields = ('name', 'key_values__value')
    actions = ['export_selected']
    list_export = ('csv', 'xlsx')
    inlines = [KeyValueInline, MediaImagesInline]
    raw_id_fields = ('company_bot', 'parent')

    def file_name(self, obj):
        return obj.name

    file_name.short_description = "File name"

    def get_title(self, obj):
        """Get TITLE from key-value pairs"""
        try:
            title_kv = obj.key_values.filter(key__iexact='title').first()
            if title_kv and title_kv.value:
                # Truncate long titles for display
                title = title_kv.value
                if len(title) > 50:
                    return f"{title[:47]}..."
                return title
            return "-"
        except Exception:
            return "-"

    get_title.short_description = 'Title'
    get_title.admin_order_field = 'key_values__value'

    def get_queryset(self, request):
        """Optimize queries by prefetching related objects"""
        qs = super().get_queryset(request)
        return qs.prefetch_related('key_values', 'tags', 'parent')

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)

        manual_tags = getattr(obj, '_manual_tags_to_set', [])
        auto_tags = getattr(obj, '_auto_tags_to_preserve', [])

        print("manual_tags to set:", manual_tags)
        print("auto_tags to preserve:", auto_tags)

        obj.tags.set(manual_tags + auto_tags)

    def get_fieldsets(self, request, obj=None):
        # Check if user is a MODERATOR
        is_moderator = False
        try:
            profile = Profile.objects.get(email=request.user.email)
            is_moderator = profile.profile_type == ProfileType.MODERATOR
            print("Is User Moderator: ", is_moderator)
        except Profile.DoesNotExist:
            is_moderator = False

        if is_moderator:
            base_fields = ('name', 'file', 'url', 'description', 'extracted_text', 'media_type')
        else:
            base_fields = (
                'name', 'file', 'url', 'description', 'extracted_text', 'priority', 'media_type',
                'company_bot', 'parent'
            )

        fieldsets = [
            (None, {
                'fields': base_fields
            }),
            ('Manual Tags', {
                'fields': ('manual_tags',),
            }),
        ]

        if obj and obj.pk:
            if obj.tags.filter(created_by_id=1).exists():
                fieldsets.append(
                    ('Auto Tags', {
                        'fields': ('auto_tags',),
                        'description': 'Automatically generated tags'
                    })
                )

        return fieldsets

    def get_actions(self, request):
        """Remove the delete selected action"""
        actions = super().get_actions(request)
        # if 'delete_selected' in actions:
        #     del actions['delete_selected']
        return actions

    def get_urls(self):
        """Add custom URLs for batch upload"""
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path('batch-upload/',
                 self.admin_site.admin_view(BatchMediaUploadView.as_view()),
                 name='chatbot_media_batch_upload'),
            path('api/batch-extract/',
                 self.admin_site.admin_view(BatchMediaExtractView.as_view()),
                 name='chatbot_media_batch_extract'),
            path('api/batch-save/',
                 self.admin_site.admin_view(BatchMediaSaveView.as_view()),
                 name='chatbot_media_batch_save'),
            path('api/batch-task-status/',
                 self.admin_site.admin_view(BatchMediaTaskStatusView.as_view()),
                 name='chatbot_media_task_status'),
            path('api/retry-extract/',
                 self.admin_site.admin_view(BatchMediaRetryExtractView.as_view()),
                 name='chatbot_media_retry_extract'),
            path('api/retry-save/',
                 self.admin_site.admin_view(BatchMediaRetrySaveView.as_view()),
                 name='chatbot_media_retry_save'),
            path('api/vector-db-task-status/',
                 self.admin_site.admin_view(VectorDBTaskStatusView.as_view()),
                 name='chatbot_media_vector_db_task_status'),
            path('api/get-cached-item/',
                 self.admin_site.admin_view(GetCachedItemView.as_view()),
                 name='chatbot_media_get_cached_item'),
        ]
        return custom_urls + urls


@admin.register(Tag)
class MasterTagAdmin(BatchUploadMixin, admin.ModelAdmin):
    list_display = ('name', 'status', 'source_type', 'created_by', 'created_at')
    list_filter = ('created_at', 'name', 'created_by', 'source_type')
    raw_id_fields = ('created_by',)
    readonly_fields = ('source_type', 'company', 'created_by')

    enable_batch_upload = True
    batch_upload_fields = ['name', 'status', 'description', 'created_by']

    def save_model(self, request, obj, form, change):
        print("In save")
        if not obj.pk:
            print("obj.pk= ", obj.pk)
            try:
                print("request.user.email: ", request.user.email)
                profile = Profile.objects.get(email=request.user.email)
                print("profile found: ", profile)
            except Profile.DoesNotExist:
                print("Exception profile doesnot exist")
                profile = None
            obj.created_by = profile
            obj.status = TagChoices.APPROVED
            obj.source_type = TagSourceChoices.MANUAL
        super().save_model(request, obj, form, change)
