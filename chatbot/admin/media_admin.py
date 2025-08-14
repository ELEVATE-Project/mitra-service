from import_export.admin import ExportActionMixin
from django.contrib import admin
from chatbot.form.media.media_form import MediaAdminForm
from chatbot.models import Tag, Profile
from chatbot.models.media_models import Media, KeyValue, MediaTemplate


class KeyValueInline(admin.TabularInline):
    model = KeyValue
    extra = 1


@admin.register(Media)
class MediaAdmin(ExportActionMixin, admin.ModelAdmin):
    form = MediaAdminForm
    list_display = ('name', 'media_type',)
    search_fields = ('name', )
    actions = ['export_selected']
    list_export = ('csv', 'xlsx')
    inlines = [KeyValueInline]
    raw_id_fields = ('company_bot', )

    def get_fieldsets(self, request, obj=None):
        # Base fieldsets
        fieldsets = [
            (None, {
                'fields': ('name', 'file', 'url', 'description', 'priority', 'media_type', 'company_bot')
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

# @admin.register(MediaTemplate)
# class MediaTemplateAdmin(admin.ModelAdmin):
#     list_display = ('name', 'template_type', 'created_at')
#     list_filter = ('created_at', 'name', 'template_type')


@admin.register(Tag)
class MasterTagAdmin(admin.ModelAdmin):
    list_display = ('name', 'status', 'created_by', 'created_at')
    list_filter = ('created_at', 'name', 'created_by')
    raw_id_fields = ('created_by', )

    def save_model(self, request, obj, form, change):
        if not obj.pk:
            try:
                profile = Profile.objects.get(email=request.user.email)
            except Profile.DoesNotExist:
                profile = None
            obj.created_by = profile
        super().save_model(request, obj, form, change)
