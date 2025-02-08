import json

from chatbot.llm_models.llm_script import handle_bedrock_model
from chatbot.models import CompanyBot
from chatbot.pompts.one_shot_prompt import get_remaining_stage_prompt


def get_remaining_strands(messages):

    tool = {
        "toolConfig": {
            "tools": [
                {
                    "toolSpec": {
                        "name": "get_state_information",
                        "description": "Get array of remaining state you want to be in.",
                        "inputSchema": {
                            "json": {
                                "type": "object",
                                "properties": {
                                    "conversation_summary": {
                                        "type": "string",
                                        "description": (
                                            "Summary of the conversation. "
                                        )
                                    }
                                },
                                "required": ["conversation_summary"]
                            }
                        }
                    }
                }
            ]
        }
    }

    one_shot_prompt = get_remaining_stage_prompt()
    company_bot = CompanyBot.objects.filter(route='/oneshot_assistant').first()
    response = handle_bedrock_model(
        system_prompt=one_shot_prompt, messages=messages, model_name=company_bot.llm_model,
        temperature=company_bot.bot_temperature, max_token=company_bot.max_token
    )

    if isinstance(response, dict):
        tool_use_id = response.get('toolUseId', None)
        if tool_use_id:
            response = response.get('input').get('conversation_summary')
            if isinstance(response, str):
                response = json.loads(response)

    return response
