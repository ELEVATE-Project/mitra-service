from django.contrib import admin
from chatbot.form.media.media_form import MediaAdminForm
from chatbot.models import Tag, Profile
from chatbot.models.media_models import Media, KeyValue, MediaTemplate
from chatbot.views.admin.media_upload_views import (
    BatchMediaUploadView,
    BatchMediaExtractView,
    BatchMediaSaveView,
    BatchMediaTaskStatusView,
    BatchMediaRetryExtractView,
    BatchMediaRetrySaveView
)


class KeyValueInline(admin.TabularInline):
    model = KeyValue
    extra = 1


@admin.register(Media)
class MediaAdmin(admin.ModelAdmin):
    form = MediaAdminForm
    list_display = ('name', 'media_type',)
    search_fields = ('name',)
    actions = ['export_selected']
    list_export = ('csv', 'xlsx')
    inlines = [KeyValueInline]
    raw_id_fields = ('company_bot',)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)

        manual_tags = getattr(obj, '_manual_tags_to_set', [])
        auto_tags = getattr(obj, '_auto_tags_to_preserve', [])

        print("manual_tags to set:", manual_tags)
        print("auto_tags to preserve:", auto_tags)

        obj.tags.set(manual_tags + auto_tags)

    def get_fieldsets(self, request, obj=None):
        # Base fieldsets
        fieldsets = [
            (None, {
                'fields': (
                'name', 'file', 'url', 'description', 'extracted_text', 'priority', 'media_type', 'company_bot')
            }),
            ('Manual Tags', {
                'fields': ('manual_tags',),
            }),
        ]

        # Only add auto_tags fieldset if the object exists and has auto tags
        if obj and obj.pk:
            # Check if this media has any auto tags
            if obj.tags.filter(created_by_id=1).exists():
                fieldsets.append(
                    ('Auto Tags', {
                        'fields': ('auto_tags',),
                        'description': 'Automatically generated tags'
                    })
                )

        return fieldsets

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
        ]
        return custom_urls + urls


@admin.register(Tag)
class MasterTagAdmin(admin.ModelAdmin):
    list_display = ('name', 'status', 'created_by', 'created_at')
    list_filter = ('created_at', 'name', 'created_by')
    raw_id_fields = ('created_by',)

    def save_model(self, request, obj, form, change):
        if not obj.pk:
            try:
                profile = Profile.objects.get(email=request.user.email)
            except Profile.DoesNotExist:
                profile = None
            obj.created_by = profile
        super().save_model(request, obj, form, change)
