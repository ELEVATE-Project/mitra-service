from django.contrib import admin
from observability.models import CompanyBotTCRun


@admin.register(CompanyBotTCRun)
class CompanyBotTCRunAdmin(admin.ModelAdmin):
    readonly_fields = ['status', 'metrics_result']
    raw_id_fields = ('company_bot', )
    list_display = ('company_bot', 'status', 'created_at', 'updated_at')