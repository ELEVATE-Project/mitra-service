import re
from django.db import connection
import json_repair
from chatbot.models import CompanyBotDynamicContextType
from datetime import datetime, date, timedelta


def run_sql_from_string(string):
    print(string)
    matches = re.findall(r'\{\{\s*(.*?)\s*\}\}', string)

    if not matches:
        return string

    replacements = []

    for sql in matches:
        print(sql)
        with connection.cursor() as cursor:
            cursor.execute(sql)

            fetched_results = cursor.fetchall()
            columns = [col[0] for col in cursor.description]
            result_str = str([dict(zip(columns, row)) for row in fetched_results])

            replacements.append(result_str)

    for i, sql in enumerate(matches):
        string = string.replace(f"{{{{ {sql} }}}}", replacements[i])

    print('Resultant string: {}'.format(string))
    return string


def get_todays_date(company_bot):
    today_date = ""
    try:
        if company_bot and company_bot.dynamic_context_type == CompanyBotDynamicContextType.SQL_QUERY:
            dynamic_context = company_bot.dynamic_context
            if isinstance(dynamic_context, str):
                dynamic_context = json_repair.repair_json(dynamic_context, return_objects=True)
                print("dynamic_context: ", dynamic_context)

            dynamic_date_text = dynamic_context.get('date_text') or ""
            print("dynamic_date_text: ", dynamic_date_text)
            sql_result = run_sql_from_string(dynamic_context.get('date'))
            print("Resultant string:", sql_result)

            parsed_date = None
            print("Type sql_result", type(sql_result))
            if isinstance(sql_result, str):
                match = re.search(r"datetime\.date\((\d+), (\d+), (\d+)\)", sql_result)
                if match:
                    year, month, day = map(int, match.groups())
                    parsed_date = date(year, month, day)

            elif isinstance(sql_result, list) and len(sql_result) > 0:
                val = sql_result[0].get('current_date')
                if isinstance(val, date):
                    parsed_date = val
                elif isinstance(val, str):
                    parsed_date = datetime.strptime(val, "%d %B %Y").date()
            print("parsed_date: ", parsed_date)
            if parsed_date:
                today_weekday = parsed_date.strftime('%A')
                yesterday = parsed_date - timedelta(days=1)
                tomorrow = parsed_date + timedelta(days=1)
                last_week = parsed_date - timedelta(weeks=1)

                today_date = f"{parsed_date.strftime('%d %B %Y')} ({today_weekday}), " \
                             f"Yesterday: {yesterday.strftime('%d %B %Y')} ({yesterday.strftime('%A')}), " \
                             f"Tomorrow: {tomorrow.strftime('%d %B %Y')} ({tomorrow.strftime('%A')}), " \
                             f"Last Week: {last_week.strftime('%d %B %Y')} ({last_week.strftime('%A')})"
                print("parsed today_date: ", today_date)

    except Exception as e:
        print("Error while parsing today's date:", e)
    print("DATE:", today_date)
    return today_date
