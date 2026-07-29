# View functions backing the Usage Cost Dashboard admin pages.
# Registered as custom admin URLs in UsageCostLogAdmin.get_urls() rather than
# as standalone URL patterns so they inherit admin authentication and jazzmin context.
from django.contrib import admin
from django.core.paginator import Paginator
from django.db.models import Sum
from django.db.models.functions import TruncDate
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
import datetime

from chatbot.models import ChatSession, CompanyBot, UsageCostLog

SESSION_COST_CHART_PAGE_SIZE = 50


# Purpose: Safely parses the optional 'bot' query param into an int PK.
# Output:  int, or None if absent/non-numeric (falls back to "all bots" instead of a 500).
def _get_bot_id_param(request):
    bot_id = request.GET.get('bot')
    if not bot_id:
        return None
    try:
        return int(bot_id)
    except ValueError:
        return None


# Purpose: Parses a <input type="datetime-local"> value ("YYYY-MM-DDTHH:MM") into an
#          aware datetime. Returns None for empty/unparseable input instead of raising,
#          so a malformed value just falls back to "no filter" rather than a 500.
def _parse_local_datetime(value):
    if not value:
        return None
    dt = parse_datetime(value)
    if dt is None:
        return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt)
    return dt


# Purpose: Builds context for the "Sessions and Cost" table.
# Inputs:  request — GET params: session_view (top1|top10|all), q (search),
#                    date_from/date_to (datetime-local strings), page.
#          bot_id  — Optional CompanyBot PK; when set, only sessions for that bot are shown.
# Output:  Dict with top_sessions, sessions_page, session_view, search_query,
#          date_from/date_to (raw strings, for re-populating the form inputs).
def _get_sessions_context(request, bot_id=None):
    search_query = request.GET.get('q', '').strip()
    date_from_raw = request.GET.get('date_from', '').strip()
    date_to_raw = request.GET.get('date_to', '').strip()
    date_from = _parse_local_datetime(date_from_raw)
    date_to = _parse_local_datetime(date_to_raw)

    session_view = request.GET.get('session_view', 'top10')
    if session_view not in ('top1', 'top10', 'all'):
        session_view = 'top10'
    # A date filter, like search, only makes sense against the full paginated list -
    # top1/top10 are fixed "highest cost" views, not a range a date filter could narrow.
    if search_query or date_from or date_to:
        session_view = 'all'

    # Exclude zero-cost sessions (test/system calls) to keep the dashboard focused on real spend.
    sessions_qs = ChatSession.objects.filter(total_cost__gt=0).order_by('-total_cost')
    if bot_id:
        sessions_qs = sessions_qs.filter(company_bot_id=bot_id)
    if search_query:
        sessions_qs = sessions_qs.filter(session__icontains=search_query)
    if date_from:
        sessions_qs = sessions_qs.filter(created_at__gte=date_from)
    if date_to:
        sessions_qs = sessions_qs.filter(created_at__lte=date_to)

    sessions_page = None
    if session_view == 'top1':
        top_sessions = sessions_qs[:1]
    elif session_view == 'all':
        paginator = Paginator(sessions_qs, 20)
        sessions_page = paginator.get_page(request.GET.get('page'))
        top_sessions = sessions_page
    else:
        top_sessions = sessions_qs[:10]

    return {
        'top_sessions': top_sessions,
        'sessions_page': sessions_page,
        'session_view': session_view,
        'search_query': search_query,
        'date_from': date_from_raw,
        'date_to': date_to_raw,
    }


# Purpose: Returns paginated session cost data for the "Cost by Session" bar chart.
# Inputs:  request    — GET params read via page_param for current page number.
#          page_param — Query param name to read the page number from.
#          bot_id     — Optional CompanyBot PK; when set, only sessions for that bot are included.
# Output:  Dict with labels (session IDs), values (costs), page, num_pages.
def _get_session_cost_chart_data(request, page_param='page', bot_id=None):
    sessions_qs = ChatSession.objects.filter(total_cost__gt=0).order_by('-created_at')
    if bot_id:
        sessions_qs = sessions_qs.filter(company_bot_id=bot_id)
    paginator = Paginator(sessions_qs, SESSION_COST_CHART_PAGE_SIZE)
    page = paginator.get_page(request.GET.get(page_param))

    return {
        'labels': [s.session for s in page.object_list],
        'values': [float(s.total_cost) for s in page.object_list],
        'page': page.number,
        'num_pages': paginator.num_pages,
    }


