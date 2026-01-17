from chatbot.llm_models.llm_script import handle_bedrock_model


def validate_and_fix_action_list(messages, response_json, company_bot):
    """
    Validate and fix action list using end_context prompt.
    """
    prompt = f"""
        {company_bot.end_context}
        {response_json}
    """

    system_prompt = [{
        "text": prompt
    }]

    validation_response = handle_bedrock_model(
        system_prompt=system_prompt,
        messages=messages,
        model_name=company_bot.llm_model,
        temperature=0,
        max_token=company_bot.max_token,
        company_bot=company_bot,
        is_json_response=True
    )

    if not validation_response or not isinstance(validation_response, dict):
        return None

    return validation_response
