from import_export.admin import ExportActionMixin
from django.contrib import admin
from django.db.models import Q
from simple_history.admin import SimpleHistoryAdmin
from chatbot.filter.admin_filter import (CompanyChatCompanyFilter, ChatSessionFilter, ProfileCityFilter,
                                         ProfileStateFilter, ProfileCompanyChatFilter, ProfileEmailFilter)
from chatbot.filter.custom_date_from_filter import CustomAdvanceDateFilter
from chatbot.models import Company, Profile, ProfileType, CompanyBot, CompanyChat, ChatSession, \
    CompanyBotTypeChoices
from chatbot.models.company_models import CompanyStateMachine
from chatbot.resources.resource import CompanyChatResource
from chatbot.resources.company_resource import ChatSessionResource


class CompanyStateMachineAdmin(admin.TabularInline):
    model = CompanyStateMachine
    extra = 1


class CompanyAdmin(admin.ModelAdmin):
    list_display = ('name', 'created_at', 'status')
    search_fields = ('name', )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        user_email = request.user.email
        profile = Profile.objects.filter(email=user_email)
        if request.user.is_superuser:
            return qs
        elif len(profile) > 0 and profile[0].profile_type == ProfileType.MODERATOR:
            return qs.filter(id=profile[0].company.id)
        else:
            return qs.none()


@admin.register(CompanyBot)
class CompanyBotAdmin(SimpleHistoryAdmin):
    list_display = ('name', 'company', 'context')
    list_filter = ('company', )
    inlines = []

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        user_email = request.user.email
        profile = Profile.objects.filter(email=user_email)
        if request.user.is_superuser:
            return qs
        elif len(profile) > 0 and profile[0].profile_type == ProfileType.MODERATOR:
            return qs.filter(company=profile[0].company)
        else:
            return qs.none()

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        user = request.user
        user_email = request.user.email
        profile = Profile.objects.filter(email=user_email)
        if not user.is_superuser and len(profile) > 0 and profile[0].profile_type == ProfileType.MODERATOR:
            company_field = form.base_fields.get('company')
            if company_field:
                form.base_fields['company'].queryset = form.base_fields['company'].queryset.filter(
                    id=profile[0].company.id)
            form.base_fields = {field_name: form.base_fields[field_name] for field_name in form.base_fields
                                if field_name not in ['llm_model', 'llm_key']}
        form.base_fields = {field_name: form.base_fields[field_name] for field_name in form.base_fields}
        return form

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        # This method is called when the admin change form is rendered.
        if object_id:
            obj = self.model.objects.get(pk=object_id)
            if obj.bot_type == CompanyBotTypeChoices.STATE_MACHINE:
                # If the bot_type is 'state machine', include the inline.
                self.inlines = [CompanyStateMachineAdmin]
            else:
                # Otherwise, no inlines.
                self.inlines = []
        else:
            # For the add form, decide if you want the inline to be shown or not.
            # This example assumes not.
            self.inlines = []
        return super().changeform_view(request, object_id, form_url, extra_context)


@admin.register(CompanyChat)
class CompanyChatAdmin(ExportActionMixin, admin.ModelAdmin):
    list_display = ('session', 'sender', 'receiver', 'message', 'created_at', 'message_type')
    list_filter = (CustomAdvanceDateFilter, ProfileCompanyChatFilter, ProfileEmailFilter, 'session', CompanyChatCompanyFilter)
    search_fields = ('session', 'message__icontains')
    actions = ['export_selected']
    list_export = ('csv', 'xlsx')
    list_per_page = 20
    raw_id_fields = ('sender', 'receiver')

    resource_class = CompanyChatResource


    def get_queryset(self, request):
        qs = super().get_queryset(request)
        user_email = request.user.email
        profile = Profile.objects.filter(email=user_email).select_related('company').first()
        if request.user.is_superuser:
            return qs.prefetch_related('sender__company', 'receiver__company')
        elif profile and profile.profile_type == ProfileType.MODERATOR:
            return qs.filter(
                Q(sender__company=profile.company) | Q(receiver__company=profile.company)
            ).prefetch_related('sender__company', 'receiver__company')
        else:
            return qs.none()

    def get_search_results(self, request, queryset, search_term):
        queryset, use_distinct = super().get_search_results(request, queryset, search_term)

        user_email = request.user.email
        profile = Profile.objects.filter(email=user_email).select_related('company').first()
        if not request.user.is_superuser and profile and profile.profile_type == ProfileType.MODERATOR:
            if profile.company:
                queryset = queryset.filter(
                    Q(sender__company=profile.company) | Q(receiver__company=profile.company)
            ).prefetch_related('sender__company', 'receiver__company')
        return queryset, use_distinct

    def get_list_filter(self, request):
        user = request.user
        user_email = request.user.email
        profile = Profile.objects.filter(email=user_email).select_related('company').first()
        if not user.is_superuser and profile and profile.profile_type == ProfileType.MODERATOR:
            company = profile.company
            if company.slug == 'fmch':
                return CustomAdvanceDateFilter, ProfileCompanyChatFilter, ProfileEmailFilter, 'session', \
                       ProfileCityFilter, ProfileStateFilter, 'message_type'
            if company.slug == 'tfistaging':
                return (CustomAdvanceDateFilter, ProfileCompanyChatFilter, ProfileEmailFilter, 'session',
                        CompanyChatCompanyFilter, 'stage')
        return super().get_list_filter(request)


@admin.register(ChatSession)
class ChatSessionAdmin(ExportActionMixin, admin.ModelAdmin):
    list_display = ('session', 'get_first_name', 'created_at')
    list_filter = ('session', 'title', ChatSessionFilter, 'project_id')
    search_fields = ('session', 'title', 'profile__first_name')
    raw_id_fields = ('profile',)

    resource_class = ChatSessionResource

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related('profile', 'company_bot')
        user_email = request.user.email
        profile = Profile.objects.filter(email=user_email)
        if request.user.is_superuser:
            return qs
        elif len(profile) > 0 and profile[0].profile_type == ProfileType.MODERATOR:
            return qs.filter(profile__company=profile[0].company).prefetch_related('profile__company')
        else:
            return qs.none()

    def get_list_display(self, request):
        user = request.user
        user_email = request.user.email
        profile = Profile.objects.filter(email=user_email)
        if not user.is_superuser and len(profile) > 0 and profile[0].profile_type == ProfileType.MODERATOR:
            return 'session', 'get_first_name', 'created_at'
        return 'session', 'get_first_name', 'created_at'

    def get_first_name(self, obj):
        return obj.profile.first_name if obj.profile else None
    get_first_name.short_description = 'First Name'

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        user = request.user
        user_email = request.user.email
        profile = Profile.objects.filter(email=user_email)
        # Check if the user is a moderator
        if not user.is_superuser and len(profile) > 0 and profile[0].profile_type == ProfileType.MODERATOR:
            # Exclude the fields for moderators
            form.base_fields = {field_name: form.base_fields[field_name] for field_name in form.base_fields
                                if field_name not in ['current_step']}
        return form


admin.site.register(Company, CompanyAdmin)
