from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from chatbot.filter.custom_date_from_filter import CustomAdvanceDateFilter
from chatbot.models.program_model import Program


@admin.register(Program)
class ProgramAdmin(SimpleHistoryAdmin):
    """
    Admin interface for the programme master list.
    Records the user who created each programme and keeps a history of every change, since
    programmes drive how reports are grouped on the dashboard.
    """

    list_display = ('name', 'program_uuid', 'created_at')
    list_filter = (CustomAdvanceDateFilter,)
    search_fields = ('name', 'program_uuid')
    ordering = ('name',)

    def save_model(self, request, obj, form, change):
        if not obj.pk:
            obj.created_by = request.user
        obj.save()
