from chatbot.llm_models.llm_script import handle_bedrock_model
from chatbot.utils.chat_query_handler import ask
from jinja2 import Template


def get_mitra_paraphrase_utils(paraphrase_problem, should_paraphrase_text, company_bot):
    messages = [{
                    'role': 'user',
                    'content': [{'text': paraphrase_problem}]
                }]

    paraphrase_prompt = company_bot.context
    validation_prompt = company_bot.end_context
    paraphrase_prompt = [{'text': paraphrase_prompt}]
    validation_prompt = [{'text': validation_prompt}]
    print('validation_prompt: ', validation_prompt)
    validation_response = handle_bedrock_model(
        system_prompt=validation_prompt, messages=messages,  model_name = company_bot.llm_model,
        temperature = company_bot.bot_temperature, max_token = company_bot.max_token, company_bot=company_bot
    )
    print("validation_response: ", validation_response)
    is_validated = validation_response.get('is_validated')
    if is_validated.lower() == 'no' or not should_paraphrase_text:
        return validation_response
    print('paraphrase_prompt: ', paraphrase_prompt)
    paraphrase_response = handle_bedrock_model(
        system_prompt=paraphrase_prompt, messages=messages, model_name = company_bot.llm_model,
        temperature = company_bot.bot_temperature, max_token = company_bot.max_token, company_bot=company_bot
    )
    print("paraphrase_response: ", paraphrase_response)
    paraphrase_response = paraphrase_response.get('paraphrased_challenge')
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
