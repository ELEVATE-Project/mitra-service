import json_repair
from chatbot.llm_models.llm_script import handle_bedrock_model
from chatbot.models import CompanyBot
from jinja2 import Template


def get_remaining_strands(messages):

    company_bot = CompanyBot.objects.filter(route='/oneshot_assistant').first()
    validate_bot = CompanyBot.objects.filter(route='/oneshot_validator').first()
    tool = company_bot.tool_context
    if tool and isinstance(tool, str):
        tool = json_repair.repair_json(tool, return_objects=True)

    one_shot_prompt = [
        {
            'text': company_bot.context
        }
    ]

    response = handle_bedrock_model(
        system_prompt=one_shot_prompt, messages=messages, model_name=company_bot.llm_model,
        temperature=company_bot.bot_temperature, max_token=company_bot.max_token, tools=tool
    )

    if response:
        if response.get('parameters'):
            response = response.get('parameters')
        elif response.get('input'):
            response = response.get('input')

    tool = validate_bot.tool_context
    if tool and isinstance(tool, str):
        tool = json_repair.repair_json(tool, return_objects=True)

    context_data = {
        "oneshot_assistant_response": response
    }
    template = Template(validate_bot.tag_context)
    tag_context = template.render(context_data)
    content_prompt = f"""
                {validate_bot.context}
                {tag_context}
            """
    one_shot_prompt = [
        {
            'text': content_prompt
        }
    ]

    response = handle_bedrock_model(
        system_prompt=one_shot_prompt, messages=messages, model_name=validate_bot.llm_model,
        temperature=validate_bot.bot_temperature, max_token=validate_bot.max_token, tools=tool
    )

    if response:
        if response.get('parameters'):
            response = response.get('parameters')
        elif response.get('input'):
            response = response.get('input')

    return response
