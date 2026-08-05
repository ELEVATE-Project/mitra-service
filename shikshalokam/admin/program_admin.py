from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from chatbot.filter.custom_date_from_filter import CustomAdvanceDateFilter
from shikshalokam.models.program_model import Program


@admin.register(Program)
class ProgramAdmin(SimpleHistoryAdmin):
    list_display = ('name', 'program_uuid', 'created_at')
    list_filter = (CustomAdvanceDateFilter,)
    search_fields = ('name', 'program_uuid')
    ordering = ('name',)

    def save_model(self, request, obj, form, change):
        if not obj.pk:
            obj.created_by = request.user
        obj.save()
