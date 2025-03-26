from import_export.admin import ExportActionMixin
from django.contrib import admin

from chatbot.forms import MediaAdminForm
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


@admin.register(MediaTemplate)
class MediaTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'template_type', 'created_at')
    list_filter = ('created_at', 'name', 'template_type')
