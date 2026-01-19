from chatbot.llm_models.llm_script import handle_bedrock_model
from chatbot.models import CompanyBot
from chatbot.utils.chat_query_handler import ask
from jinja2 import Template
import json
import logging

from shikshalokam.utils.action_list.action_parser import unwrap_tool_values
from shikshalokam.utils.action_list.action_validator import validate_and_fix_action_list

logger = logging.getLogger('django')

def get_mitra_paraphrase_utils(messages, company_bot):
    paraphrase_prompt = company_bot.context
    paraphrase_prompt = [{'text': paraphrase_prompt}]

    paraphrase_response = handle_bedrock_model(
        system_prompt=paraphrase_prompt, messages=messages, model_name = company_bot.llm_model,
        temperature = company_bot.bot_temperature, max_token = company_bot.max_token, company_bot=company_bot, tools=json.loads(company_bot.tool_context)
    )

    logger.info("Paraphrased response: %s", json.dumps(paraphrase_response))

    # try:
    #     validate_bot = CompanyBot.objects.filter(route='/paraphrase_bot').first()
    #     if validate_bot:
    #         paraphrase_response = validate_and_fix_action_list(
    #             messages=messages, response_json=paraphrase_response, company_bot=validate_bot
    #         )
    #         logger.info("Validation applied using validate_bot for paraphrase")
    #     else:
    #         logger.info("No validate_bot found with route='/paraphrase_bot', skipping validation")

    # except CompanyBot.DoesNotExist:
    #     logger.error("validate_bot not found, proceeding without validation")
    # except Exception as validation_error:
    #     logger.error(f"Validation failed: {validation_error}, proceeding with original response")

    if 'output' in paraphrase_response:
        content = (
            paraphrase_response
            .get('output', {})
            .get('message', {})
            .get('content', [])
        )

        if isinstance(content, list):
            for item in content:
                if 'toolUse' in item:
                    tool_input = item['toolUse'].get('input')
                    if tool_input:
                        paraphrase_response = tool_input
                        break

    extracted_data = (
            paraphrase_response.pop("parameters", None)
            or paraphrase_response.pop("input", None)
    )

    if extracted_data:
        extracted_data = unwrap_tool_values(extracted_data)
        paraphrase_response = extracted_data

    logger.info(
        "Extracted paraphrase data: %s",
        json.dumps(paraphrase_response, default=str)
    )

    if isinstance(paraphrase_response, str):
        try:
            paraphrase_response = json.loads(paraphrase_response)
        except Exception:
            import json_repair
            paraphrase_response = json_repair.repair_json(
                paraphrase_response, return_objects=True
            )
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
