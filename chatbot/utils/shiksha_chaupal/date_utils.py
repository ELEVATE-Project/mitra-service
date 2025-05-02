from chatbot.llm_models.llm_script import handle_bedrock_model, handle_openai_model
from chatbot.models import CompanyBot, LLMProvider
from chatbot.utils.chat_utils import get_guided_chat
from chatbot.utils.shiksha_chaupal.base_utils import get_guided_prompt
import logging


logger = logging.getLogger('django')


def handle_date_prompt(intro_mssg, profile, company_chats, other_info):
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
    response=None
    if company_bot.provider == LLMProvider.BEDROCK_CONVERSE:
        try:
            response = handle_bedrock_model(
                system_prompt=prompt_to_use, messages=messages, model_name=company_bot.llm_model,
                temperature=company_bot.bot_temperature, max_token=company_bot.max_token, company_bot=company_bot
            )
        except Exception as e:
            logger.error(f"Got Error: %s", e)
            print(f"Got Error: {e}")
            response = None
    elif company_bot.provider == LLMProvider.OPENAI:
        response = handle_openai_model(
            system_prompt=prompt_to_use, messages=messages, model_name=company_bot.llm_model,
            temperature=company_bot.bot_temperature, max_token=company_bot.max_token,
            is_json_response=True
        )

    return response
