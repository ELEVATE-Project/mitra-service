from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin
from chatbot.models import MitraProject


@admin.register(MitraProject)
class MitraProjectAdmin(SimpleHistoryAdmin):
    list_display = ('project_id', 'profile', 'created_at')
    list_filter = ('profile', 'project_id', 'program_id', 'created_at')

    raw_id_fields = ('profile', )