# Purpose: JSON endpoint for "Cost by Session" bar chart page navigation.
# Inputs:  request — GET params: page, bot.
# Output:  JSON: {labels, values, page, num_pages}.
def usage_cost_session_chart(request):
    bot_id = _get_bot_id_param(request)
    return JsonResponse(_get_session_cost_chart_data(request, bot_id=bot_id))


# Purpose: Renders the "Sessions and Cost" table partial for AJAX refreshes.
#          Returns only the table fragment so filter/search/pagination updates
#          don't trigger a full page reload (avoids re-rendering all charts).
# Inputs:  request — GET params: session_view, q, page, bot.
# Output:  Rendered HTML fragment (usage_cost_sessions_table.html).
def usage_cost_sessions_partial(request):
    bot_id = _get_bot_id_param(request)
    context = {
        **admin.site.each_context(request),
        **_get_sessions_context(request, bot_id=bot_id),
    }
    return render(request, 'admin/usage_cost_sessions_table.html', context)


# Purpose:      Renders the full cost monitoring dashboard.
# Inputs:       request — GET params: bot, session_view, q, page, chart_page.
#               bot     — Optional CompanyBot PK; filters all datasets to a single bot.
# Output:       Rendered dashboard page with five aggregated datasets:
#               daily cost trend (30 days), cost by call type, cost by provider,
#               cost by bot (top 20), and paginated session cost chart data.
# Side effects: None (read-only).
# Note:         admin.site.each_context injects jazzmin sidebar/nav/permission context.
def usage_cost_dashboard(request):
    bot_id = _get_bot_id_param(request)
    since = timezone.now() - datetime.timedelta(days=30)

    usage_qs = UsageCostLog.objects.filter(company_bot_id=bot_id) if bot_id else UsageCostLog.objects

    by_call_type = (
        usage_qs.values('call_type')
        .annotate(total=Sum('total_cost'))
        .order_by('-total')
    )

    by_provider = (
        usage_qs.values('provider')
        .annotate(total=Sum('total_cost'))
        .order_by('-total')
    )

    by_company_bot = (
        usage_qs.values('company_bot__name')
        .annotate(total=Sum('total_cost'))
        .order_by('-total')[:20]
    )

    daily_trend = (
        usage_qs.filter(created_at__gte=since)
        .annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(total=Sum('total_cost'))
        .order_by('day')
    )

    session_cost_chart = _get_session_cost_chart_data(request, page_param='chart_page', bot_id=bot_id)

    bots = list(CompanyBot.objects.values('id', 'name').order_by('name'))

    context = {
        **admin.site.each_context(request),
        'title': 'Cost Monitoring Dashboard',
        **_get_sessions_context(request, bot_id=bot_id),
        'by_call_type': list(by_call_type),
        'by_provider': list(by_provider),
        'by_company_bot': list(by_company_bot),
        'daily_trend_labels': [d['day'].isoformat() for d in daily_trend],
        'daily_trend_values': [float(d['total'] or 0) for d in daily_trend],
        'session_cost_chart_labels': session_cost_chart['labels'],
        'session_cost_chart_values': session_cost_chart['values'],
        'session_cost_chart_page': session_cost_chart['page'],
        'session_cost_chart_num_pages': session_cost_chart['num_pages'],
        'bots': bots,
        'selected_bot': bot_id,
    }
    return render(request, 'admin/usage_cost_dashboard.html', context)


# Purpose: Renders a per-session cost breakdown page.
# Inputs:  request    — HTTP request (admin auth required).
#          session_pk — Primary key of the ChatSession to inspect.
# Output:  Rendered page listing every UsageCostLog row for the session,
#          ordered chronologically, with session summary metadata.
def usage_cost_session_detail(request, session_pk):
    chat_session = ChatSession.objects.filter(pk=session_pk).first()
    logs = UsageCostLog.objects.filter(session_id=session_pk).order_by('created_at')

    context = {
        **admin.site.each_context(request),
        'title': 'Session Cost Breakdown',
        'chat_session': chat_session,
        'logs': logs,
    }
    return render(request, 'admin/usage_cost_session_detail.html', context)
