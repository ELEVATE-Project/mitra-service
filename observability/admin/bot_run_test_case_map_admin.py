from django.contrib import admin
from observability.models import BotRunTestCaseMap


@admin.register(BotRunTestCaseMap)
class CompanyBotRunTestCaseMapAdmin(admin.ModelAdmin):
    list_display = ('bot_run', 'metric_name', 'test_case', 'status', 'created_at')
    raw_id_fields = ('bot_run', 'test_case', )