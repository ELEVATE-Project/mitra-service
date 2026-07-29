# Admin registration for UsageCostLog.
# The default changelist is suppressed in favour of a custom dashboard that
# aggregates cost by call type, provider, bot, and session with charts.
from django.contrib import admin
from django.shortcuts import redirect
from django.urls import path, reverse
from chatbot.models import UsageCostLog


# Purpose:  Django admin registration for UsageCostLog. Replaces the default
#           record list with a cost monitoring dashboard and registers four
#           custom URL routes under the admin namespace.
# Routes:   dashboard/                    — full dashboard (charts + tables)
#           dashboard/session/<pk>/       — per-session call breakdown
#           dashboard/sessions-table/     — AJAX partial for sessions table
#           dashboard/session-cost-chart/ — JSON endpoint for bar chart pagination
# Note:     The default changelist redirects to the dashboard, except FK popup
#           selectors which still use the standard changelist.
@admin.register(UsageCostLog)
class UsageCostLogAdmin(admin.ModelAdmin):
    list_display = (
        'session', 'call_type', 'provider', 'model_name', 'input_units', 'output_units',
        'total_cost', 'company_bot', 'created_at'
    )
    list_filter = ('call_type', 'provider', 'company_bot', 'created_at')
    search_fields = ('session__session', 'model_name')
    raw_id_fields = ('session', 'profile', 'company_bot')
    readonly_fields = ('created_at',)
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)

    # Redirect the default changelist to the dashboard.
    # _popup guard preserves FK selector popups (e.g. from other admin pages).
    def changelist_view(self, request, extra_context=None):
        if '_popup' in request.GET:
            return super().changelist_view(request, extra_context)
        url = reverse('admin:chatbot_usagecostlog_dashboard')
        query_string = request.GET.urlencode()
        if query_string:
            url = f'{url}?{query_string}'
        return redirect(url)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                'dashboard/',
                self.admin_site.admin_view(self.dashboard_view),
                name='chatbot_usagecostlog_dashboard',
            ),
            path(
                'dashboard/session/<int:session_pk>/',
                self.admin_site.admin_view(self.session_detail_view),
                name='chatbot_usagecostlog_session_detail',
            ),
            path(
                'dashboard/sessions-table/',
                self.admin_site.admin_view(self.sessions_table_view),
                name='chatbot_usagecostlog_sessions_table',
            ),
            path(
                'dashboard/session-cost-chart/',
                self.admin_site.admin_view(self.session_cost_chart_view),
                name='chatbot_usagecostlog_session_cost_chart',
            ),
        ]
        return custom_urls + urls

    def dashboard_view(self, request):
        from chatbot.views.admin.usage_admin_views import usage_cost_dashboard
        return usage_cost_dashboard(request)

    def sessions_table_view(self, request):
        from chatbot.views.admin.usage_admin_views import usage_cost_sessions_partial
        return usage_cost_sessions_partial(request)

    def session_cost_chart_view(self, request):
        from chatbot.views.admin.usage_admin_views import usage_cost_session_chart
        return usage_cost_session_chart(request)

    def session_detail_view(self, request, session_pk):
        from chatbot.views.admin.usage_admin_views import usage_cost_session_detail
        return usage_cost_session_detail(request, session_pk)
