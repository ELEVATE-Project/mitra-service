from django.contrib import admin
from observability.models import CompanyBotTestCases, CompanyBotTCRun, TCBotRunMetrics


class TCBotRunMetricsAdmin(admin.TabularInline):
    model = TCBotRunMetrics
    extra = 1


@admin.register(CompanyBotTestCases)
class CompanyBotTestCasesAdmin(admin.ModelAdmin):
    list_display = ('company_bot', 'testcase_input',
                    'expected_output', 'input_format')

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

    list_display = ('company_bot', 'status', 'created_at', 'updated_at')
