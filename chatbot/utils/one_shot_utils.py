import json_repair
from chatbot.llm_models.llm_script import handle_bedrock_model
from chatbot.models import CompanyBot
from chatbot.pompts.one_shot_prompt import get_remaining_stage_prompt


def get_remaining_strands(messages):

    one_shot_prompt = get_remaining_stage_prompt()
    company_bot = CompanyBot.objects.filter(route='/oneshot_assistant').first()
    tool = company_bot.tool_context
    if tool and isinstance(tool, str):
        tool = json_repair.repair_json(tool, return_objects=True)
    response = handle_bedrock_model(
        system_prompt=one_shot_prompt, messages=messages, model_name=company_bot.llm_model,
        temperature=company_bot.bot_temperature, max_token=company_bot.max_token, tools=tool
    )
    if response:
        if response.get('parameters'):
            response = response.get('parameters')
        elif response.get('input'):
            response = response.get('input')

    return response
