from chatbot.llm_models.llm_script import handle_bedrock_model
from chatbot.utils.chat_query_handler import ask
from jinja2 import Template
import json
import logging

logger = logging.getLogger('django')

def get_mitra_paraphrase_utils(messages, company_bot):
    paraphrase_prompt = company_bot.context
    paraphrase_prompt = [{'text': paraphrase_prompt}]

    paraphrase_response = handle_bedrock_model(
        system_prompt=paraphrase_prompt, messages=messages, model_name = company_bot.llm_model,
        temperature = company_bot.bot_temperature, max_token = company_bot.max_token, company_bot=company_bot, tools=json.loads(company_bot.tool_context)
    )

    logger.info("Paraphrased response: %s", json.dumps(paraphrase_response))

    paraphrase_response = paraphrase_response.get('input', {})
    return paraphrase_response


def generate_title_utils(input_data, company_bot):
    prompt = company_bot.context
    messages = [{
        'role': 'user',
        'content': [{'text': f"{input_data}"}]
    }]

    prompt = [{'text': prompt}]

    response = handle_bedrock_model(
        system_prompt=prompt, messages=messages, model_name = company_bot.llm_model,
        temperature = company_bot.bot_temperature, max_token = company_bot.max_token,
        company_bot=company_bot
    )
    response = response.get('title')
    return response
