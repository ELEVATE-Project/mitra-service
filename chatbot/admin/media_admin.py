from import_export.admin import ExportActionMixin
from django.contrib import admin

from chatbot.forms import MediaAdminForm
from chatbot.models.media_models import Media, KeyValue


class KeyValueInline(admin.TabularInline):
    model = KeyValue
    extra = 1


@admin.register(Media)
class MediaAdmin(ExportActionMixin, admin.ModelAdmin):
    form = MediaAdminForm
    list_display = ('name', 'media_type', 'company')
    search_fields = ('name', )
    actions = ['export_selected']
    list_export = ('csv', 'xlsx')
    inlines = [KeyValueInline]
