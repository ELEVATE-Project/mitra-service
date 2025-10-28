from django.contrib import admin
from observability.models import CompanyBotTCRun
from rangefilter.filters import DateRangeFilter, DateTimeRangeFilter


@admin.register(CompanyBotTCRun)
class CompanyBotTCRunAdmin(admin.ModelAdmin):
    readonly_fields = ['status', 'metrics_result']
    raw_id_fields = ('company_bot', )
    list_display = ('company_bot', 'status', 'created_at')
    
    list_filter = (
        'status',                          
        ('company_bot', admin.RelatedFieldListFilter),
        ('created_at', DateTimeRangeFilter),
    )
    
    search_fields = ('company_bot__name', 'status')
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)