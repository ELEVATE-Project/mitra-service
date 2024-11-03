from chatbot.llm_models.llm_script import handle_bedrock_model
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
                                            "Output should be in JSON format with array of remaining state."
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

    response = handle_bedrock_model(
        system_prompt=one_shot_prompt, messages=messages
        # , tools=tool
    )

    return response
