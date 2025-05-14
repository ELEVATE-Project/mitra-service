from chatbot.llm_models.llm_script import handle_bedrock_model
from jinja2 import Template
import json_repair


def transliterate_text(company_bot, source_language, target_language, message_body):
    context_data = {
        "source_language": source_language,
        "target_language": target_language,
        "message_body": message_body
    }

    template = Template(company_bot.context)
    system_prompt = template.render(context_data)

    messages = [
        {
            'role': 'user',
            'content': [{'text': message_body}]
        }
    ]

    prompt_to_use = [
        {
            'text': system_prompt
        },
    ]

    response = handle_bedrock_model(
        system_prompt=prompt_to_use, messages=messages, model_name=company_bot.llm_model,
        temperature=company_bot.bot_temperature, max_token=company_bot.max_token, company_bot=company_bot
    )
    print("Response: ", response)

    if response and isinstance(response, str):
        response = json_repair.repair_json(response, return_objects=True)
        transliterated_text = response.get('transliteration', message_body)
    elif response and isinstance(response, dict):
        transliterated_text = response.get('transliteration', message_body)
    else:
        transliterated_text = message_body

    return transliterated_text
