from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin
from chatbot.filter.custom_date_from_filter import CustomAdvanceDateFilter
from chatbot.models import I18nTag, I18nTranslation


class I18nTranslationInline(admin.TabularInline):
    """Inline admin for I18nTranslation to show translations within I18nTag admin."""
    model = I18nTranslation
    extra = 1
    fields = ('variable_name', 'language', 'value')
    ordering = ('variable_name', 'language')


@admin.register(I18nTag)
class I18nTagAdmin(SimpleHistoryAdmin):
    """Admin interface for I18nTag model."""
    list_display = (
        'tag_name', 'get_translation_count', 'created_at', 'updated_at'
    )
    list_filter = (
        CustomAdvanceDateFilter,
    )
    search_fields = ('tag_name',)
    date_hierarchy = 'created_at'
    ordering = ('tag_name',)
    inlines = [I18nTranslationInline]
    
    fieldsets = (
        ('Tag Information', {
            'fields': ('tag_name',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    readonly_fields = ('created_at', 'updated_at')
    
    def get_translation_count(self, obj):
        """Display the count of translations for this tag."""
        return obj.translations.count()
    get_translation_count.short_description = 'Translations'
    get_translation_count.admin_order_field = 'translations__count'


@admin.register(I18nTranslation)
class I18nTranslationAdmin(SimpleHistoryAdmin):
    """Admin interface for I18nTranslation model."""
    list_display = (
        'tag_id', 'variable_name', 'language', 'get_value_preview', 'created_at'
    )
    list_filter = (
        'language',
        'tag_id',
        CustomAdvanceDateFilter
    )
    search_fields = ('tag_id__tag_name', 'variable_name', 'value')
    date_hierarchy = 'created_at'
    ordering = ('tag_id', 'variable_name', 'language')
    raw_id_fields = ('tag_id',)
    
    fieldsets = (
        ('Translation Information', {
            'fields': ('tag_id', 'variable_name', 'language')
        }),
        ('Content', {
            'fields': ('value',),
            'description': 'Enter the translated text content.'
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    readonly_fields = ('created_at', 'updated_at')
    
    def get_value_preview(self, obj):
        """Display a preview of the translation value."""
        if len(obj.value) > 50:
            return f"{obj.value[:50]}..."
        return obj.value
    get_value_preview.short_description = 'Value Preview'
    
    def formfield_for_dbfield(self, db_field, request, **kwargs):
        """Customize form fields."""
        if db_field.name == 'value':
            kwargs['widget'] = admin.widgets.AdminTextareaWidget(attrs={'rows': 6, 'cols': 80})
        return super().formfield_for_dbfield(db_field, request, **kwargs)
    
    def get_queryset(self, request):
        """Optimize queryset with select_related."""
        qs = super().get_queryset(request)
        return qs.select_related('tag_id')
