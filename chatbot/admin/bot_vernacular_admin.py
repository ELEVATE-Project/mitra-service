from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin
from chatbot.models import BotVernacular
from chatbot.models.story_vernacular_model import StoryVernacular


@admin.register(BotVernacular)
class BotVernacularAdmin(SimpleHistoryAdmin):
    list_display = ('company_bot', 'language', 'introductory_message')
    list_filter = ('company_bot', 'language')
    inlines = []
    raw_id_fields = ('company_bot', )


@admin.register(StoryVernacular)
class StoryVernacularAdmin(SimpleHistoryAdmin):
    list_display = ('company_bot', 'language')
    list_filter = ('company_bot', 'language')
    inlines = []
    raw_id_fields = ('company_bot', )
