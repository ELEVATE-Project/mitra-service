from django.contrib import admin
from observability.models import CompanyBotTestCases, CompanyBotTCRun, TCBotRunMetrics, BotRunTestCaseMap


class TCBotRunMetricsAdmin(admin.TabularInline):
    model = TCBotRunMetrics
    extra = 1


@admin.register(CompanyBotTestCases)
class CompanyBotTestCasesAdmin(admin.ModelAdmin):
    list_display = ('company_bot', 'about', 'created_at')

    raw_id_fields = ('company_bot', )
    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        # This method is called when the admin change form is rendered.
        if object_id:
            self.inlines = [TCBotRunMetricsAdmin]
        else:
            self.inlines = []
        return super().changeform_view(request, object_id, form_url, extra_context)


@admin.register(CompanyBotTCRun)
class CompanyBotTCRunAdmin(admin.ModelAdmin):
    readonly_fields = ['status', 'metrics_result']

    raw_id_fields = ('company_bot', )
    list_display = ('company_bot', 'status', 'created_at', 'updated_at')


@admin.register(BotRunTestCaseMap)
class CompanyBotRunTestCaseMapAdmin(admin.ModelAdmin):
    list_display = ('bot_run', 'metric_name', 'test_case', 'status', 'created_at')
    raw_id_fields = ('bot_run', 'test_case', )

