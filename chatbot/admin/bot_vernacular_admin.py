from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin
from chatbot.models import BotVernacular


@admin.register(BotVernacular)
class BotVernacularAdmin(SimpleHistoryAdmin):
    list_display = ('company_bot', 'language', 'introductory_message')
    list_filter = ('company_bot', 'language')
    inlines = []
    raw_id_fields = ('company_bot', )
