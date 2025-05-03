from chatbot.llm_models.llm_script import handle_bedrock_model, handle_openai_model
from chatbot.models import CompanyBot, LLMProvider
from chatbot.utils.chat_utils import get_guided_chat
from chatbot.utils.shiksha_chaupal.base_utils import get_guided_prompt
import logging
from dateutil import parser
from datetime import datetime
import pytz
import json_repair


logger = logging.getLogger('django')
INDIA_TZ = pytz.timezone("Asia/Kolkata")


def handle_date_prompt(intro_mssg, profile, company_chats, other_info):
    bot_question = None

    if profile:
        company_bot = CompanyBot.objects.get(company=profile.company, route='/date-validator')
    else:
        company_bot = CompanyBot.objects.get(route='/date-validator')

    prompt_to_use = get_guided_prompt(
        company_bot=company_bot, system_context=company_bot.context, intro_mssg=intro_mssg, profile=profile
    )

    messages = get_guided_chat(
        company_bot=company_bot, company_chats=company_chats, intro=intro_mssg, other_info=other_info
    )

    response = None
    try:
        if company_bot.provider == LLMProvider.BEDROCK_CONVERSE:
            response = handle_bedrock_model(
                system_prompt=prompt_to_use, messages=messages, model_name=company_bot.llm_model,
                temperature=company_bot.bot_temperature, max_token=company_bot.max_token, company_bot=company_bot
            )
        elif company_bot.provider == LLMProvider.OPENAI:
            response = handle_openai_model(
                system_prompt=prompt_to_use, messages=messages, model_name=company_bot.llm_model,
                temperature=company_bot.bot_temperature, max_token=company_bot.max_token,
                is_json_response=True
            )
    except Exception as e:
        logger.error(f"Error in handle_date_prompt: {e}")
        response = None

    if not response:
        return "I am sorry, I could not understand completely. Could you rephrase this please?"

    date_type = interpret_date_response(response)
    print("date_type: ", date_type)

    end_context = json_repair.repair_json(company_bot.end_context, return_objects=True)
    print("end_context: ", end_context)

    if end_context:
        bot_question = end_context.get(date_type, None)

    return bot_question


def interpret_date_response(date_response):
    user_date = date_response.get("parsed_date", '')
    print("user_date: ", user_date)
    try:
        parsed_date = parser.parse(user_date, dayfirst=True)
        today = datetime.now(INDIA_TZ).date()
        print("today date: ", today)

        if parsed_date.date() > today:
            return "FUTURE_DATE"
        elif parsed_date.date() == today:
            return "PAST_DATE"
        else:
            return "PAST_DATE"

    except Exception:
        return "PHRASE"
