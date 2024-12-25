import json
from chatbot.llm_models.llm_script import handle_bedrock_model
from chatbot.models import CompanyBot


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

    company_bot = CompanyBot.objects.get(route='/oneshot_assistant')
    bot_context = company_bot.context

    one_shot_prompt = [
        {
            'text': bot_context
        }
    ]

    print("one_shot_prompt: ",one_shot_prompt)

    response = handle_bedrock_model(
        system_prompt=one_shot_prompt, messages=messages
        # , tools=tool
    )

    if isinstance(response, dict):
        tool_use_id = response.get('toolUseId', None)
        if tool_use_id:
            response = response.get('input').get('conversation_summary')
            if isinstance(response, str):
                response = json.loads(response)

    return response
